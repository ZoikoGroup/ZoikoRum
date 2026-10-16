"""Platform KPIs for staff and the board (Governance playbook and board brief): onboarding, trust, engagements,
money, disputes and enforcement for a period. Each figure comes from the domain that owns it, aggregated in SQL."""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.admin.models import EnforcementCase, Incident
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole


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
    return {"casesOpened": sum(by_status.values()), "byStatus": by_status, "actionsTaken": actions, "openNow": open_now,
            "medianHoursToFirstDecision": round(median(triaged), 1) if triaged else None,
            "incidentsBySeverity": incidents, "incidentsOpenNow": incidents_open}


async def report(session: AsyncSession, actor: Actor, since: datetime | None, until: datetime | None) -> dict:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN, PlatformRole.TS_ANALYST, PlatformRole.FINANCIAL_OPS,
                                PlatformRole.RISK_LEAD, PlatformRole.LEGAL, PlatformRole.COMPLIANCE_OFFICER)
    from zoikorum.domains.contract import facade as contract_facade
    from zoikorum.domains.dispute import facade as dispute_facade
    from zoikorum.domains.escrow import facade as escrow_facade
    from zoikorum.domains.professional import facade as professional_facade
    from zoikorum.domains.trust import facade as trust_facade

    until = until or clock.now()
    since = since or until - timedelta(days=30)
    onboarding = await professional_facade.funnel(session, since, until)
    trust = await trust_facade.tier_kpis(session, since, until)
    engagements = await contract_facade.activity_kpis(session, since, until)
    payments = await escrow_facade.kpis(session, since, until)
    disputes = await dispute_facade.kpis(session, since, until)
    enforcement = await _enforcement(session, since, until)
    board = {
        "grossReleasedByCurrency": [{"currency": r["currency"], "amountMinor": r["releasedMinor"]} for r in payments["byCurrency"]],
        "feesByCurrency": [{"currency": r["currency"], "amountMinor": r["feesMinor"]} for r in payments["byCurrency"]],
        "engagementsStarted": engagements["engagementsStarted"], "activeBuyerOrganisations": engagements["activeBuyerOrganisations"],
        "disputeRatePct": round(100 * disputes["opened"] / engagements["engagementsStarted"], 1) if engagements["engagementsStarted"] else None,
        "verifiedSupply": trust["tiersNow"].get("A", 0) + trust["tiersNow"].get("B", 0),
        "seriousIncidents": sum(n for sev, n in enforcement["incidentsBySeverity"].items() if sev in ("SEV1", "SEV2")),
    }
    return {"from": since, "to": until, "board": board, "onboarding": onboarding, "trust": trust, "engagements": engagements,
            "payments": payments, "disputes": disputes, "enforcement": enforcement}
