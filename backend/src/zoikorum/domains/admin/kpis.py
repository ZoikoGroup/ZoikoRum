"""Platform KPIs for staff and the board (Governance playbook and board brief): onboarding, trust, engagements,
money, disputes and enforcement for a period. Each figure comes from the domain that owns it, aggregated in SQL."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.admin.models import EnforcementCase, Incident
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.capabilities import Cap


async def _enforcement(session: AsyncSession, since: datetime, until: datetime) -> dict:
    window = [EnforcementCase.created_at >= since, EnforcementCase.created_at < until]
    by_status = dict((await session.execute(select(EnforcementCase.status, func.count()).where(*window)
                                            .group_by(EnforcementCase.status))).all())
    actions = dict((await session.execute(select(EnforcementCase.action, func.count()).where(*window, EnforcementCase.action.is_not(None))
                                          .group_by(EnforcementCase.action))).all())
    open_now = await session.scalar(select(func.count()).select_from(EnforcementCase).where(
        EnforcementCase.status.in_(("TRIAGE", "ASSESSED")))) or 0  # not yet decided
    triaged = [(u - c).total_seconds() / 3600 for c, u in (await session.execute(select(EnforcementCase.created_at, EnforcementCase.updated_at)
               .where(*window, EnforcementCase.status != "TRIAGE"))).all()]
    incidents = dict((await session.execute(select(Incident.severity, func.count()).where(
        Incident.created_at >= since, Incident.created_at < until).group_by(Incident.severity))).all())
    incidents_open = await session.scalar(select(func.count()).select_from(Incident).where(Incident.status != "CLOSED")) or 0
    by_level = {f"L{level}": n for level, n in (await session.execute(select(EnforcementCase.level, func.count()).where(
        *window, EnforcementCase.level > 0).group_by(EnforcementCase.level).order_by(EnforcementCase.level))).all()}

    applied = (await session.execute(select(EnforcementCase.subject_id, EnforcementCase.status).where(
        EnforcementCase.applied_at >= since, EnforcementCase.applied_at < until))).all()
    reversed_ = sum(1 for _, status in applied if status == "REVERSED")
    subjects = {s for s, _ in applied}
    recurring = 0  # subjects actioned in the period who had another action applied before or during it
    if subjects:
        recurring = await session.scalar(select(func.count()).select_from(
            select(EnforcementCase.subject_id).where(EnforcementCase.subject_id.in_(subjects), EnforcementCase.applied_at < until)
            .group_by(EnforcementCase.subject_id).having(func.count() >= 2).subquery())) or 0

    filed = decided = upheld = 0
    for (appeal,) in (await session.execute(select(EnforcementCase.appeal).where(EnforcementCase.appeal.is_not(None)))).all():
        if since <= _when(appeal.get("filedAt")) < until:
            filed += 1
        if appeal.get("status") in ("UPHELD", "REJECTED") and since <= _when(appeal.get("decidedAt")) < until:
            decided += 1
            upheld += appeal["status"] == "UPHELD"
    return {"casesOpened": sum(by_status.values()), "byStatus": by_status, "actionsTaken": actions, "openNow": open_now,
            "medianHoursToFirstDecision": round(median(triaged), 1) if triaged else None,
            "incidentsBySeverity": incidents, "incidentsOpenNow": incidents_open,
            "byLevel": by_level, "actionsApplied": len(applied), "reversed": reversed_, "reversalRatePct": _pct(reversed_, len(applied)),
            "appealsFiled": filed, "appealsDecided": decided, "appealsUpheld": upheld, "appealSuccessRatePct": _pct(upheld, decided),
            "subjectsActioned": len(subjects), "recurringSubjects": recurring}


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole else None


def _when(value) -> datetime:
    """An ISO time from a JSON record; a missing or unreadable one sorts before any period."""
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)



async def report(session: AsyncSession, actor: Actor, since: datetime | None, until: datetime | None) -> dict:
    actor.require_capability(Cap.ANALYTICS_KPIS_READ)
    from zoikorum.domains.contract import facade as contract_facade
    from zoikorum.domains.dispute import facade as dispute_facade
    from zoikorum.domains.escrow import facade as escrow_facade
    from zoikorum.domains.policy import facade as policy_facade
    from zoikorum.domains.professional import facade as professional_facade
    from zoikorum.domains.trust import facade as trust_facade
    from zoikorum.domains.verification import facade as verification_facade

    until = until or clock.now()
    since = since or until - timedelta(days=30)
    onboarding = await professional_facade.funnel(session, since, until)
    trust = await trust_facade.tier_kpis(session, since, until)
    engagements = await contract_facade.activity_kpis(session, since, until)
    payments = await escrow_facade.kpis(session, since, until)
    disputes = await dispute_facade.kpis(session, since, until)
    enforcement = await _enforcement(session, since, until)
    disputes.update(await dispute_facade.quality_kpis(session, since, until))
    refunds = await escrow_facade.refund_kpis(session, since, until)
    payments.update({
        "acceptance": await contract_facade.acceptance_kpis(session, since, until),
        "paymentsCaptured": refunds["payments"], "refunds": refunds["refunds"],
        "refundsPer100Payments": _pct(refunds["refunds"], refunds["payments"]),
        "refundsByCurrency": refunds["byCurrency"],
        "disputesPer100Payments": _pct(disputes["opened"], refunds["payments"]),
        "approvals": await policy_facade.approval_bottlenecks(session, since, until),
    })
    enterprise = await professional_facade.enterprise_cycle(session, since, until)
    board = {
        "grossReleasedByCurrency": [{"currency": r["currency"], "amountMinor": r["releasedMinor"]} for r in payments["byCurrency"]],
        "feesByCurrency": [{"currency": r["currency"], "amountMinor": r["feesMinor"]} for r in payments["byCurrency"]],
        "engagementsStarted": engagements["engagementsStarted"], "activeBuyerOrganisations": engagements["activeBuyerOrganisations"],
        "disputeRatePct": round(100 * disputes["opened"] / engagements["engagementsStarted"], 1) if engagements["engagementsStarted"] else None,
        "verifiedSupply": trust["tiersNow"].get("A", 0) + trust["tiersNow"].get("B", 0),
        "seriousIncidents": sum(n for sev, n in enforcement["incidentsBySeverity"].items() if sev in ("SEV1", "SEV2")),
        "trustTierTrend": await trust_facade.tier_trend(session, since, until),
        "enforcementReversalRatePct": enforcement["reversalRatePct"],
        "credentialExpiryIncidents": await verification_facade.credential_expiries(session, since, until),
        "enterpriseOnboarding": enterprise,
    }
    return {"from": since, "to": until, "board": board, "onboarding": onboarding, "trust": trust, "engagements": engagements,
            "payments": payments, "disputes": disputes, "enforcement": enforcement}
