"""Reconciliation suspense (PAY-02): differences found by a run become breaks that move OPEN -> EVIDENCE_GATHERING ->
REVIEWED -> CLOSED with maker-checker and step-up on close; a day is never reported clean while a break is unresolved."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from test_dispute import staff
from test_payments_ops import funded
from zoikorum.domains.payments.reconciliation import run_status
from zoikorum.shared import clock

R = "/v1/payments/reconciliations"
B = "/v1/payments/reconciliation-breaks"


def test_a_day_is_clean_only_without_unresolved_breaks():
    assert run_status("MATCHED", 0, 0) == "CLEAN"
    assert run_status("MATCHED", 1, 1) == "BREAKS_OPEN"  # books agree again, but the break is not explained yet
    assert run_status("MISMATCH", 2, 0) == "BREAKS_RESOLVED"
    assert run_status("MISMATCH", 0, 0) == "BREAKS_OPEN"


async def audits(sf, action: str) -> int:
    async with sf() as s:
        return await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action = :a"), {"a": action})


async def test_breaks_are_idempotent_and_close_only_with_maker_checker_and_step_up(client, make_user, drain, sf):
    pro_user, buyer, c = await funded(client, make_user, drain, both=True)
    m1 = c["milestones"][0]["id"]
    await client.post(f"/v1/milestones/{m1}/submit", headers=pro_user.h, json={"note": "Delivered"})
    await client.post(f"/v1/milestones/{m1}/accept", headers=buyer.idem())
    await drain()
    maker = await staff(make_user, "maker", "FINANCIAL_OPS")
    checker = await staff(make_user, "checker", "PLATFORM_ADMIN")
    today = clock.now().date().isoformat()

    clean = (await client.post(R, headers=maker.h, json={"day": today})).json()
    assert clean["status"] == "MATCHED" and clean["runStatus"] == "CLEAN" and clean["breaks"] == 0

    async with sf() as s, s.begin():  # a payout record goes missing from the payments side
        await s.execute(text("DELETE FROM payments.payouts"))
    for _ in range(2):  # re-running the day does not duplicate its break
        r = (await client.post(R, headers=maker.h, json={"day": today})).json()
        assert r["status"] == "MISMATCH" and r["runStatus"] == "BREAKS_OPEN" and r["breaks"] == 1 and r["openBreaks"] == 1
    assert (await client.get(B, headers=buyer.h)).status_code == 403
    (brk,) = (await client.get(B, headers=maker.h, params={"status": "OPEN"})).json()
    assert brk["kind"] == "payouts" and brk["amountMinor"] == 900_000 and brk["owner"] is None
    assert brk["references"]["batchId"] == r["id"] and brk["references"]["payments"] == 0
    await drain()
    assert await audits(sf, "payments.reconciliation_break.opened") == 1
    url = f"{B}/{brk['id']}/advance"

    assert (await client.post(url, headers=maker.h, json={"status": "REVIEWED", "note": "Skipping ahead"})).json()["code"] == "INVALID_STEP"
    got = (await client.post(url, headers=maker.h, json={"status": "EVIDENCE_GATHERING", "note": "Pulling provider payout file"})).json()
    assert got["status"] == "EVIDENCE_GATHERING" and got["owner"] and got["ownerId"]
    got = (await client.post(url, headers=maker.h, json={"status": "REVIEWED", "note": "Payout row deleted by a bad script"})).json()
    assert got["status"] == "REVIEWED" and got["reviewedAt"]
    blocked = await client.post(url, headers=maker.h, json={"status": "CLOSED", "note": "Restored from backup"})
    assert blocked.status_code == 409 and blocked.json()["code"] == "MAKER_CHECKER_REQUIRED"
    listed = (await client.get(R, headers=maker.h)).json()
    assert listed[0]["runStatus"] == "BREAKS_OPEN"  # reviewed is not resolved

    clock.advance(timedelta(seconds=400))  # the checker's step-up has expired
    try:
        stale = await client.post(url, headers=checker.h, json={"status": "CLOSED", "note": "Restored from backup"})
        assert stale.status_code == 401 and stale.json()["code"] == "STEP_UP_REQUIRED"
    finally:
        clock.set_now(None)
    closed = (await client.post(url, headers=checker.h, json={"status": "CLOSED", "note": "Restored from backup; ledger agrees"})).json()
    assert closed["status"] == "CLOSED" and closed["closedAt"] and closed["resolutionNote"] == "Restored from backup; ledger agrees"
    assert [h["toStatus"] for h in closed["history"]] == ["OPEN", "EVIDENCE_GATHERING", "REVIEWED", "CLOSED"]
    assert (await client.post(url, headers=checker.h, json={"status": "CLOSED", "note": "Again please"})).json()["code"] == "BREAK_CLOSED"
    await drain()
    assert await audits(sf, "payments.reconciliation_break.advanced") == 3

    listed = (await client.get(R, headers=maker.h)).json()
    assert listed[0]["runStatus"] == "BREAKS_RESOLVED" and listed[0]["openBreaks"] == 0
    # The same difference on a re-run stays explained; no new break appears.
    r = (await client.post(R, headers=maker.h, json={"day": today})).json()
    assert r["runStatus"] == "BREAKS_RESOLVED" and r["breaks"] == 1
    assert (await client.get(B, headers=maker.h, params={"status": "OPEN"})).json() == []


async def test_a_closed_break_reopens_when_the_difference_changes(client, make_user, drain, sf):
    pro_user, buyer, c = await funded(client, make_user, drain, both=True)
    for m in c["milestones"][:1]:
        await client.post(f"/v1/milestones/{m['id']}/submit", headers=pro_user.h, json={"note": "Delivered"})
        await client.post(f"/v1/milestones/{m['id']}/accept", headers=buyer.idem())
    await drain()
    a = await staff(make_user, "fa", "FINANCIAL_OPS")
    b = await staff(make_user, "fb", "FINANCIAL_OPS")
    today = clock.now().date().isoformat()
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE payments.payouts SET amount_minor = amount_minor - 100"))
    await client.post(R, headers=a.h, json={"day": today})
    (brk,) = (await client.get(B, headers=a.h)).json()
    url = f"{B}/{brk['id']}/advance"
    for who, step in ((a, "EVIDENCE_GATHERING"), (a, "REVIEWED"), (b, "CLOSED")):
        assert (await client.post(url, headers=who.h, json={"status": step, "note": "Rounding on the payout"})).status_code == 200
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE payments.payouts SET amount_minor = amount_minor - 50"))
    r = (await client.post(R, headers=a.h, json={"day": today})).json()
    assert r["runStatus"] == "BREAKS_OPEN" and r["breaks"] == 1
    (again,) = (await client.get(B, headers=a.h)).json()
    assert again["id"] == brk["id"] and again["status"] == "OPEN" and again["amountMinor"] == 150 and again["closedAt"] is None
