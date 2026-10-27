"""Escrow ledger snapshots: periodic per-account balances for fast reads, and an integrity check of the ledger.

Daily at 03:30 UTC (and on demand by Financial Operations) every escrow account gets a snapshot: the balance of each
ledger account (credits minus debits) through a cut-off five minutes in the past, so a transaction still open at the
cut-off can never be missed. ``balances`` reads the latest snapshot and adds only the ledger lines after it.

Each snapshot is also a check, recorded with it (status OK or MISMATCH):
* chain: the previous snapshot plus the lines added since equals a full recount of the ledger (an append-only line that
  was changed or removed shows up here);
* every entry group (one money movement) still balances: debits equal credits;
* the money the ledger says is held in escrow (ESCROW_HELD) equals the account's own held figure, read with the account
  locked against changes.
A mismatch is logged, written to the audit trail and exported as ``zk_escrow_snapshot_mismatches`` (alerts.yml pages
Financial Operations). Snapshots never change the ledger or the account.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.escrow.models import EscrowAccount, LedgerEntry, LedgerSnapshot
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.errors import NotFound
from zoikorum.shared.events import record_audit
from zoikorum.shared.metrics import gauge_source
from zoikorum.shared.relay import on_timer, schedule_timer

log = logging.getLogger("zoikorum.escrow.snapshots")
TIMER = "escrow.ledger_snapshots"
SAFETY = timedelta(minutes=5)  # lines newer than this may belong to a transaction that has not committed yet
BATCH = 500


def next_run(now: datetime) -> datetime:
    """Daily at 03:30 UTC (after the 01:00 reconciliation and the 02:30 housekeeping)."""
    today = datetime.combine(now.date(), time(3, 30), tzinfo=timezone.utc)
    return today if now < today else today + timedelta(days=1)


async def bootstrap(session: AsyncSession) -> None:
    nxt = next_run(clock.now())
    await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)


async def _latest(session: AsyncSession, account_id: uuid.UUID) -> LedgerSnapshot | None:
    return await session.scalar(select(LedgerSnapshot).where(LedgerSnapshot.account_id == account_id)
                                .order_by(LedgerSnapshot.created_at.desc(), LedgerSnapshot.id.desc()).limit(1))


async def _sums(session: AsyncSession, account_id: uuid.UUID, after: datetime | None, through: datetime | None) -> tuple[dict, int]:
    """{ledger account: credits - debits} and the number of lines, for lines in (after, through]."""
    stmt = select(LedgerEntry.ledger_account, func.sum(LedgerEntry.credit_minor - LedgerEntry.debit_minor), func.count()) \
        .where(LedgerEntry.account_id == account_id).group_by(LedgerEntry.ledger_account)
    if after is not None:
        stmt = stmt.where(LedgerEntry.created_at > after)
    if through is not None:
        stmt = stmt.where(LedgerEntry.created_at <= through)
    rows = (await session.execute(stmt)).all()
    return {acct: int(total or 0) for acct, total, _ in rows}, sum(n for _, _, n in rows)


def _add(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return {k: v for k, v in out.items() if v != 0 or k in a or k in b}


def _same(a: dict, b: dict) -> bool:
    keys = set(a) | set(b)
    return all(a.get(k, 0) == b.get(k, 0) for k in keys)


async def balances(session: AsyncSession, account_id: uuid.UUID) -> dict:
    """Balance of every ledger account of this escrow now: latest snapshot plus the lines after it."""
    snap = await _latest(session, account_id)
    after = snap.through_created_at if snap else None
    delta, count = await _sums(session, account_id, after, None)
    return {"balances": _add(snap.balances if snap else {}, delta), "fromSnapshot": snap.id if snap else None,
            "linesAfterSnapshot": count}


async def take(session: AsyncSession, account_id: uuid.UUID) -> LedgerSnapshot:
    """One snapshot with its integrity checks (see the module notes)."""
    a = await session.get(EscrowAccount, account_id, with_for_update={"read": True})  # writers wait; readers do not
    if a is None:
        raise NotFound("Escrow account not found")
    cutoff = clock.now() - SAFETY
    prev = await _latest(session, account_id)
    problems: list[dict] = []
    full, count = await _sums(session, account_id, None, cutoff)
    if prev is not None and prev.through_created_at is not None and prev.through_created_at <= cutoff:
        delta, _ = await _sums(session, account_id, prev.through_created_at, cutoff)
        if not _same(_add(prev.balances, delta), full):
            problems.append({"check": "CHAIN", "previousSnapshot": str(prev.id), "expected": _add(prev.balances, delta), "ledger": full})
    unbalanced = (await session.execute(
        select(LedgerEntry.entry_group_id, func.sum(LedgerEntry.debit_minor), func.sum(LedgerEntry.credit_minor))
        .where(LedgerEntry.account_id == account_id).group_by(LedgerEntry.entry_group_id)
        .having(func.sum(LedgerEntry.debit_minor) != func.sum(LedgerEntry.credit_minor)).limit(20))).all()
    for group, debit, credit in unbalanced:
        problems.append({"check": "GROUP_BALANCE", "entryGroupId": str(group), "debit": int(debit), "credit": int(credit)})
    now_totals, _ = await _sums(session, account_id, None, None)  # everything committed, with the account locked
    held = now_totals.get("ESCROW_HELD", 0)
    if held != a.held_minor:
        problems.append({"check": "HELD", "ledger": held, "account": a.held_minor})
    snap = LedgerSnapshot(account_id=a.id, currency=a.currency, through_created_at=cutoff, entry_count=count, balances=full,
                          status="MISMATCH" if problems else "OK", problems=problems)
    session.add(snap)
    await session.flush()
    if problems:
        log.error("escrow ledger snapshot mismatch", extra={"fields": {"escrowAccountId": str(a.id), "checks": [p["check"] for p in problems]}})
        record_audit(session, "escrow.ledger_snapshot.mismatch", object_type="EscrowAccount", object_id=a.id,
                     tenant_id=a.organization_id, details={"snapshotId": str(snap.id), "problems": problems})
    return snap


async def take_all(session_factory) -> dict[str, int]:
    """A snapshot of every escrow account, each in its own short transaction."""
    done = {"OK": 0, "MISMATCH": 0}
    last: uuid.UUID | None = None
    while True:
        async with session_factory() as s:
            stmt = select(EscrowAccount.id).order_by(EscrowAccount.id).limit(BATCH)
            if last is not None:
                stmt = stmt.where(EscrowAccount.id > last)
            ids = list((await s.scalars(stmt)).all())
        if not ids:
            return done
        for account_id in ids:
            async with session_factory() as s, s.begin():
                done[(await take(s, account_id)).status] += 1
        last = ids[-1]


def snapshot_out(s: LedgerSnapshot) -> dict:
    return {"id": s.id, "accountId": s.account_id, "currency": s.currency, "throughCreatedAt": s.through_created_at,
            "entryCount": s.entry_count, "balances": s.balances, "status": s.status, "problems": s.problems, "takenAt": s.created_at}


async def check_now(session: AsyncSession, actor: Actor, account_id: uuid.UUID) -> dict:
    """Financial Operations: take a snapshot of one escrow now and show its checks."""
    actor.require_capability(Cap.PAYMENTS_READ)  # read-only: a snapshot never moves money
    return snapshot_out(await take(session, account_id))


async def latest_for(session: AsyncSession, actor: Actor, account_id: uuid.UUID) -> dict:
    actor.require_capability(Cap.PAYMENTS_READ)  # read-only: a snapshot never moves money
    snap = await _latest(session, account_id)
    return {"latest": snapshot_out(snap) if snap else None, **await balances(session, account_id)}


@on_timer(TIMER)
async def _daily(session: AsyncSession, key: str, payload: dict) -> None:
    from zoikorum.shared.db import session_factory

    result = await take_all(session_factory())
    log.info("escrow ledger snapshots taken", extra={"fields": result})
    nxt = next_run(clock.now())
    await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)  # re-arms itself


@gauge_source
async def _gauges(session: AsyncSession) -> list[tuple[str, str, float]]:
    """Accounts whose latest snapshot found a problem, and the age of the newest snapshot."""
    latest = select(LedgerSnapshot.account_id, func.max(LedgerSnapshot.created_at).label("at")).group_by(LedgerSnapshot.account_id).subquery()
    mismatches = await session.scalar(select(func.count()).select_from(LedgerSnapshot).join(
        latest, (LedgerSnapshot.account_id == latest.c.account_id) & (LedgerSnapshot.created_at == latest.c.at))
        .where(LedgerSnapshot.status == "MISMATCH")) or 0
    newest = await session.scalar(select(func.max(LedgerSnapshot.created_at)))
    accounts = await session.scalar(select(func.count()).select_from(EscrowAccount)) or 0
    age_hours = (clock.now() - newest).total_seconds() / 3600 if newest else (0.0 if accounts == 0 else 1e6)
    return [("zk_escrow_snapshot_mismatches", "Escrow accounts whose latest ledger snapshot failed an integrity check", float(mismatches)),
            ("zk_escrow_snapshot_age_hours", "Hours since the newest escrow ledger snapshot", round(age_hours, 2))]
