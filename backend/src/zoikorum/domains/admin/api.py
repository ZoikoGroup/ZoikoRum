from __future__ import annotations

from fastapi import Response, APIRouter
from pydantic import BaseModel, Field

from zoikorum.domains.admin import service, switches
from zoikorum.domains.admin.incidents import IncidentIn, IncidentUpdateIn
from zoikorum.shared.auth import OptionalActor, CurrentActor
from zoikorum.shared import metrics
from zoikorum.shared.db import AnalyticsSession, DbSession
import uuid
from typing import Literal
from datetime import datetime
from sqlalchemy import select
from fastapi import Query
from zoikorum.domains.admin.models import EnforcementCase
from zoikorum.domains.admin.schemas import (
    ActionIn, AppealDecisionIn, AppealIn, AssessmentIn, CaseIn, CloseCaseIn, OverrideIn, ReasonIn, RemediationDoneIn, ReportIn,
)
from zoikorum.shared.auth import PlatformRole
from zoikorum.shared.idempotency import IdempotencyKey
from zoikorum.shared.platform_models import ConsumerFailure
from zoikorum.shared.relay import replay_dead_letter
from zoikorum.shared.db import session_factory
from zoikorum.shared.events import record_audit
from zoikorum.shared.errors import NotFound, Conflict

router = APIRouter(tags=["admin"])


@router.get("/v1/admin/enforcement-cases")
async def cases(actor: CurrentActor, session: DbSession, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                status_: str | None = Query(default=None, alias="status"), level: int | None = Query(default=None, ge=0, le=4),
                overdue: bool = False, source: str | None = None):
    """Staff queue. Cases past their triage target come first; filter by status, level, source or overdue."""
    return await service.queue(session, actor, status_, level, overdue, source, limit, offset)


@router.get("/v1/enforcement-cases")
async def own_cases(actor: CurrentActor, session: DbSession):
    from zoikorum.domains.professional import facade as professional
    from zoikorum.shared.auth import OrgRole
    from zoikorum.domains.buyer import facade as buyer
    from sqlalchemy import or_, and_
    pro = await professional.get_professional_by_identity(session, actor.identity_id)
    organizations = await buyer.list_identity_organizations(session, actor.identity_id)
    org_ids = [o for o in organizations if OrgRole.ORG_ADMIN in await buyer.get_member_roles(session, o, actor.identity_id)]
    scope = [and_(EnforcementCase.subject_type == "IDENTITY", EnforcementCase.subject_id == actor.identity_id),
             and_(EnforcementCase.subject_type == "ORGANIZATION", EnforcementCase.subject_id.in_(org_ids))]
    if pro:
        scope.append(and_(EnforcementCase.subject_type == "PROFESSIONAL", EnforcementCase.subject_id == pro.id))
    rows = (await session.scalars(select(EnforcementCase).where(or_(*scope), EnforcementCase.applied_at.is_not(None)).order_by(EnforcementCase.created_at.desc()))).all()
    return [service.case_out(c) for c in rows]


@router.post("/v1/admin/enforcement-cases", status_code=201)
async def open_case(body: CaseIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.open_case(session, actor, body), status_code=201)


@router.post("/v1/admin/enforcement-cases/{case_id}/assess")
async def assess(case_id: uuid.UUID, body: AssessmentIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.assess(session, actor, case_id, body))


@router.post("/v1/admin/enforcement-cases/{case_id}/propose-action")
async def propose(case_id: uuid.UUID, body: ActionIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.propose_action(session, actor, case_id, body))


@router.post("/v1/admin/enforcement-cases/{case_id}/approve-action")
async def approve(case_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.approve_action(session, actor, case_id))


@router.post("/v1/admin/enforcement-cases/{case_id}/reverse")
async def reverse(case_id: uuid.UUID, body: ReasonIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.reverse_case(session, actor, case_id, body.reason))


@router.post("/v1/enforcement-cases/{case_id}/appeal")
async def file_appeal(case_id: uuid.UUID, body: AppealIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """The person appeals a Level 2+ action within the appeal window, with their reasons and documents."""
    return await idem.run(session, actor, lambda: service.file_appeal(session, actor, case_id, body.reason, body.evidence))


@router.post("/v1/admin/enforcement-cases/{case_id}/appeal/decision")
async def decide_appeal(case_id: uuid.UUID, body: AppealDecisionIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.decide_appeal(session, actor, case_id, body))


@router.get("/v1/admin/dead-letters")
async def dead_letters(actor: CurrentActor, session: DbSession, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    await service.staff(session, actor, PlatformRole.PLATFORM_ADMIN, PlatformRole.FINANCIAL_OPS)
    rows = (await session.scalars(select(ConsumerFailure).where(ConsumerFailure.status == "DEAD").order_by(ConsumerFailure.created_at.desc()).limit(limit).offset(offset))).all()
    return [{"id": r.id, "eventType": r.event_type, "consumer": r.consumer, "attempts": r.attempts, "financial": r.financial, "lastError": r.last_error} for r in rows]


@router.post("/v1/admin/dead-letters/{failure_id}/replay")
async def replay(failure_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    await service.staff(session, actor, PlatformRole.PLATFORM_ADMIN, PlatformRole.FINANCIAL_OPS)
    actor.require_step_up()
    row = await session.get(ConsumerFailure, failure_id)
    if not row:
        raise NotFound("Delivery failure not found")
    financial_ops = PlatformRole.FINANCIAL_OPS in await service.identity_facade.live_platform_roles(session, actor.identity_id)
    if row.financial and not financial_ops:
        from zoikorum.shared.errors import Forbidden
        raise Forbidden("Financial replay requires Financial Operations authority")
    if row.status != "DEAD":
        raise Conflict("Only dead-lettered deliveries can be replayed")
    ok = await replay_dead_letter(session_factory(), failure_id, authorised_by=str(actor.identity_id), financial_ops=financial_ops)
    record_audit(session, "admin.dead_letter.replayed", object_type="ConsumerFailure", object_id=failure_id, details={"succeeded": ok})
    return {"replayed": ok}


class SwitchIn(BaseModel):
    paused: bool
    reason: str = Field(min_length=10, max_length=500)


@router.get("/v1/admin/switches")
async def list_switches(actor: CurrentActor, session: DbSession) -> list[dict]:
    """Staff: the operational switches and who last changed each one."""
    await service.staff(session, actor, PlatformRole.PLATFORM_ADMIN, PlatformRole.FINANCIAL_OPS)
    return await switches.list_switches(session)


@router.put("/v1/admin/switches/{key}")
async def set_switch(key: str, body: SwitchIn, actor: CurrentActor, session: DbSession) -> dict:
    """Pause or resume one kind of action at once (step-up, reason, audited). Money switches: Platform Admin or
    Financial Operations; the others: Platform Admin."""
    return await switches.set_switch(session, actor, key, body.paused, body.reason)


@router.get("/v1/admin/worker")
async def worker(actor: CurrentActor, session: DbSession) -> dict:
    """Staff: how far behind the background worker is (the same numbers as GET /metrics)."""
    await service.staff(session, actor, PlatformRole.PLATFORM_ADMIN, PlatformRole.FINANCIAL_OPS)
    return await metrics.worker_backlog(session)


@router.get("/v1/admin/overview")
async def overview(actor: CurrentActor, session: DbSession) -> dict:
    """Staff: platform counts (accounts, professional profiles, open verification checks)."""
    return await service.overview(session, actor)



# ---- User reports ------------------------------------------------------------------------------------------------

@router.post("/v1/reports", status_code=201)
async def submit_report(body: ReportIn, actor: CurrentActor, session: DbSession):
    """Report a profile, account, organisation, review or message to Trust & Safety. The reported person is never told
    who reported; a report never restricts anyone by itself."""
    from zoikorum.domains.admin import reports
    return await reports.submit(session, actor, body)


@router.get("/v1/reports/mine")
async def my_reports(actor: CurrentActor, session: DbSession):
    from zoikorum.domains.admin import reports
    return await reports.mine(session, actor)


@router.get("/v1/admin/enforcement-cases/{case_id}/reports")
async def case_reports(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    from zoikorum.domains.admin import reports
    await service.staff(session, actor, PlatformRole.TS_ANALYST, PlatformRole.RISK_LEAD, PlatformRole.LEGAL)
    return await reports.for_case(session, actor, case_id)


@router.post("/v1/admin/enforcement-cases/{case_id}/close")
async def close_case(case_id: uuid.UUID, body: CloseCaseIn, actor: CurrentActor, session: DbSession):
    """Reviewed, no action needed. Reporters are told it was reviewed."""
    return await service.close_case(session, actor, case_id, body.reason)



@router.post("/v1/enforcement-cases/{case_id}/remediation/{index}/done")
async def remediation_done(case_id: uuid.UUID, index: int, body: RemediationDoneIn, actor: CurrentActor, session: DbSession):
    return await service.remediation_done(session, actor, case_id, index, body.note)


@router.post("/v1/admin/enforcement-cases/{case_id}/remediation/{index}/confirm")
async def remediation_confirm(case_id: uuid.UUID, index: int, actor: CurrentActor, session: DbSession):
    return await service.remediation_confirm(session, actor, case_id, index)


@router.post("/v1/admin/enforcement-cases/{case_id}/executive-override")
async def executive_override(case_id: uuid.UUID, body: OverrideIn, actor: CurrentActor, session: DbSession):
    """Executive final authority: end an active action, with a recorded justification."""
    return await service.executive_override(session, actor, case_id, body.reason)



# ---- Incident register ---------------------------------------------------------------------------------------------

@router.get("/v1/admin/incidents")
async def incidents(actor: CurrentActor, session: DbSession, status_: str | None = Query(default=None, alias="status")):
    from zoikorum.domains.admin import incidents as register
    return await register.list_incidents(session, actor, status_)


@router.post("/v1/admin/incidents", status_code=201)
async def open_incident(body: IncidentIn, actor: CurrentActor, session: DbSession):
    from zoikorum.domains.admin import incidents as register
    return await register.open_incident(session, actor, body)


@router.patch("/v1/admin/incidents/{incident_id}")
async def update_incident(incident_id: uuid.UUID, body: IncidentUpdateIn, actor: CurrentActor, session: DbSession):
    from zoikorum.domains.admin import incidents as register
    return await register.update_incident(session, actor, incident_id, body)


@router.get("/v1/admin/kpis")
async def platform_kpis(actor: CurrentActor, session: AnalyticsSession, since: datetime | None = Query(None, alias="from"),
                        until: datetime | None = Query(None, alias="to")) -> dict:
    """Staff: platform KPIs for a period (default the last 30 days): board figures, onboarding, trust, engagements,
    money through escrow, disputes and enforcement."""
    from zoikorum.domains.admin import kpis

    return await kpis.report(session, actor, since, until)


class FlagIn(BaseModel):
    rolloutPct: int = Field(ge=0, le=100)
    organizationIds: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    reason: str = Field(min_length=10, max_length=500)


@router.get("/v1/flags")
async def my_flags(actor: OptionalActor, session: DbSession) -> dict:
    """Which feature flags are on for the signed-in person (and their organisation), for the web app."""
    from zoikorum.domains.admin import flags
    from zoikorum.domains.buyer import facade as buyer_facade

    org = None
    if actor:
        orgs = await buyer_facade.list_identity_organizations(session, actor.identity_id)
        org = orgs[0] if orgs else None
    return {k: await flags.enabled(session, k, actor.identity_id if actor else None, org) for k in flags.FLAGS}


@router.get("/v1/admin/flags")
async def list_flags(actor: CurrentActor, session: DbSession) -> list[dict]:
    from zoikorum.domains.admin import flags

    await service.staff(session, actor, PlatformRole.PLATFORM_ADMIN)
    return await flags.list_flags(session)


@router.get("/v1/admin/flags/{key}/fairness")
async def flag_fairness(key: str, actor: CurrentActor, session: DbSession) -> dict:
    """Ranking experiments: each group's share of top-10 search places with and without the change."""
    from zoikorum.domains.admin import flags

    await service.staff(session, actor, PlatformRole.PLATFORM_ADMIN)
    return await flags.fairness(session, key)


@router.put("/v1/admin/flags/{key}")
async def set_flag(key: str, body: FlagIn, actor: CurrentActor, session: DbSession) -> dict:
    """Platform Admin: roll a flag out to a percentage of people and named organisations (step-up, reason, audited)."""
    from zoikorum.domains.admin import flags

    return await flags.set_flag(session, actor, key, body.rolloutPct, body.organizationIds, body.reason)


class ApiKeyTierIn(BaseModel):
    tier: Literal["STANDARD", "ENTERPRISE"]


@router.put("/v1/admin/api-keys/{key_id}/tier")
async def set_api_key_tier(key_id: uuid.UUID, body: ApiKeyTierIn, actor: CurrentActor, session: DbSession) -> dict:
    """Platform Admin: the request budget agreed with the organisation for this key."""
    from zoikorum.domains.buyer import facade as buyer_facade
    return await buyer_facade.set_api_key_tier(session, actor, key_id, body.tier)


@router.get("/v1/procurement-pack")
async def procurement_pack(actor: CurrentActor, format: Literal["pdf", "json"] = "pdf") -> Response:
    """Signed-in customers: the security and compliance summary for a procurement review, built from live configuration."""
    from zoikorum.domains.admin import procurement

    data, name, media = procurement.render(format)
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/v1/admin/risk")
async def risk_top(actor: CurrentActor, session: DbSession, limit: int = 25) -> list[dict]:
    """Trust & Safety: the highest risk scores (last 30 days) with the signals behind them. Advisory only."""
    from zoikorum.domains.ai import facade as ai_facade
    return await ai_facade.risk_top(session, actor, max(1, min(limit, 100)))


@router.get("/v1/admin/risk/{subject_type}/{subject_id}")
async def risk_of(subject_type: Literal["IDENTITY", "ORGANIZATION"], subject_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    from zoikorum.domains.ai import facade as ai_facade
    return await ai_facade.risk_explain(session, actor, subject_type, subject_id)


@router.get("/v1/admin/audit/archives")
async def audit_archives(actor: CurrentActor, session: DbSession) -> list[dict]:
    """Audit records archived to write-once storage after 90 days, newest first."""
    from zoikorum.domains.audit import facade as audit_facade
    return await audit_facade.list_archives(session, actor)


@router.post("/v1/admin/audit/archives/{archive_id}/verify")
async def verify_audit_archive(archive_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """Read an archive back and check its fingerprint and hash chain."""
    from zoikorum.domains.audit import facade as audit_facade
    return await audit_facade.verify_archive(session, actor, archive_id)



class AdminConfigSettingOut(BaseModel):
    key: str  # the environment variable, e.g. ZK_PLATFORM_FEE_BPS
    value: str
    description: str | None


class AdminConfigGroupOut(BaseModel):
    domain: str
    settings: list[AdminConfigSettingOut]


class AdminConfigOut(BaseModel):
    environment: str
    version: str | None
    groups: list[AdminConfigGroupOut]


@router.get("/v1/admin/config", response_model=AdminConfigOut)
async def admin_config(actor: CurrentActor):
    """Platform Admin: the business rules in force (fees, windows, limits, service levels, providers). Secrets,
    credentials and connection strings are never included."""
    return service.admin_config(actor)
