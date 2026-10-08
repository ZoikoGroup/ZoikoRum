from __future__ import annotations

from fastapi import APIRouter

from zoikorum.domains.admin import service
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
import uuid
from sqlalchemy import select
from fastapi import Query
from zoikorum.domains.admin.models import EnforcementCase
from zoikorum.domains.admin.schemas import CaseIn, AssessmentIn, ActionIn, ReasonIn, AppealDecisionIn
from zoikorum.shared.auth import PlatformRole
from zoikorum.shared.idempotency import IdempotencyKey
from zoikorum.shared.platform_models import ConsumerFailure
from zoikorum.shared.relay import replay_dead_letter
from zoikorum.shared.db import session_factory
from zoikorum.shared.events import record_audit
from zoikorum.shared.errors import NotFound, Conflict

router = APIRouter(tags=["admin"])


@router.get("/v1/admin/enforcement-cases")
async def cases(actor: CurrentActor, session: DbSession, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    await service.staff(session, actor, *PlatformRole.ALL)
    rows = (await session.scalars(select(EnforcementCase).order_by(EnforcementCase.created_at.desc()).limit(limit).offset(offset))).all()
    return [service.case_out(c) for c in rows]


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
async def appeal(case_id: uuid.UUID, body: ReasonIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.file_appeal(session, actor, case_id, body.reason))


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


@router.get("/v1/admin/overview")
async def overview(actor: CurrentActor, session: DbSession) -> dict:
    """Staff: platform counts (accounts, professional profiles, open verification checks)."""
    return await service.overview(session, actor)
