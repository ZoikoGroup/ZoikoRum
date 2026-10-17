"""Money-flow gaps closed on 2026-10-12: funding only on an active contract, payments that finish after the work closed,
provider errors, refund failures, never-signed contracts, the fee fixed at activation, and spend limits."""

from __future__ import annotations


from sqlalchemy import text

from test_contract import C, accepted_contract, signed_contract
from test_dispute import D, dispute_body
from test_escrow import E, balanced, escrow_of
from zoikorum.domains.contract import service as contract_service
from zoikorum.domains.escrow import service as escrow_service
from zoikorum.domains.notification.service import EVENT_TITLES
from zoikorum.domains.payments import providers
from zoikorum.domains.payments import service as payments_service
from zoikorum.shared.errors import ServiceUnavailable, ValidationFailed
from zoikorum.shared.event_catalog import E as EV


async def fund(client, buyer, esc, ids):
    return await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": ids, "paymentMethodToken": "tok_visa"})


async def states(sf, contract_id) -> dict[int, str]:
    async with sf() as s:
        rows = (await s.execute(text("SELECT a.sequence, a.state FROM escrow.allocations a JOIN escrow.accounts x ON x.id = a.account_id "
                                     "WHERE x.contract_id = :c"), {"c": contract_id})).all()
    return dict(rows)


async def events(sf, kind: str) -> int:
    async with sf() as s:
        return await s.scalar(text("SELECT count(*) FROM platform.outbox WHERE event_type = :t"), {"t": kind})


async def test_no_funding_while_a_dispute_is_open(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1, m2 = c["milestones"]
    await fund(client, buyer, esc, [m1["id"]])
    await drain()
    assert (await client.post(D, headers=buyer.idem(), json=dispute_body(c))).status_code == 201
    await drain()
    blocked = await fund(client, buyer, esc, [m2["id"]])
    assert blocked.status_code == 409 and blocked.json()["code"] == "CONTRACT_NOT_ACTIVE"
    assert "dispute" in blocked.json()["detail"]
    assert (await escrow_of(client, buyer, c))["canFund"] is False  # the page does not offer it either
    assert (await states(sf, c["id"]))[2] == "UNFUNDED"


async def test_payment_finishing_after_the_work_closed_is_refunded(client, make_user, drain, sf, monkeypatch):
    """Checkout still open when the milestone is cancelled: the captured money goes straight back to the buyer. A refund the
    provider cannot make is announced and retried daily."""
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m2 = c["milestones"][1]
    assert (await fund(client, buyer, esc, [m2["id"]])).status_code == 200  # request recorded; the charge runs in the worker
    async with sf() as s, s.begin():  # meanwhile the milestone closes (e.g. a dispute decision ended the engagement)
        await s.execute(text("UPDATE contract.milestones SET status = 'CANCELLED' WHERE id = :m"), {"m": m2["id"]})
    failing = providers.FakeProvider()
    monkeypatch.setattr(failing, "refund", lambda *a, **k: providers.PayoutResult(False, failure_message="Card account closed"))
    monkeypatch.setattr(payments_service, "get_provider", lambda: failing)
    await drain()
    assert (await states(sf, c["id"]))[2] == "REFUNDED"
    assert await events(sf, EV.REFUND_FAILED) == 1
    monkeypatch.setattr(payments_service, "get_provider", providers.get_provider)
    async with sf() as s, s.begin():
        assert await payments_service.retry_failed_refunds(s) == 1
    async with sf() as s:
        assert await s.scalar(text("SELECT status FROM payments.refunds WHERE contract_id = :c"), {"c": c["id"]}) == "SETTLED"
    await balanced(sf)


async def test_provider_refusing_a_charge_is_a_failed_payment_not_a_stuck_one(client, make_user, drain, sf, monkeypatch):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)

    def refuse(*a, **k):
        raise ValidationFailed("Amount below the provider minimum", code="AMOUNT_TOO_SMALL")

    refusing = providers.FakeProvider()
    monkeypatch.setattr(refusing, "charge", refuse)
    monkeypatch.setattr(payments_service, "get_provider", lambda: refusing)
    await fund(client, buyer, esc, [c["milestones"][0]["id"]])
    await drain()
    assert (await states(sf, c["id"]))[1] == "UNFUNDED"
    funding = (await escrow_of(client, buyer, c))["fundings"][0]
    assert funding["status"] == "FAILED" and "minimum" in funding["failureMessage"]


async def test_funding_reverts_if_the_provider_never_starts_the_charge(client, make_user, drain, sf, monkeypatch):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)

    def down(*a, **k):
        raise ServiceUnavailable("Payment provider unavailable")

    unavailable = providers.FakeProvider()
    monkeypatch.setattr(unavailable, "charge", down)
    monkeypatch.setattr(payments_service, "get_provider", lambda: unavailable)
    await fund(client, buyer, esc, [c["milestones"][0]["id"]])
    await drain()
    assert (await states(sf, c["id"]))[1] == "FUNDING"  # retried in the background...
    async with sf() as s:
        funding_id = await s.scalar(text("SELECT id FROM escrow.fundings WHERE status = 'REQUESTED'"))
    async with sf() as s, s.begin():  # ...and after an hour of no charge at all, the buyer can try again
        await escrow_service.funding_check(s, {"fundingId": str(funding_id)})
    assert (await states(sf, c["id"]))[1] == "UNFUNDED"
    monkeypatch.setattr(payments_service, "get_provider", providers.get_provider)
    async with sf() as s, s.begin():  # a late retry does not charge a funding the buyer no longer has open
        await payments_service.charge_for_funding(s, {"fundingId": str(funding_id), "escrowAccountId": esc["id"], "contractId": c["id"],
                                                      "organizationId": c["organizationId"], "amountMinor": 1, "currency": "USD",
                                                      "paymentMethodToken": "tok_visa"})
        assert await s.scalar(text("SELECT count(*) FROM payments.payment_intents WHERE funding_id = :f"), {"f": funding_id}) == 0


async def test_an_agreement_nobody_signs_lapses(client, make_user, drain, sf):
    pro_user, pro, buyer, org, accepted, c = await accepted_contract(client, make_user, drain)
    async with sf() as s, s.begin():
        await contract_service.signature_deadline_passed(s, {"contractId": c["id"]})
        await contract_service.signature_expired(s, {"contractId": c["id"]})
    after = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert after["status"] == "TERMINATED" and {m["status"] for m in after["milestones"]} == {"CANCELLED"}


async def test_the_fee_agreed_at_activation_is_the_one_charged(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    assert esc["feeBps"] == 1000
    async with sf() as s, s.begin():  # as if the platform fee had been 5% when this engagement started
        await s.execute(text("UPDATE escrow.accounts SET fee_bps = 500 WHERE id = :a"), {"a": esc["id"]})
    m1 = c["milestones"][0]
    await fund(client, buyer, esc, [m1["id"]])
    await drain()
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Delivered"})
    await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())
    await drain()
    async with sf() as s:
        fee_bps, gross, fee = (await s.execute(text("SELECT fee_bps, gross_minor, fee_minor FROM escrow.releases WHERE milestone_id = :m"),
                                               {"m": m1["id"]})).one()
    assert fee_bps == 500 and fee == gross * 5 // 100
    await balanced(sf)


async def test_people_hear_about_money_events():
    for kind in (EV.MILESTONE_FUNDING_REMINDER, EV.MILESTONE_FUNDING_REVERSED, EV.MILESTONE_PARTIAL_ACCEPTANCE_OFFERED,
                 EV.ESCROW_RELEASE_BLOCKED, EV.REFUND_FAILED, EV.REFUND_SETTLED):
        assert kind in EVENT_TITLES


async def test_release_not_approved_is_announced(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1 = c["milestones"][0]
    await fund(client, buyer, esc, [m1["id"]])
    await drain()
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE escrow.allocations SET state = 'RELEASE_PENDING_APPROVAL' WHERE milestone_id = :m"), {"m": m1["id"]})
        await escrow_service.release_not_approved(s, {"subjectId": m1["id"], "subjectType": "Milestone", "action": "ESCROW_RELEASE"},
                                                  EV.APPROVAL_DENIED)
    assert await events(sf, EV.ESCROW_RELEASE_BLOCKED) == 1
    assert (await states(sf, c["id"]))[1] == "RELEASE_PENDING_APPROVAL"  # neither paid nor refunded on one side's word


async def test_accepted_work_whose_release_was_refused_is_escalated_and_can_be_disputed(client, make_user, drain, sf):
    """No deadlock: reminders go out, and either side can take the held payment to a payment-release dispute."""
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1 = c["milestones"][0]
    await fund(client, buyer, esc, [m1["id"]])
    await drain()
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE escrow.allocations SET state = 'RELEASE_PENDING_APPROVAL' WHERE milestone_id = :m"), {"m": m1["id"]})
        await s.execute(text("UPDATE contract.milestones SET status = 'ACCEPTED', accepted_at = now() WHERE id = :m"), {"m": m1["id"]})
        await escrow_service.release_not_approved(s, {"subjectId": m1["id"], "subjectType": "Milestone", "action": "ESCROW_RELEASE"},
                                                  EV.APPROVAL_DENIED)
    async with sf() as s:
        timer = await s.scalar(text("SELECT key FROM platform.timers WHERE kind = :k"), {"k": escrow_service.TIMER_RELEASE_ESCALATION})
    assert timer == f"{m1['id']}:1"
    async with sf() as s, s.begin():
        await escrow_service.release_escalation(s, {"milestoneId": m1["id"], "round": 1})
    assert await events(sf, EV.ESCROW_RELEASE_ESCALATED) == 1
    assert EV.ESCROW_RELEASE_ESCALATED in EVENT_TITLES

    # Accepted work can only be disputed about its payment.
    wrong = await client.post(D, headers=pro_user.idem(), json=dispute_body(c))
    assert wrong.status_code == 422 and wrong.json()["code"] == "PAYMENT_RELEASE_ONLY"
    r = await client.post(D, headers=pro_user.idem(), json=dispute_body(c, category="PAYMENT_RELEASE", outcome="FULL_RELEASE"))
    assert r.status_code in (200, 201), r.text
    await drain()
    assert (await states(sf, c["id"]))[1] == "ON_HOLD"
    assert (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["status"] == "ACTIVE"  # the rest of the work carries on
    async with sf() as s, s.begin():  # while the dispute holds it, no more reminders
        await escrow_service.release_escalation(s, {"milestoneId": m1["id"], "round": 2})
    assert await events(sf, EV.ESCROW_RELEASE_ESCALATED) == 1

    async with sf() as s, s.begin():  # the decision pays the professional
        await escrow_service.dispute_resolved(s, {"contractId": c["id"], "disputeId": r.json()["id"], "allocations": [
            {"milestoneId": m1["id"], "releaseMinor": m1["amount"]["amountMinor"], "refundMinor": 0, "milestoneOutcome": "ACCEPT"}]})
    assert (await states(sf, c["id"]))[1] == "RELEASED"
    await balanced(sf)


async def test_a_challenge_window_holds_payment_after_acceptance_and_allows_a_dispute(client, make_user, drain, sf, monkeypatch):
    """Defects found after acceptance: the payment waits for the window, the buyer may dispute inside it, then it is paid."""
    from zoikorum.config import get_settings

    monkeypatch.setattr(get_settings(), "dispute_challenge_window_days", 7)  # pinned into the contract's terms
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1, m2 = c["milestones"][0], c["milestones"][1]
    await fund(client, buyer, esc, [m1["id"], m2["id"]])
    await drain()
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE contract.milestones SET status = 'ACCEPTED', accepted_at = now() WHERE id IN (:a, :b)"),
                        {"a": m1["id"], "b": m2["id"]})
        await escrow_service.milestone_accepted(s, {"milestoneId": m1["id"]})
        await escrow_service.milestone_accepted(s, {"milestoneId": m2["id"]})
    assert await states(sf, c["id"]) == {1: "HELD", 2: "HELD"}  # not paid out at acceptance
    async with sf() as s:
        due = (await s.execute(text("SELECT key FROM platform.timers WHERE kind = :k ORDER BY key"),
                               {"k": escrow_service.TIMER_RELEASE_AFTER_WINDOW})).scalars().all()
    assert sorted(due) == sorted([m1["id"], m2["id"]])

    # Inside the window the buyer may dispute accepted work for what it is, not only about the payment.
    r = await client.post(D, headers=buyer.idem(), json=dispute_body(c, milestones=[m1["id"]]))
    assert r.status_code in (200, 201), r.text
    await drain()
    assert (await states(sf, c["id"]))[1] == "ON_HOLD"

    # The window ends: M2 is paid; M1 stays with its dispute.
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE contract.milestones SET accepted_at = now() - interval '8 days' WHERE id IN (:a, :b)"),
                        {"a": m1["id"], "b": m2["id"]})
        await escrow_service.milestone_accepted(s, {"milestoneId": m2["id"]})
        await escrow_service.milestone_accepted(s, {"milestoneId": m1["id"]})
    assert await states(sf, c["id"]) == {1: "ON_HOLD", 2: "RELEASED"}
    await balanced(sf)
    # After the window, accepted work can no longer be disputed for its quality.
    late = await client.post(D, headers=buyer.idem(), json=dispute_body(c, milestones=[m2["id"]]))
    assert late.status_code == 409
