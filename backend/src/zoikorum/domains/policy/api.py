from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Query
from sqlalchemy import select

from zoikorum.domains.policy import service
from zoikorum.domains.policy.facade import PolicyContext
from zoikorum.domains.policy.models import ApprovalRequest, ExceptionRequest
from zoikorum.domains.policy.schemas import (
    ApprovalDecisionIn, DraftIn, EvaluateIn, ExceptionDecisionIn, ExceptionIn, ProfileIn,
)
from zoikorum.domains.search import facade as search
from zoikorum.shared.auth import CurrentActor, OrgRole
from zoikorum.shared.db import DbSession
from zoikorum.shared.errors import NotFound
from zoikorum.shared.http import page_of, paginate
from zoikorum.shared.events import record_audit
from zoikorum.shared.uploads import file_response, find_file, read_file

router = APIRouter(prefix="/v1/policy", tags=["enterprise policies"])


@router.get("/profiles")
async def profiles(orgId: uuid.UUID, actor: CurrentActor, session: DbSession,
    cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
    return await service.list_profiles(session, actor, orgId, cursor, limit)


@router.post("/profiles", status_code=201)
async def create_profile(body: ProfileIn, actor: CurrentActor, session: DbSession):
    return await service.create_profile(session, actor, body)


@router.get("/profiles/{profile_id}")
async def profile(profile_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.profile_out(session, await service.get_profile(session, actor, profile_id))


@router.put("/profiles/{profile_id}/draft")
async def edit_draft(profile_id: uuid.UUID, body: DraftIn, actor: CurrentActor, session: DbSession):
    return await service.update_draft(session, actor, profile_id, body)


@router.post("/profiles/{profile_id}/draft")
async def new_draft(profile_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.new_draft(session, actor, profile_id)


@router.post("/profiles/{profile_id}/activate")
async def activate(profile_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.activate(session, actor, profile_id)


@router.get("/profiles/{profile_id}/impact")
async def impact(profile_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    profile = await service.get_profile(session, actor, profile_id)
    from zoikorum.domains.policy.models import PolicyVersion
    version = await session.get(PolicyVersion, profile.draft_version_id or profile.active_version_id)
    filters = {"minTier": version.settings["minTrustTier"],
        "requiredDimensions": version.settings["requiredDimensions"],
        "jurisdictions": version.settings.get("allowedJurisdictions")}
    return {"eligibleProfessionals": await search.count_eligible(session, filters),
        "settings": version.settings, "rules": version.rules,
        "scope": "Current search projections and trust settings; transaction-specific rules require a dry run."}


@router.post("/dry-run")
async def dry_run(body: EvaluateIn, actor: CurrentActor, session: DbSession):
    await service.require_member(session, actor, body.orgId, OrgRole.ORG_ADMIN)
    return asdict(await service.evaluate(session, PolicyContext(body.orgId, body.action,
        body.subjectType, body.subjectId, actor.identity_id, body.attributes, body.pinnedPolicyVersionId),
        dry_run=True, preview_profile_id=body.previewProfileId))


@router.get("/approvals")
async def approvals(orgId: uuid.UUID, actor: CurrentActor, session: DbSession,
    cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
    await service.require_member(session, actor, orgId)
    stmt, lim = paginate(select(ApprovalRequest).where(ApprovalRequest.organization_id == orgId), ApprovalRequest, cursor, limit)
    rows = list((await session.scalars(stmt)).all())
    outputs = {r.id: await service.approval_out(session, r) for r in rows[:lim]}
    return page_of(rows, lim, lambda r: outputs[r.id])


@router.post("/approvals/{request_id}/decide")
async def decide_approval(request_id: uuid.UUID, body: ApprovalDecisionIn, actor: CurrentActor, session: DbSession):
    return await service.decide_approval(session, actor, request_id, body)


@router.get("/exceptions")
async def exceptions(orgId: uuid.UUID, actor: CurrentActor, session: DbSession,
    cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
    await service.require_member(session, actor, orgId)
    stmt, lim = paginate(select(ExceptionRequest).where(ExceptionRequest.organization_id == orgId), ExceptionRequest, cursor, limit)
    return page_of(list((await session.scalars(stmt)).all()), lim, service.exception_out)


@router.post("/exceptions", status_code=201)
async def request_exception(body: ExceptionIn, actor: CurrentActor, session: DbSession):
    return await service.create_exception(session, actor, body)


@router.post("/exceptions/{request_id}/decide")
async def decide_exception(request_id: uuid.UUID, body: ExceptionDecisionIn, actor: CurrentActor, session: DbSession):
    return await service.decide_exception(session, actor, request_id, body)


@router.get("/exceptions/{request_id}/documents/{digest}")
async def exception_file(request_id: uuid.UUID, digest: str, actor: CurrentActor, session: DbSession):
    request = await session.get(ExceptionRequest, request_id)
    if not request:
        raise NotFound("Exception request not found")
    await service.require_member(session, actor, request.organization_id)
    record = find_file(request.documents, digest)
    record_audit(session, "policy.exception.document.viewed", object_type="ExceptionRequest", object_id=request.id,
        tenant_id=request.organization_id, evidence_hash=record['sha256'])
    return file_response(read_file(record), record.get("contentType"), record["name"])
