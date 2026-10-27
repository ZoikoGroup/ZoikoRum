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
from zoikorum.shared.errors import Conflict, NotFound
from zoikorum.shared.http import page_of, paginate
from zoikorum.shared.events import record_audit
from zoikorum.shared.uploads import file_response, find_file, read_file
from zoikorum.shared.idempotency import OptionalIdempotencyKey

router = APIRouter(prefix="/v1/policy", tags=["enterprise policies"])


@router.get("/profiles")
async def profiles(orgId: uuid.UUID, actor: CurrentActor, session: DbSession,
    cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
    return await service.list_profiles(session, actor, orgId, cursor, limit)


@router.post("/profiles", status_code=201)
async def create_profile(body: ProfileIn, actor: CurrentActor, session: DbSession, idem: OptionalIdempotencyKey):
    return await idem.run(session, actor, lambda: service.create_profile(session, actor, body), status_code=201)


@router.get("/profiles/{profile_id}")
async def profile(profile_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    from zoikorum.shared import cache
    p = await service.get_profile(session, actor, profile_id)  # access is checked on every read, cached or not
    # Keyed by the profile's version too: any change to the profile is a new key, even before the event drops the rest.
    return await cache.cached(cache.POLICY_PROFILES, f"{p.id}:{p.version}:{p.updated_at.isoformat() if p.updated_at else ''}",
                              lambda: service.profile_out(session, p))


@router.put("/profiles/{profile_id}/draft")
async def edit_draft(profile_id: uuid.UUID, body: DraftIn, actor: CurrentActor, session: DbSession, idem: OptionalIdempotencyKey):
    return await idem.run(session, actor, lambda: service.update_draft(session, actor, profile_id, body))


@router.post("/profiles/{profile_id}/draft")
async def new_draft(profile_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: OptionalIdempotencyKey):
    return await idem.run(session, actor, lambda: service.new_draft(session, actor, profile_id))


@router.post("/profiles/{profile_id}/activate")
async def activate(profile_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: OptionalIdempotencyKey):
    return await idem.run(session, actor, lambda: service.activate(session, actor, profile_id))


@router.get("/profiles/{profile_id}/impact")
async def impact(profile_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    profile = await service.get_profile(session, actor, profile_id)
    from zoikorum.domains.policy.models import PolicyVersion
    version_id = profile.draft_version_id or profile.active_version_id
    version = await session.get(PolicyVersion, version_id) if version_id else None
    if version is None:
        raise Conflict("This profile has no active or draft version to preview", code="NO_VERSION")
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
async def decide_approval(request_id: uuid.UUID, body: ApprovalDecisionIn, actor: CurrentActor, session: DbSession, idem: OptionalIdempotencyKey):
    return await idem.run(session, actor, lambda: service.decide_approval(session, actor, request_id, body))


@router.get("/exceptions")
async def exceptions(orgId: uuid.UUID, actor: CurrentActor, session: DbSession,
    cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
    await service.require_member(session, actor, orgId)
    stmt, lim = paginate(select(ExceptionRequest).where(ExceptionRequest.organization_id == orgId), ExceptionRequest, cursor, limit)
    return page_of(list((await session.scalars(stmt)).all()), lim, service.exception_out)


@router.post("/exceptions", status_code=201)
async def request_exception(body: ExceptionIn, actor: CurrentActor, session: DbSession, idem: OptionalIdempotencyKey):
    return await idem.run(session, actor, lambda: service.create_exception(session, actor, body), status_code=201)


@router.post("/exceptions/{request_id}/decide")
async def decide_exception(request_id: uuid.UUID, body: ExceptionDecisionIn, actor: CurrentActor, session: DbSession, idem: OptionalIdempotencyKey):
    return await idem.run(session, actor, lambda: service.decide_exception(session, actor, request_id, body))


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


@router.get("/profiles/{profile_id}/checks")
async def profile_checks(profile_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """Builder checks for the draft (or active) version, and where the profile applies."""
    from zoikorum.domains.buyer import facade as buyer_facade
    from zoikorum.domains.policy import insights
    from zoikorum.domains.policy.models import PolicyVersion

    profile = await service.get_profile(session, actor, profile_id)
    version_id = profile.draft_version_id or profile.active_version_id
    version = await session.get(PolicyVersion, version_id) if version_id else None
    if version is None:
        raise Conflict("This profile has no active or draft version", code="NO_VERSION")
    units = await buyer_facade.business_unit_names(session, profile.organization_id)
    return {"checks": insights.checks(version.settings, version.rules, await insights.roles_held(session, profile.organization_id)),
            "appliesTo": [units.get(b, "Unknown unit") for b in profile.business_unit_ids] or ["The whole organisation"],
            "riskLevel": profile.risk_level, "version": "draft" if profile.draft_version_id else "active"}


@router.get("/dashboard")
async def policy_dashboard(orgId: uuid.UUID, actor: CurrentActor, session: DbSession, days: int = 30) -> dict:
    """Policy KPIs for the organisation: usage, interventions, approval speed, exceptions, spend held back."""
    from zoikorum.domains.policy import insights

    await service.require_member(session, actor, orgId)
    return await insights.dashboard(session, orgId, max(1, min(days, 365)))


@router.get("/dashboard/profiles")
async def policy_dashboard_by_profile(orgId: uuid.UUID, actor: CurrentActor, session: DbSession, days: int = 30) -> dict:
    """Per policy profile: evaluations, engagements and spend exposure per currency, exceptions, approvals and the
    approval step that holds things up."""
    from zoikorum.domains.policy import insights

    await service.require_member(session, actor, orgId)
    return await insights.by_profile(session, orgId, max(1, min(days, 365)))


@router.get("/dashboard/profiles.csv")
async def policy_dashboard_by_profile_csv(orgId: uuid.UUID, actor: CurrentActor, session: DbSession, days: int = 30):
    """The per-profile breakdown as CSV (amounts in minor units, one entry per currency, never converted)."""
    import csv
    import io

    from fastapi import Response

    from zoikorum.domains.policy import insights

    await service.require_member(session, actor, orgId)
    days = max(1, min(days, 365))
    rows = insights.csv_rows(await insights.by_profile(session, orgId, days))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=insights.CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    record_audit(session, "policy.dashboard.exported", object_type="Organization", object_id=orgId, tenant_id=orgId,
                 details={"format": "csv", "rows": len(rows), "days": days})
    return Response(buf.getvalue().encode(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="zoikorum-policy-profiles-{days}d.csv"'})


@router.get("/setup")
async def setup_status(orgId: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """Procurement setup wizard progress, and ``needsPolicySetup`` (no policy profile yet: prompt "Define your policy")."""
    return await service.setup_status(session, actor, orgId)


@router.get("/engagement-indicators")
async def engagement_indicators(orgId: uuid.UUID, actor: CurrentActor, session: DbSession,
                                contractIds: list[uuid.UUID] = Query([], max_length=100)) -> dict:
    """Live policy indicators for the organisation's engagements: risk level (with reasons), whether an exception is open
    or in force, and the progress of the current approval chain. Contracts of other organisations are left out."""
    from zoikorum.domains.policy import indicators

    await service.require_member(session, actor, orgId)
    found = await indicators.for_contracts(session, orgId, contractIds)
    return {"items": [found[c] for c in dict.fromkeys(contractIds) if c in found]}
