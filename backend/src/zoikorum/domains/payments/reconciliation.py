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
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.escrow import facade as escrow_facade
from zoikorum.domains.payments.models import PaymentIntent, Payout, ReconciliationBatch, Refund
from zoikorum.domains.payments.providers import get_provider
from zoikorum.domains.payments.schemas import ReconciliationOut
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.relay import schedule_timer

TIMER = "payments.daily_reconciliation"
VIEWERS = (PlatformRole.FINANCIAL_OPS, PlatformRole.PLATFORM_ADMIN)


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
    payload = {"batchId": batch.id, "day": day.isoformat(), "status": status, "mismatches": mismatches}
    record_event(session, E.RECONCILIATION_MISMATCH if mismatches else E.RECONCILIATION_COMPLETED,
                 aggregate_type="ReconciliationBatch", aggregate_id=batch.id, payload=payload)
    if mismatches:
        record_audit(session, "payments.reconciliation.mismatch", object_type="ReconciliationBatch", object_id=batch.id,
                     details={"day": day.isoformat(), "checks": [c for c in checks if not c["ok"]]})
    return batch


def _out(b: ReconciliationBatch) -> ReconciliationOut:
    return ReconciliationOut(id=b.id, day=b.day, status=b.status, mismatches=b.mismatches, checks=b.checks, runBy=b.run_by,
                             updatedAt=b.updated_at or b.created_at)


async def list_batches(session: AsyncSession, actor: Actor) -> list[ReconciliationOut]:
    actor.require_platform_role(*VIEWERS)
    rows = (await session.scalars(select(ReconciliationBatch).order_by(ReconciliationBatch.day.desc()).limit(90))).all()
    return [_out(b) for b in rows]


async def run(session: AsyncSession, actor: Actor, day: date) -> ReconciliationOut:
    actor.require_platform_role(*VIEWERS)
    batch = await reconcile(session, day, run_by=str(actor.identity_id))
    return _out(batch)


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
