"""Daily reconciliation (Engineering Handbook 15.4; Homepage "Payment Records and Reconciliation").

For one UTC day, per currency, three independent records must agree:
  * the escrow ledger (double-entry, written by the escrow domain),
  * the payments records (charges, payouts, refunds, chargebacks written by this domain),
  * the provider's own settlement report, when the provider offers one (the test provider does not).

Checks (ledger account -> payments record):
  charges     BUYER_CLEARING debits         = captured charges
  payouts     PRO_PAYABLE credits           = payouts created (net amounts owed to professionals)
  refunds     BUYER_REFUND_PAYABLE credits  = refunds created
  chargebacks CHARGEBACK_REVERSAL credits   = chargebacks received
Any difference makes the batch MISMATCH, a P0 financial incident (RECONCILIATION_MISMATCH + audit).
The scheduled run happens at 01:00 UTC for the previous day; Financial Ops can re-run any day.

Suspense (PAY-02): every difference becomes a break (one per day, check and currency; a re-run updates it rather than
adding another). A break moves OPEN -> EVIDENCE_GATHERING -> REVIEWED -> CLOSED; closing needs a fresh step-up and a
different person from the reviewer (maker-checker). A day reports CLEAN only when none of its breaks is unresolved:
runStatus is CLEAN, BREAKS_OPEN or BREAKS_RESOLVED.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.escrow import facade as escrow_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.payments.models import PaymentIntent, Payout, ReconciliationBatch, ReconciliationBreak, Refund
from zoikorum.domains.payments.providers import get_provider
from zoikorum.domains.payments.schemas import BreakAdvanceIn, ReconciliationBreakOut, ReconciliationOut
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.errors import Conflict, NotFound
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.relay import schedule_timer

TIMER = "payments.daily_reconciliation"
BREAK_STEPS = ("OPEN", "EVIDENCE_GATHERING", "REVIEWED", "CLOSED")


def _window(day: date) -> tuple[datetime, datetime]:
    since = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return since, since + timedelta(days=1)


async def _sum(session: AsyncSession, amount, ts, since: datetime, until: datetime, *where) -> dict[str, int]:
    model = amount.class_
    rows = (await session.execute(select(model.currency, func.sum(amount)).where(ts >= since, ts < until, *where)
                                  .group_by(model.currency))).all()
    return {ccy: int(v or 0) for ccy, v in rows}


async def reconcile(session: AsyncSession, day: date, run_by: str = "SCHEDULE") -> ReconciliationBatch:
    since, until = _window(day)
    moves = await escrow_facade.ledger_movements(session, since, until)

    def ledger(account: str, side: int) -> dict[str, int]:
        return {ccy: amounts[side] for (acct, ccy), amounts in moves.items() if acct == account and amounts[side]}

    payments = {
        "charges": await _sum(session, PaymentIntent.amount_minor, PaymentIntent.captured_at, since, until,
                              PaymentIntent.status.in_(("CAPTURED", "CHARGED_BACK"))),
        "payouts": await _sum(session, Payout.amount_minor, Payout.created_at, since, until),
        "refunds": await _sum(session, Refund.amount_minor, Refund.created_at, since, until),
        "chargebacks": await _sum(session, PaymentIntent.chargeback_minor, PaymentIntent.charged_back_at, since, until),
    }
    ledgers = {"charges": ledger("BUYER_CLEARING", 0), "payouts": ledger("PRO_PAYABLE", 1),
               "refunds": ledger("BUYER_REFUND_PAYABLE", 1), "chargebacks": ledger("CHARGEBACK_REVERSAL", 1)}
    report = get_provider().report(since, until)
    provider = {"charges": report.charges, "payouts": report.payouts, "refunds": report.refunds} if report else {}
    payments_settled: dict[str, dict[str, int]] = {}
    if report:  # the provider reports what actually settled
        payments_settled = {
            "charges": payments["charges"],
            "payouts": await _sum(session, Payout.amount_minor, Payout.settled_at, since, until, Payout.status == "SETTLED"),
            "refunds": await _sum(session, Refund.amount_minor, Refund.settled_at, since, until, Refund.status == "SETTLED"),
        }

    checks = []
    for name in ("charges", "payouts", "refunds", "chargebacks"):
        for ccy in sorted(set(ledgers[name]) | set(payments[name]) | set(provider.get(name, {}))):
            led, pay = ledgers[name].get(ccy, 0), payments[name].get(ccy, 0)
            prov = provider[name].get(ccy, 0) if name in provider else None
            diff = led - pay
            ok = diff == 0 and (prov is None or prov == payments_settled[name].get(ccy, 0))
            checks.append({"name": name, "currency": ccy, "ledger": led, "payments": pay, "provider": prov,
                           "difference": diff if diff else (0 if prov is None else prov - payments_settled[name].get(ccy, 0)), "ok": ok})
    mismatches = sum(1 for c in checks if not c["ok"])
    status = "MISMATCH" if mismatches else "MATCHED"

    batch = await session.scalar(select(ReconciliationBatch).where(ReconciliationBatch.day == day).with_for_update())
    if batch is None:
        batch = ReconciliationBatch(day=day, status=status, checks=checks, mismatches=mismatches, run_by=run_by)
        session.add(batch)
    else:
        batch.status, batch.checks, batch.mismatches, batch.run_by = status, checks, mismatches, run_by
    await session.flush()
    await _sync_breaks(session, batch, checks, run_by)
    payload = {"batchId": batch.id, "day": day.isoformat(), "status": status, "mismatches": mismatches}
    record_event(session, E.RECONCILIATION_MISMATCH if mismatches else E.RECONCILIATION_COMPLETED,
                 aggregate_type="ReconciliationBatch", aggregate_id=batch.id, payload=payload)
    if mismatches:
        record_audit(session, "payments.reconciliation.mismatch", object_type="ReconciliationBatch", object_id=batch.id,
                     details={"day": day.isoformat(), "checks": [c for c in checks if not c["ok"]]})
    return batch


async def _sync_breaks(session: AsyncSession, batch: ReconciliationBatch, checks: list[dict], run_by: str) -> None:
    """One break per day + check + currency that differs. A re-run updates an existing break (never a duplicate); a
    closed break whose difference changed reopens, because what was explained is no longer what the books show."""
    existing = {(b.kind, b.currency): b for b in (await session.scalars(
        select(ReconciliationBreak).where(ReconciliationBreak.day == batch.day).with_for_update())).all()}
    now = clock.now().isoformat()
    for c in checks:
        if c["ok"]:
            continue
        refs = {"batchId": str(batch.id), "ledger": c["ledger"], "payments": c["payments"], "provider": c["provider"]}
        b = existing.get((c["name"], c["currency"]))
        if b is None:
            b = ReconciliationBreak(batch_id=batch.id, day=batch.day, kind=c["name"], currency=c["currency"],
                                    amount_minor=c["difference"], references=refs, status="OPEN",
                                    history=[{"at": now, "by": run_by, "fromStatus": None, "toStatus": "OPEN",
                                              "note": "Found by the reconciliation run"}])
            session.add(b)
            await session.flush()
            record_audit(session, "payments.reconciliation_break.opened", object_type="ReconciliationBreak", object_id=b.id,
                         details={"day": batch.day.isoformat(), "kind": b.kind, "currency": b.currency,
                                  "amountMinor": b.amount_minor})
            continue
        same = {k: v for k, v in b.references.items() if k != "batchId"} == {k: v for k, v in refs.items() if k != "batchId"}
        if b.amount_minor == c["difference"] and same:
            continue
        entry = {"at": now, "by": run_by, "fromStatus": b.status, "toStatus": b.status,
                 "note": f"Re-run: difference {b.amount_minor} -> {c['difference']}"}
        if b.status == "CLOSED":
            entry["toStatus"], b.status = "OPEN", "OPEN"
            b.reviewed_by = b.reviewed_at = b.closed_by = b.closed_at = None
        b.batch_id, b.amount_minor, b.references, b.history = batch.id, c["difference"], refs, [*b.history, entry]
        record_audit(session, "payments.reconciliation_break.updated", object_type="ReconciliationBreak", object_id=b.id,
                     details={"day": batch.day.isoformat(), "kind": b.kind, "currency": b.currency,
                              "amountMinor": b.amount_minor, "status": b.status})


async def _break_counts(session: AsyncSession, days: list[date]) -> dict[date, tuple[int, int]]:
    """day -> (breaks, unresolved breaks)."""
    if not days:
        return {}
    rows = (await session.execute(select(ReconciliationBreak.day, func.count(),
                                         func.count().filter(ReconciliationBreak.status != "CLOSED"))
                                  .where(ReconciliationBreak.day.in_(days)).group_by(ReconciliationBreak.day))).all()
    return {d: (int(total), int(open_)) for d, total, open_ in rows}


def run_status(batch_status: str, breaks: int, open_breaks: int) -> str:
    """Never CLEAN while a break for the day is unresolved (or, defensively, while the run mismatched with no break)."""
    if open_breaks or (batch_status == "MISMATCH" and not breaks):
        return "BREAKS_OPEN"
    return "BREAKS_RESOLVED" if breaks else "CLEAN"


def _out(b: ReconciliationBatch, counts: tuple[int, int] = (0, 0)) -> ReconciliationOut:
    total, open_ = counts
    return ReconciliationOut(id=b.id, day=b.day, status=b.status, mismatches=b.mismatches, checks=b.checks, runBy=b.run_by,
                             updatedAt=b.updated_at or b.created_at, runStatus=run_status(b.status, total, open_),
                             breaks=total, openBreaks=open_)


async def list_batches(session: AsyncSession, actor: Actor) -> list[ReconciliationOut]:
    actor.require_capability(Cap.RECON_READ)
    rows = (await session.scalars(select(ReconciliationBatch).order_by(ReconciliationBatch.day.desc()).limit(90))).all()
    counts = await _break_counts(session, [b.day for b in rows])
    return [_out(b, counts.get(b.day, (0, 0))) for b in rows]


async def run(session: AsyncSession, actor: Actor, day: date) -> ReconciliationOut:
    actor.require_capability(Cap.RECON_OPERATE)
    batch = await reconcile(session, day, run_by=str(actor.identity_id))
    return _out(batch, (await _break_counts(session, [day])).get(day, (0, 0)))


# ---- Suspense: reconciliation breaks ----------------------------------------------------------------------------

async def _break_outs(session: AsyncSession, rows: list[ReconciliationBreak]) -> list[ReconciliationBreakOut]:
    people = await identity_facade.get_identities(session, list({b.owner_id for b in rows if b.owner_id}))
    return [ReconciliationBreakOut(
        id=b.id, batchId=b.batch_id, day=b.day, kind=b.kind, currency=b.currency, amountMinor=b.amount_minor,
        references=b.references, status=b.status, ownerId=b.owner_id,
        owner=people[b.owner_id].display_name if b.owner_id in people else None, resolutionNote=b.resolution_note,
        reviewedBy=b.reviewed_by, reviewedAt=b.reviewed_at, closedBy=b.closed_by, closedAt=b.closed_at, history=b.history,
        createdAt=b.created_at, updatedAt=b.updated_at or b.created_at) for b in rows]


async def list_breaks(session: AsyncSession, actor: Actor, status: str | None = None) -> list[ReconciliationBreakOut]:
    actor.require_capability(Cap.RECON_READ)
    stmt = select(ReconciliationBreak).order_by(ReconciliationBreak.day.desc(), ReconciliationBreak.kind,
                                                ReconciliationBreak.currency).limit(500)
    if status:
        stmt = stmt.where(ReconciliationBreak.status == status)
    return await _break_outs(session, list((await session.scalars(stmt)).all()))


async def advance_break(session: AsyncSession, actor: Actor, break_id: uuid.UUID, body: BreakAdvanceIn) -> ReconciliationBreakOut:
    """Move a break one step on. The first person to move it owns it; closing needs a fresh step-up, a resolution note,
    and someone other than the person who marked it REVIEWED (maker-checker). Audited."""
    actor.require_capability(Cap.RECON_OPERATE)
    if body.status == "CLOSED":
        actor.require_step_up()
    b = await session.get(ReconciliationBreak, break_id, with_for_update=True)
    if b is None:
        raise NotFound("Reconciliation break not found")
    if b.status == "CLOSED":
        raise Conflict("This break is closed", code="BREAK_CLOSED")
    expected = BREAK_STEPS[BREAK_STEPS.index(b.status) + 1]
    if body.status != expected:
        raise Conflict(f"A break moves {b.status.lower()} -> {expected.lower()}", code="INVALID_STEP")
    if body.status == "CLOSED" and b.reviewed_by == actor.identity_id:
        raise Conflict("The person who reviewed this break cannot also close it", code="MAKER_CHECKER_REQUIRED")
    now, note, previous = clock.now(), body.note.strip(), b.status
    if b.owner_id is None:
        b.owner_id = actor.identity_id
    if body.status == "REVIEWED":
        b.reviewed_by, b.reviewed_at = actor.identity_id, now
    if body.status == "CLOSED":
        b.closed_by, b.closed_at, b.resolution_note = actor.identity_id, now, note
    b.status = body.status
    b.history = [*b.history, {"at": now.isoformat(), "by": str(actor.identity_id), "fromStatus": previous,
                              "toStatus": body.status, "note": note}]
    record_audit(session, "payments.reconciliation_break.advanced", object_type="ReconciliationBreak", object_id=b.id,
                 details={"day": b.day.isoformat(), "kind": b.kind, "currency": b.currency, "from": previous,
                          "to": body.status, "note": note})
    await session.flush()
    return (await _break_outs(session, [b]))[0]


def next_run(after: datetime) -> datetime:
    """01:00 UTC on the day after ``after``'s date, or today if it is still before 01:00."""
    today_one = datetime.combine(after.date(), time(1, 0), tzinfo=timezone.utc)
    return today_one if after < today_one else today_one + timedelta(days=1)


async def scheduled(session: AsyncSession) -> None:
    """Timer handler: reconcile yesterday, then re-arm for tomorrow."""
    now = clock.now()
    await reconcile(session, (now - timedelta(days=1)).date())
    nxt = next_run(now)
    await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)


async def bootstrap(session: AsyncSession) -> None:
    nxt = next_run(clock.now())
    await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)


async def health(session: AsyncSession) -> list[tuple[str, str, float]]:
    """Metrics (shared/metrics.py): the payments SLO is zero unresolved mismatches, and the daily run must happen."""
    latest = await session.scalar(select(ReconciliationBatch).order_by(ReconciliationBatch.day.desc()).limit(1))
    if latest is None:
        return []
    unresolved = await session.scalar(select(func.count()).select_from(ReconciliationBreak)
                                      .where(ReconciliationBreak.status != "CLOSED")) or 0
    return [("zk_reconciliation_open_breaks", "Reconciliation breaks not yet closed, any day (must reach 0)", unresolved),
            ("zk_reconciliation_latest_mismatches", "Mismatches in the latest reconciled day (must be 0)", latest.mismatches),
            ("zk_reconciliation_latest_age_days", "Days since the latest reconciled day (2 or more: the daily run is not "
             "happening)", (clock.now().date() - latest.day).days)]
