"""Scheduled dispute reports for buyer organisations (Dispute resolution: reporting for enterprise admins).

An Organisation Admin opts in to a weekly or monthly report. A durable timer fires at the start of each period
(Monday / the 1st, 06:00 UTC); the admin is notified with the period's figures and a link to the CSV of the cases.
The CSV is built from the live records when it is downloaded, so it never goes stale or leaks after access ends:
downloading it needs the Organisation Admin or Legal Reviewer role at that moment.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.dispute.models import DisputeCase, ReportSubscription
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, OrgRole
from zoikorum.shared.errors import Forbidden, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.relay import cancel_timer, schedule_timer

TIMER_REPORT = "dispute.scheduled_report"
EXPORT_PATH = "/v1/disputes/reports/export"


def next_run(frequency: str, after: datetime) -> datetime:
    """The next period start strictly after ``after``: Monday 06:00 UTC (weekly) or the 1st at 06:00 UTC (monthly)."""
    day = after.astimezone(timezone.utc).date()
    if frequency == "WEEKLY":
        candidate = day + timedelta(days=(7 - day.weekday()) % 7)
    else:
        candidate = day.replace(day=1)
    while True:
        at = datetime.combine(candidate, time(6), tzinfo=timezone.utc)
        if at > after:
            return at
        candidate = candidate + timedelta(days=7) if frequency == "WEEKLY" else (candidate.replace(day=28) + timedelta(days=4)).replace(day=1)


def period_of(frequency: str, run_at: datetime) -> tuple[datetime, datetime]:
    if frequency == "WEEKLY":
        return run_at - timedelta(days=7), run_at
    first = (run_at.replace(day=1) - timedelta(days=1)).replace(day=1)
    return first, run_at


def _key(sub: ReportSubscription) -> str:
    return f"{sub.id}:{sub.next_run_at.isoformat()}"


def _out(sub: ReportSubscription | None) -> dict | None:
    if sub is None or not sub.active:
        return None
    return {"frequency": sub.frequency, "nextRunAt": sub.next_run_at, "lastSentAt": sub.last_sent_at}


async def _require_admin(session: AsyncSession, actor: Actor, org_id: uuid.UUID, *roles: str) -> None:
    held = await buyer_facade.get_member_roles(session, org_id, actor.identity_id)
    if not held:
        raise NotFound("Organisation not found")
    if not held.intersection(roles or (OrgRole.ORG_ADMIN,)):
        raise Forbidden("Dispute reports are for the organisation's admins", code="ROLE_REQUIRED")


async def get_subscription(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> dict | None:
    await _require_admin(session, actor, org_id)
    return _out(await session.scalar(select(ReportSubscription).where(
        ReportSubscription.organization_id == org_id, ReportSubscription.identity_id == actor.identity_id)))


async def set_subscription(session: AsyncSession, actor: Actor, org_id: uuid.UUID, frequency: str | None) -> dict | None:
    await _require_admin(session, actor, org_id)
    sub = await session.scalar(select(ReportSubscription).where(
        ReportSubscription.organization_id == org_id, ReportSubscription.identity_id == actor.identity_id).with_for_update())
    if sub is not None and sub.active:
        await cancel_timer(session, TIMER_REPORT, _key(sub))
    if frequency is None:
        if sub is not None:
            sub.active = False
    else:
        run = next_run(frequency, clock.now())
        if sub is None:
            sub = ReportSubscription(organization_id=org_id, identity_id=actor.identity_id, frequency=frequency, active=True, next_run_at=run)
            session.add(sub)
        else:
            sub.frequency, sub.active, sub.next_run_at = frequency, True, run
        await session.flush()
        await schedule_timer(session, TIMER_REPORT, _key(sub), run, {"subscriptionId": str(sub.id), "runAt": run.isoformat()})
    record_audit(session, "dispute.report.subscription", object_type="Organization", object_id=org_id, tenant_id=org_id,
                 details={"frequency": frequency})
    await session.flush()
    return _out(sub)


async def _cases(session: AsyncSession, org_id: uuid.UUID, since: datetime, until: datetime) -> list[DisputeCase]:
    """Cases opened in the period, decided in it, or still open at its end."""
    from zoikorum.domains.dispute.service import OPEN
    return list((await session.scalars(select(DisputeCase).where(
        DisputeCase.organization_id == org_id, DisputeCase.created_at < until,
        or_(DisputeCase.created_at >= since, DisputeCase.status.in_(OPEN), DisputeCase.decided_at >= since))
        .order_by(DisputeCase.created_at))).all())


async def export_csv(session: AsyncSession, actor: Actor, org_id: uuid.UUID, since: datetime | None, until: datetime | None) -> tuple[bytes, str]:
    await _require_admin(session, actor, org_id, OrgRole.ORG_ADMIN, OrgRole.LEGAL_REVIEWER)
    until = until or clock.now()
    since = since or until - timedelta(days=30)
    if since >= until or until - since > timedelta(days=400):
        raise ValidationFailed("Choose a period of at most 400 days", code="INVALID_PERIOD")
    rows = await _cases(session, org_id, since, until)
    names: dict[uuid.UUID, str] = {}
    for r in rows:
        if r.professional_id not in names:
            pro = await professional_facade.get_professional(session, r.professional_id)
            names[r.professional_id] = pro.display_name if pro else ""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["reference", "engagement", "professional", "category", "status", "currency", "disputed", "opened_at", "decided_at",
                "days_to_decision", "outcome", "decision_path"])
    for r in rows:
        decision = r.decision or {}
        w.writerow([r.reference, r.contract_reference, names[r.professional_id], r.category, r.status, r.currency,
                    f"{r.disputed_minor / 100:.2f}", r.created_at.isoformat(), r.decided_at.isoformat() if r.decided_at else "",
                    f"{(r.decided_at - r.created_at).total_seconds() / 86400:.1f}" if r.decided_at else "",
                    decision.get("outcome", ""), decision.get("decisionPath", "")])
    record_audit(session, "dispute.report.exported", object_type="Organization", object_id=org_id, tenant_id=org_id,
                 details={"from": since.isoformat(), "to": until.isoformat(), "rows": len(rows)})
    return buf.getvalue().encode(), f"disputes-{since:%Y%m%d}-{until:%Y%m%d}.csv"


async def report_due(session: AsyncSession, payload: dict) -> None:
    """Timer: send this period's report to the subscriber, then arm the next one. Someone who is no longer an
    Organisation Admin stops receiving it."""
    from zoikorum.domains.dispute.service import OPEN

    sub = await session.get(ReportSubscription, uuid.UUID(payload["subscriptionId"]), with_for_update=True)
    if sub is None or not sub.active or sub.next_run_at.isoformat() != payload.get("runAt"):
        return
    if OrgRole.ORG_ADMIN not in await buyer_facade.get_member_roles(session, sub.organization_id, sub.identity_id):
        sub.active = False
        return
    since, until = period_of(sub.frequency, sub.next_run_at)
    rows = await _cases(session, sub.organization_id, since, until)
    opened = sum(1 for r in rows if r.created_at >= since)
    decided = sum(1 for r in rows if r.decided_at and r.decided_at >= since)
    still_open = sum(1 for r in rows if r.status in OPEN)
    frozen: dict[str, int] = {}
    for r in rows:
        if r.status in (*OPEN, "DECIDED"):
            frozen[r.currency] = frozen.get(r.currency, 0) + r.disputed_minor
    url = f"{EXPORT_PATH}?orgId={sub.organization_id}&from={since.isoformat()}&to={until.isoformat()}"
    money = ", ".join(f"{c} {v / 100:,.2f}" for c, v in sorted(frozen.items())) or "none"
    record_event(session, E.DISPUTE_REPORT_READY, aggregate_type="DisputeReportSubscription", aggregate_id=sub.id,
                 payload={"recipientIdentityIds": [str(sub.identity_id)], "frequency": sub.frequency, "periodFrom": since.isoformat(),
                          "periodTo": until.isoformat(), "reportUrl": url, "opened": opened, "decided": decided, "open": still_open,
                          "message": f"Your {sub.frequency.lower()} dispute report ({since:%d %b} - {until:%d %b %Y}): {opened} opened, "
                                     f"{decided} decided, {still_open} still open. Money frozen: {money}. Download the CSV from "
                                     f"Disputes > Dashboard, or {url}"})
    sub.last_sent_at = clock.now()
    sub.next_run_at = next_run(sub.frequency, sub.next_run_at)
    await schedule_timer(session, TIMER_REPORT, _key(sub), sub.next_run_at, {"subscriptionId": str(sub.id), "runAt": sub.next_run_at.isoformat()})
