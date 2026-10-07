"""Unit tests: pure business rules for Steps 4-9, with no database and no HTTP.

These run in well under a second (pytest -m unit) and pin the rules that money, documents and lifecycles depend on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from filehelp import upload
from zoikorum.domains.contract import service as contract
from zoikorum.domains.dispute import service as dispute
from zoikorum.domains.escrow import service as escrow
from zoikorum.domains.proposal import service as proposal
from zoikorum.domains.search.service import _escape_like
from zoikorum.shared import clock, uploads
from zoikorum.shared.errors import InvalidStateTransition, NotFound, ValidationFailed
from zoikorum.shared.money import Money

pytestmark = pytest.mark.unit


# ---- Money and the platform fee ------------------------------------------------------------------------------

@pytest.mark.parametrize(("gross", "bps", "fee"), [
    (1_000_000, 1000, 100_000),  # 10% of 10,000.00
    (500_000, 1000, 50_000),
    (999, 1000, 100),  # 99.9 rounds half-up to 100 minor units
    (994, 1000, 99),
    (1, 1000, 0),
    (0, 1000, 0),
])
def test_platform_fee_rounds_half_up_to_the_minor_unit(gross, bps, fee):
    assert Money(gross, "USD").percentage_bps(bps).minor == fee


def test_fee_and_net_always_add_back_to_gross():
    for gross in (1, 7, 999, 12_345, 1_000_000, 987_654_321):
        fee = Money(gross, "USD").percentage_bps(1000).minor
        assert 0 <= fee <= gross and (gross - fee) + fee == gross


# ---- Escrow -------------------------------------------------------------------------------------------------

def _alloc(state, seq=1):
    return SimpleNamespace(state=state, sequence=seq)


@pytest.mark.parametrize(("states", "funded", "released", "refunded", "expected"), [
    ([], 0, 0, 0, "UNFUNDED"),
    (["UNFUNDED", "UNFUNDED"], 0, 0, 0, "UNFUNDED"),
    (["HELD", "UNFUNDED"], 100, 0, 0, "FUNDED"),
    (["RELEASED", "HELD"], 200, 100, 0, "PARTIALLY_RELEASED"),
    (["RELEASED", "RELEASED"], 200, 200, 0, "FULLY_RELEASED"),
    (["ON_HOLD", "RELEASED"], 200, 100, 0, "DISPUTED"),  # a dispute hold wins over everything
    (["REFUNDED", "UNFUNDED"], 100, 0, 100, "REFUNDED"),
    (["PARTIALLY_RELEASED", "REFUNDED"], 200, 60, 140, "CLOSED"),
])
def test_escrow_account_status(states, funded, released, refunded, expected):
    account = SimpleNamespace(funded_minor=funded, released_minor=released, refunded_minor=refunded)
    assert escrow._status(account, [_alloc(s) for s in states]) == expected


@pytest.mark.parametrize(("gross", "fee", "refund"), [(600_000, 60_000, 400_000), (1_000_000, 100_000, 0), (0, 0, 1_000_000)])
def test_dispute_decision_ledger_lines_balance(gross, fee, refund):
    lines = escrow._decision_lines(_alloc("ON_HOLD"), gross, fee, refund, 1000)
    assert sum(debit for _, _, debit, _, _ in lines) == sum(credit for _, _, _, credit, _ in lines) == gross + refund
    assert any(acct == "PLATFORM_REVENUE" for _, acct, _, _, _ in lines) == bool(fee)


def test_released_and_refunded_money_can_never_move_again():
    for terminal in ("RELEASED", "REFUNDED", "PARTIALLY_RELEASED"):
        assert escrow.ALLOCATION_STATES.is_terminal(terminal)
    assert escrow.ALLOCATION_STATES.can("HELD", "ON_HOLD")  # a dispute freezes held funds
    assert not escrow.ALLOCATION_STATES.can("UNFUNDED", "RELEASED")  # nothing is released without funding
    with pytest.raises(InvalidStateTransition):
        escrow.ALLOCATION_STATES.assert_can("RELEASED", "HELD")


# ---- Contracts and milestones -------------------------------------------------------------------------------

@pytest.mark.parametrize(("frm", "to", "ok"), [
    ("PENDING_FUNDING", "IN_PROGRESS", True),
    ("PENDING_FUNDING", "SUBMITTED", False),  # no work before funding
    ("IN_PROGRESS", "SUBMITTED", True),
    ("SUBMITTED", "ACCEPTED", True),
    ("SUBMITTED", "REVISION_REQUESTED", True),
    ("REVISION_REQUESTED", "SUBMITTED", True),
    ("ACCEPTED", "DISPUTED", False),  # accepted work cannot be disputed (challenge window is 0)
    ("ACCEPTED", "SUBMITTED", False),
    ("DISPUTED", "ACCEPTED", True),
])
def test_milestone_lifecycle(frm, to, ok):
    assert contract.MILESTONE_STATES.can(frm, to) is ok


def test_contract_lifecycle_terminal_states():
    assert contract.CONTRACT_STATES.is_terminal("COMPLETED") and contract.CONTRACT_STATES.is_terminal("TERMINATED")
    assert not contract.CONTRACT_STATES.can("PENDING_SIGNATURE", "COMPLETED")  # must be signed and active first


def test_terms_hash_ignores_key_order_but_not_content():
    a = {"total": 1500, "milestones": [{"title": "M1"}], "nda": True}
    b = {"nda": True, "milestones": [{"title": "M1"}], "total": 1500}
    assert contract._hash(a) == contract._hash(b)
    assert contract._hash(a) != contract._hash({**a, "total": 1501})


def _milestone(status="SUBMITTED", due_in=timedelta(days=1), seq=1):
    return SimpleNamespace(status=status, sequence=seq, title="Master file",
                           acceptance_due_at=clock.now() + due_in if due_in is not None else None)


def test_review_window_overdue_only_for_submitted_work_past_the_deadline():
    assert contract._review_overdue(_milestone(due_in=timedelta(hours=-1)))
    assert not contract._review_overdue(_milestone(due_in=timedelta(hours=1)))
    assert not contract._review_overdue(_milestone(status="ACCEPTED", due_in=timedelta(days=-3)))
    assert not contract._review_overdue(_milestone(due_in=None))


def test_next_action_tells_each_side_what_to_do_when_review_is_overdue():
    c = SimpleNamespace(status="ACTIVE")
    late = [_milestone(due_in=timedelta(days=-1))]
    assert contract._next_action(c, late, {"BUYER", "PROFESSIONAL"}, "BUYER", "Venky").startswith("Review overdue: M1")
    assert "payment stays protected" in contract._next_action(c, late, {"BUYER", "PROFESSIONAL"}, "PROFESSIONAL", "Venky")
    on_time = [_milestone(due_in=timedelta(days=2))]
    assert contract._next_action(c, on_time, {"BUYER", "PROFESSIONAL"}, "BUYER", "Venky").startswith("Review submitted work")


# ---- Disputes -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("start", "days", "expected"), [
    (datetime(2026, 10, 9, 12, tzinfo=timezone.utc), 1, datetime(2026, 10, 12, 12, tzinfo=timezone.utc)),  # Fri + 1 = Mon
    (datetime(2026, 10, 5, 9, tzinfo=timezone.utc), 5, datetime(2026, 10, 12, 9, tzinfo=timezone.utc)),  # Mon + 5 = next Mon
    (datetime(2026, 10, 10, 9, tzinfo=timezone.utc), 1, datetime(2026, 10, 12, 9, tzinfo=timezone.utc)),  # Sat + 1 = Mon
])
def test_direct_resolution_deadline_counts_business_days(start, days, expected):
    assert dispute.add_business_days(start, days) == expected


def test_dispute_lifecycle_cannot_skip_enforcement_or_reopen():
    assert not dispute.CASE_STATES.can("DECIDED", "CLOSED")  # the decision must be enforced through escrow first
    assert dispute.CASE_STATES.is_terminal("CLOSED")
    assert not dispute.CASE_STATES.can("MEDIATION", "DIRECT_RESOLUTION")  # no going back after escalation


# ---- Requests and proposals ---------------------------------------------------------------------------------

@pytest.mark.parametrize(("served", "buyer_country", "conflict"), [
    ({"US", "GB"}, "US", False),
    ({"us"}, "US", False),  # case-insensitive
    ({"GB"}, "IN", True),
    (set(), "IN", False),  # no list means unrestricted
])
def test_jurisdiction_conflict(served, buyer_country, conflict):
    assert proposal._conflict(served, SimpleNamespace(country=buyer_country)) is conflict


def test_finished_proposals_stay_finished():
    for terminal in ("ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED"):
        assert proposal.PROPOSAL_STATES.is_terminal(terminal)
    assert not proposal.REQUEST_STATES.can("DECLINED", "OPEN")


# ---- Search -------------------------------------------------------------------------------------------------

def test_search_text_cannot_inject_like_wildcards():
    assert _escape_like("50%_off\\") == "50\\%\\_off\\\\"


# ---- Document uploads ---------------------------------------------------------------------------------------

def _model(**item):
    return uploads.UploadIn(**item)


def test_a_valid_upload_decodes_to_its_bytes():
    item = upload("brief.pdf", b"hello")
    assert uploads.checked_bytes(_model(**item)) == b"%PDF-1.4\nhello"


@pytest.mark.parametrize(("change", "code"), [
    ({"sha256": "0" * 64}, "FINGERPRINT_MISMATCH"),
    ({"name": "brief.png"}, "INVALID_FILE_TYPE"),  # extension does not match the declared type
    ({"size": 3}, "INVALID_FILE"),  # declared size does not match what arrived
    ({"dataBase64": "!!not base64!!"}, "INVALID_FILE"),
])
def test_bad_uploads_are_refused_with_a_reason(change, code):
    with pytest.raises(ValidationFailed) as err:
        uploads.checked_bytes(_model(**{**upload("brief.pdf"), **change}))
    assert err.value.code == code


def test_file_type_is_judged_by_content_not_by_name():
    disguised = upload("invoice.pdf", b"MZ\x90\x00 program", content_type="text/plain")  # no PDF header
    disguised["contentType"] = "application/pdf"
    with pytest.raises(ValidationFailed) as err:
        uploads.checked_bytes(_model(**disguised))
    assert err.value.code == "INVALID_FILE_TYPE"


def test_csv_must_be_text():
    good = upload("ledger.csv", b"date,amount\n2026-10-01,100\n", content_type="text/csv")
    assert uploads.checked_bytes(_model(**good)).startswith(b"date,amount")
    binary = upload("ledger.csv", b"\x00\x01\x02", content_type="text/csv")
    with pytest.raises(ValidationFailed):
        uploads.checked_bytes(_model(**binary))


def test_files_sent_together_have_a_total_limit(monkeypatch):
    monkeypatch.setattr(uploads, "MAX_TOTAL_BYTES", 20)
    stored = []
    monkeypatch.setattr(uploads, "get_storage", lambda: SimpleNamespace(put=lambda k, d: stored.append(k)))
    with pytest.raises(ValidationFailed) as err:
        uploads.store_uploads("t", [_model(**upload("a.pdf", b"aaaaaaaa")), _model(**upload("b.pdf", b"bbbbbbbb"))])
    assert err.value.code == "UPLOAD_TOO_LARGE" and stored == []  # nothing is stored when any check fails


def test_stored_records_keep_the_key_but_responses_hide_it(monkeypatch):
    monkeypatch.setattr(uploads, "get_storage", lambda: SimpleNamespace(put=lambda k, d: None))
    (rec,) = uploads.store_uploads("contracts/c1/m1", [_model(**upload("work.pdf"))])
    assert rec["key"] == f"contracts/c1/m1/{rec['sha256']}"
    out = uploads.file_out(rec).model_dump()
    assert out["hasFile"] is True and "key" not in out
    assert uploads.file_out({"name": "old.pdf", "sha256": "a" * 64, "size": 1}).hasFile is False


def test_old_fingerprint_only_records_cannot_be_opened():
    with pytest.raises(NotFound) as err:
        uploads.find_file([{"name": "old.pdf", "sha256": "a" * 64, "size": 1}], "a" * 64)
    assert err.value.code == "FILE_NOT_STORED"
    with pytest.raises(NotFound):
        uploads.find_file([], "b" * 64)


def test_file_responses_are_safe_to_open():
    r = uploads.file_response(b"x", "application/pdf", 'evil"; name=<script>.pdf')
    assert r.headers["content-disposition"] == 'inline; filename="evil namescript.pdf"'  # quotes, ; = < > stripped
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox"


# ---- Provider safety: circuit breaker and webhook signatures ------------------------------------------------

def _flaky(fail: list[bool]):
    def call():
        if fail.pop(0):
            raise ConnectionError("provider timed out")
        return "ok"
    return call


def test_circuit_opens_after_repeated_failures_and_fails_fast():
    from zoikorum.shared.circuit import CircuitBreaker
    from zoikorum.shared.errors import ServiceUnavailable

    b = CircuitBreaker("payment provider", failure_threshold=3, reset_seconds=30)
    fn = _flaky([True, True, True, False])
    for _ in range(3):
        with pytest.raises(ConnectionError):
            b.call(fn)
    assert b.state == "OPEN"
    with pytest.raises(ServiceUnavailable) as err:
        b.call(fn)  # the provider is not even called while open
    assert err.value.code == "PROVIDER_UNAVAILABLE" and err.value.status == 503


def test_circuit_half_opens_after_cool_down_and_closes_on_success():
    from zoikorum.shared.circuit import CircuitBreaker

    b = CircuitBreaker("payment provider", failure_threshold=1, reset_seconds=30)
    start = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    clock.set_now(start)
    with pytest.raises(ConnectionError):
        b.call(_flaky([True]))
    clock.set_now(start + timedelta(seconds=31))
    assert b.state == "HALF_OPEN"
    with pytest.raises(ConnectionError):
        b.call(_flaky([True]))  # the trial call fails: open again for another cool-down
    assert b.state == "OPEN"
    clock.set_now(start + timedelta(seconds=62))
    assert b.call(_flaky([False])) == "ok" and b.state == "CLOSED"
    clock.set_now(None)


def test_business_answers_like_a_declined_card_do_not_trip_the_breaker():
    from zoikorum.domains.payments.providers import FakeProvider
    from zoikorum.shared.circuit import CircuitBreaker, Guarded

    b = CircuitBreaker("payment provider", failure_threshold=1)
    p = Guarded(FakeProvider(), b, ("charge",))
    assert p.charge("tok_fail", 100, "USD").ok is False
    assert b.state == "CLOSED" and p.name == "fake"  # non-guarded attributes pass straight through


def test_webhook_signatures_bind_body_secret_and_time():
    from zoikorum.domains.payments.providers import sign_webhook, verify_signature

    now = int(clock.now().timestamp())
    sig = sign_webhook(b'{"id":"evt_1"}', "s3cret", now)
    assert verify_signature(sig, b'{"id":"evt_1"}', "s3cret", 300)
    assert not verify_signature(sig, b'{"id":"evt_2"}', "s3cret", 300)  # body changed
    assert not verify_signature(sig, b'{"id":"evt_1"}', "other", 300)  # wrong secret
    assert not verify_signature(sign_webhook(b"x", "s3cret", now - 301), b"x", "s3cret", 300)  # too old
    assert not verify_signature("garbage", b"x", "s3cret", 300)


def test_next_reconciliation_runs_at_one_am_utc():
    from zoikorum.domains.payments.reconciliation import next_run

    assert next_run(datetime(2026, 10, 7, 0, 30, tzinfo=timezone.utc)) == datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)
    assert next_run(datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)) == datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)


def test_payout_delay_reasons_are_plain_language():
    from zoikorum.domains.payments.service import delay_reason

    p = SimpleNamespace(status="QUEUED", failure_message=None, expected_at=None)
    assert delay_reason(p).startswith("Waiting for your payout account")
    p = SimpleNamespace(status="INITIATED", failure_message=None, expected_at=clock.now() - timedelta(hours=1))
    assert delay_reason(p).startswith("Taking longer than usual")
    p = SimpleNamespace(status="INITIATED", failure_message=None, expected_at=clock.now() + timedelta(days=1))
    assert delay_reason(p) is None
    p = SimpleNamespace(status="FAILED", failure_message="Account closed", expected_at=None)
    assert delay_reason(p).startswith("Account closed")
