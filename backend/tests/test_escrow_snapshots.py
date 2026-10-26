"""Escrow ledger snapshots (escrow/snapshots.py): balances from the latest snapshot plus later lines, and the integrity
checks (chain, group balance, held amount) that page Financial Operations on a mismatch."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from zoikorum.shared import clock


async def _account(sf, held: int):
    from zoikorum.domains.escrow.models import EscrowAccount

    async with sf() as s, s.begin():
        a = EscrowAccount(contract_id=uuid.uuid4(), organization_id=uuid.uuid4(), professional_id=uuid.uuid4(), currency="USD",
                          total_minor=100_000, status="FUNDED", funded_minor=held, held_minor=held)
        s.add(a)
        await s.flush()
        return a.id


async def _lines(sf, account_id, lines, at=None):
    from zoikorum.domains.escrow.models import LedgerEntry

    group = uuid.uuid4()
    async with sf() as s, s.begin():
        for entry_type, account, d, c in lines:
            s.add(LedgerEntry(entry_group_id=group, account_id=account_id, entry_type=entry_type, ledger_account=account,
                              debit_minor=d, credit_minor=c, currency="USD", reference_type="FUNDING", reference_id=uuid.uuid4(),
                              memo="test", **({"created_at": at} if at else {})))
    return group


FUND = [("BUYER_FUNDING", "BUYER_CLEARING", 50_000, 0), ("ESCROW_HOLD", "ESCROW_HELD", 0, 50_000)]


async def test_snapshot_balances_and_checks(sf, client):
    from zoikorum.domains.escrow import snapshots

    start = datetime.now(timezone.utc)
    account_id = await _account(sf, held=50_000)
    await _lines(sf, account_id, FUND, at=start - timedelta(hours=1))
    clock.set_now(start)
    async with sf() as s, s.begin():
        snap = await snapshots.take(s, account_id)
    assert snap.status == "OK" and snap.balances == {"BUYER_CLEARING": -50_000, "ESCROW_HELD": 50_000} and snap.entry_count == 2

    # Later lines are added on top of the snapshot for reads.
    await _lines(sf, account_id, [("REFUND", "ESCROW_HELD", 10_000, 0), ("REFUND", "BUYER_REFUND_PAYABLE", 0, 10_000)])
    async with sf() as s:
        now = await snapshots.balances(s, account_id)
    assert now["balances"]["ESCROW_HELD"] == 40_000 and now["linesAfterSnapshot"] == 2 and now["fromSnapshot"] == snap.id

    # The account says 50 000 held but the ledger 40 000: HELD mismatch.
    clock.set_now(start + timedelta(minutes=30))
    async with sf() as s, s.begin():
        second = await snapshots.take(s, account_id)
    assert second.status == "MISMATCH" and [p["check"] for p in second.problems] == ["HELD"]

    # A ledger line removed behind the append-only rule breaks the chain; an unbalanced group is reported too.
    async with sf() as s, s.begin():
        await s.execute(text("SET LOCAL session_replication_role = replica"))
        await s.execute(text("DELETE FROM escrow.ledger_entries WHERE account_id = :a AND ledger_account = 'BUYER_CLEARING'"),
                        {"a": account_id})
    clock.set_now(start + timedelta(hours=1))
    async with sf() as s, s.begin():
        third = await snapshots.take(s, account_id)
    assert {"CHAIN", "GROUP_BALANCE"} <= {p["check"] for p in third.problems}

    async with sf() as s:
        gauges = dict((n, v) for n, _, v in await snapshots._gauges(s))
    assert gauges["zk_escrow_snapshot_mismatches"] == 1


async def test_take_all_and_staff_endpoints(sf, client, make_user):
    from zoikorum.domains.escrow import snapshots

    account_id = await _account(sf, held=50_000)
    await _lines(sf, account_id, FUND, at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert await snapshots.take_all(sf) == {"OK": 1, "MISMATCH": 0}
    staff = await make_user("finops", platform_roles=("FINANCIAL_OPS",))
    await staff.enable_mfa()
    await staff.step_up()
    r = await client.get(f"/v1/admin/escrow/{account_id}/ledger-snapshot", headers=staff.h)
    assert r.status_code == 200, r.text
    assert r.json()["latest"]["status"] == "OK" and r.json()["balances"]["ESCROW_HELD"] == 50_000
    assert (await client.post(f"/v1/admin/escrow/{account_id}/ledger-snapshot", headers=staff.h)).json()["status"] == "OK"
    buyer = await make_user("nosy-buyer")
    assert (await client.get(f"/v1/admin/escrow/{account_id}/ledger-snapshot", headers=buyer.h)).status_code == 403
