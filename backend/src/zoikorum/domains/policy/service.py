"""Versioned, deterministic enterprise controls. Authority is always checked live."""
from __future__ import annotations
from zoikorum.domains.admin import facade as admin_facade



import uuid
from dataclasses import asdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.identity import facade as identity
from zoikorum.domains.marketplace import facade as marketplace
from zoikorum.domains.professional import facade as professional
from zoikorum.domains.trust import facade as trust
from zoikorum.domains.policy.facade import (
    Attr, Decision, PolicyAction, PolicyContext, PolicyDecision, PolicyReason, ProfileSettings, TIER_RANK,
)
from zoikorum.domains.policy.models import (
    ApprovalRequest, ApprovalVote, ExceptionRequest, PolicyEvaluation, PolicyProfile, PolicyVersion,
)
from zoikorum.domains.policy.rules import DIMENSION_OK, matches, template
from zoikorum.domains.policy.schemas import DraftIn, ProfileIn, RuleIn, SettingsIn
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, OrgRole
from zoikorum.shared.crypto import canonical_json, sha256_hex
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, PolicyBlocked, ValidationFailed, VersionConflict
from zoikorum.shared.events import record_event
from zoikorum.shared.event_catalog import E
from zoikorum.shared.http import page_of, paginate
from zoikorum.shared.relay import cancel_timer, schedule_timer
from zoikorum.shared.uploads import file_out, find_file, read_file, store_uploads

APPROVAL_TIMER = "policy.approval_deadline"
EXCEPTION_TIMER = "policy.exception_expiry"
SETTING_NAMES = {
    "minTrustTier": "min_trust_tier", "requiredDimensions": "required_dimensions",
    "allowedJurisdictions": "allowed_jurisdictions", "allowedCurrencies": "allowed_currencies",
    "escrowRequired": "escrow_required", "partialReleaseAllowed": "partial_release_allowed",
    "acceptanceWindowDays": "acceptance_window_days", "autoAcceptAfterDays": "auto_accept_after_days",
    "signatureDeadlineDays": "signature_deadline_days", "disputeEvidenceDays": "dispute_evidence_days",
    "directResolutionBusinessDays": "direct_resolution_business_days", "challengeWindowDays": "challenge_window_days",
    "requiredClauses": "required_clauses", "stepUpForApprovals": "step_up_for_approvals",
    "autoDisputeMissedDeadline": "auto_dispute_missed_deadline", "autoDisputeRejectionCount": "auto_dispute_rejection_count",
    "autoDisputeComplianceFlag": "auto_dispute_compliance_flag",
}


async def require_member(session, actor, org_id, *roles):
    account = await identity.get_identity(session, actor.identity_id)
    have = await buyer.get_member_roles(session, org_id, actor.identity_id)
    org = await buyer.get_organization(session, org_id)
    if not account or account.status != "ACTIVE" or not have or not org or org.status != "ACTIVE":
        raise NotFound("Organization not found")
    if roles and not have.intersection(roles):
        raise Forbidden("This action requires " + " or ".join(r.replace("_", " ").title() for r in roles), code="ROLE_REQUIRED")
    return have


async def attributes_for(session, org_id, professional_id, *, amount=0, currency=None,
                         engagement_type=None, specialization=None, cost_center_id=None, extra=None):
    org = await buyer.get_organization(session, org_id)
    pro = await professional.get_professional(session, professional_id)
    if not org or not pro:
        raise NotFound("Organization or professional not found")
    snapshot = await trust.get_trust(session, pro.id)
    spec_slug = specialization or pro.primary_specialization
    specs = await marketplace.get_specializations(session, [spec_slug] if spec_slug else [])
    spec = specs.get(spec_slug)
    attrs = {
        Attr.PRO_ID: str(pro.id), Attr.PRO_TIER: snapshot.tier, Attr.PRO_DIMENSIONS: snapshot.dimensions,
        Attr.PRO_JURISDICTIONS: list(pro.jurisdictions_served), Attr.PRO_LICENSED: list(pro.licensed_jurisdictions),
        Attr.PRO_RESTRICTED: pro.status == "SUSPENDED" or snapshot.dimensions.get("restrictions") == "FLAGGED" or bool(
            set(await admin_facade.active_restrictions(session, "PROFESSIONAL", pro.id)).intersection(
                {"ENGAGEMENT_SUSPENSION", "CREDENTIAL_ENFORCEMENT", "VERIFICATION_RESET", "OFFBOARD", "SUSPEND_ACCOUNT"})) or bool(
            set(await admin_facade.active_restrictions(session, "ORGANIZATION", org_id)).intersection({"ENGAGEMENT_SUSPENSION"})) or bool(
            set(await admin_facade.active_restrictions(session, "IDENTITY", pro.identity_id)).intersection({"SUSPEND_ACCOUNT", "OFFBOARD"})),
        Attr.BUYER_COUNTRY: org.country, Attr.BUYER_ORG_TYPE: org.org_type,
        Attr.ENGAGEMENT_VALUE_MINOR: amount, Attr.AMOUNT_MINOR: amount,
        Attr.ENGAGEMENT_CURRENCY: currency, Attr.ENGAGEMENT_TYPE: engagement_type,
        Attr.ENGAGEMENT_CATEGORY: spec.category_slug if spec else pro.primary_category,
        Attr.ENGAGEMENT_SPECIALIZATION: spec_slug, Attr.ENGAGEMENT_REGULATED: bool(spec and spec.regulated),
        Attr.ENGAGEMENT_CROSS_BORDER: org.country != pro.country,
    }
    if cost_center_id:
        center = await buyer.get_cost_center(session, cost_center_id)
        if not center or center.organization_id != org_id:
            raise NotFound("Cost center not found in this organization")
        attrs[Attr.COST_CENTER_ID] = str(center.id)
    return {**attrs, **(extra or {})}


async def effective_version(session, org_id, pinned=None, attributes=None):
    if (attributes or {}).get("policy.platformDefaultPinned"):
        return None, None
    if pinned:
        version = await session.get(PolicyVersion, pinned)
        profile = await session.get(PolicyProfile, version.profile_id) if version else None
        if not profile or profile.organization_id != org_id or version.status != "ACTIVE":
            raise NotFound("Applied policy version not found in this organization")
        return profile, version
    if org_id is None:
        return None, None
    unit_id = None
    center_id = (attributes or {}).get(Attr.COST_CENTER_ID)
    if center_id:
        center = await buyer.get_cost_center(session, uuid.UUID(str(center_id)))
        if not center or center.organization_id != org_id:
            raise NotFound("Cost center not found in this organization")
        unit_id = str(center.business_unit_id) if center.business_unit_id else None
    profiles = list((await session.scalars(select(PolicyProfile).where(
        PolicyProfile.organization_id == org_id, PolicyProfile.active_version_id.is_not(None)
    ))).all())
    scoped = [p for p in profiles if unit_id and unit_id in p.business_unit_ids]
    default = [p for p in profiles if not p.business_unit_ids]
    selected = scoped or default
    if len(selected) > 1:
        raise Conflict("Policy scopes overlap; an organization admin must resolve them", code="POLICY_SCOPE_CONFLICT")
    if not selected:
        return None, None
    profile = selected[0]
    return profile, await session.get(PolicyVersion, profile.active_version_id)


def label(profile, version):
    return f"{profile.name}@v{version.number}" if profile and version else "platform-default@1"


# Deadline settings a profile may leave empty: one source of truth, the platform configuration.
DEADLINE_SETTINGS = ("acceptanceWindowDays", "signatureDeadlineDays", "disputeEvidenceDays", "directResolutionBusinessDays",
                     "challengeWindowDays")


def platform_deadlines() -> dict:
    s = get_settings()
    return {"acceptance_window_days": s.acceptance_window_days, "signature_deadline_days": s.signature_deadline_days,
            "dispute_evidence_days": s.dispute_evidence_days,
            "direct_resolution_business_days": s.dispute_direct_resolution_business_days,
            "challenge_window_days": s.dispute_challenge_window_days}


def stored_settings(settings) -> dict:
    """Profile settings as saved: deadlines left empty are not saved, so they keep following the platform defaults."""
    return {k: v for k, v in settings.model_dump().items() if not (k in DEADLINE_SETTINGS and v is None)}


async def settings_for_org(session, org_id, pinned=None):
    profile, version = await effective_version(session, org_id, pinned)
    if not version:
        return ProfileSettings(None, None, "platform-default@1", **platform_deadlines())
    values = {SETTING_NAMES[k]: tuple(v) if isinstance(v, list) else v for k, v in version.settings.items()
              if k in SETTING_NAMES and v is not None}
    return ProfileSettings(profile.id, version.id, label(profile, version), **{**platform_deadlines(), **values})


async def profile_out(session, profile):
    versions = list((await session.scalars(select(PolicyVersion).where(
        PolicyVersion.profile_id == profile.id).order_by(PolicyVersion.number.desc()))).all())
    def output(v):
        return {"id": v.id, "number": v.number, "status": v.status, "label": label(profile, v),
                "settings": v.settings, "rules": v.rules, "activatedAt": v.activated_at,
                "activatedBy": v.activated_by, "createdAt": v.created_at}
    by_id = {v.id: output(v) for v in versions}
    return {"id": profile.id, "orgId": profile.organization_id, "name": profile.name,
            "description": profile.description, "riskLevel": profile.risk_level, "businessUnitIds": profile.business_unit_ids,
            "status": "ACTIVE" if profile.active_version_id else "DRAFT" if profile.draft_version_id else "RETIRED",
            "activeVersion": by_id.get(profile.active_version_id), "draftVersion": by_id.get(profile.draft_version_id),
            "activeVersionId": profile.active_version_id, "draftVersionId": profile.draft_version_id,
            "versions": list(by_id.values()), "version": profile.version, "createdAt": profile.created_at}


async def get_profile(session, actor, profile_id, *, lock=False):
    profile = await session.get(PolicyProfile, profile_id, with_for_update=lock)
    if not profile:
        raise NotFound("Policy profile not found")
    await require_member(session, actor, profile.organization_id)
    return profile


async def create_profile(session, actor, body: ProfileIn):
    await require_member(session, actor, body.orgId, OrgRole.ORG_ADMIN)
    valid_units = await buyer.list_business_unit_ids(session, body.orgId)
    if not set(body.businessUnitIds).issubset(valid_units):
        raise NotFound("Business unit not found in this organization")
    default_settings, default_rules = template(body.template)
    settings = body.settings or SettingsIn(**default_settings)
    rules = body.rules if body.rules is not None else [RuleIn(**r) for r in default_rules]
    if len({r.id for r in rules}) != len(rules):
        raise ValidationFailed("Rule IDs must be unique")
    profile = PolicyProfile(organization_id=body.orgId, name=body.name.strip(), description=body.description.strip(),
        risk_level=body.riskLevel, business_unit_ids=sorted(set(str(x) for x in body.businessUnitIds)), created_at=clock.now())
    session.add(profile)
    await session.flush()
    version = PolicyVersion(profile_id=profile.id, number=1, settings=stored_settings(settings),
        rules=[r.model_dump(exclude_none=True) for r in rules], created_by=actor.identity_id, created_at=clock.now())
    session.add(version)
    await session.flush()
    profile.draft_version_id = version.id
    record_event(session, E.POLICY_CREATED, aggregate_type="PolicyProfile", aggregate_id=profile.id,
        tenant_id=profile.organization_id, payload={"organizationId": profile.organization_id, "profileId": profile.id,
            "name": profile.name, "versionId": version.id})
    await session.flush()
    return await profile_out(session, profile)


async def update_draft(session, actor, profile_id, body: DraftIn):
    profile = await get_profile(session, actor, profile_id, lock=True)
    await require_member(session, actor, profile.organization_id, OrgRole.ORG_ADMIN)
    if body.version != profile.version:
        raise VersionConflict()
    if not profile.draft_version_id:
        raise Conflict("Active policy versions are immutable; create a new draft version", code="POLICY_VERSION_IMMUTABLE")
    draft = await session.get(PolicyVersion, profile.draft_version_id, with_for_update=True)
    if draft.status != "DRAFT":
        raise Conflict("Only draft policy versions can be edited")
    draft.settings, draft.rules = stored_settings(body.settings), [r.model_dump(exclude_none=True) for r in body.rules]
    profile.updated_at = clock.now()
    record_event(session, E.POLICY_DRAFT_UPDATED, aggregate_type="PolicyProfile", aggregate_id=profile.id,
        tenant_id=profile.organization_id, payload={"organizationId": profile.organization_id, "profileId": profile.id,
            "versionId": draft.id})
    await session.flush()
    return await profile_out(session, profile)


async def new_draft(session, actor, profile_id):
    profile = await get_profile(session, actor, profile_id, lock=True)
    await require_member(session, actor, profile.organization_id, OrgRole.ORG_ADMIN)
    if profile.draft_version_id:
        raise Conflict("This profile already has a draft", code="POLICY_DRAFT_EXISTS")
    old = await session.get(PolicyVersion, profile.active_version_id) if profile.active_version_id else None
    if not old:
        old = await session.scalar(select(PolicyVersion).where(PolicyVersion.profile_id == profile.id).order_by(PolicyVersion.number.desc()))
    number = (await session.scalar(select(func.max(PolicyVersion.number)).where(PolicyVersion.profile_id == profile.id)) or 0) + 1
    draft = PolicyVersion(profile_id=profile.id, number=number, settings=dict(old.settings), rules=list(old.rules),
        created_by=actor.identity_id, created_at=clock.now())
    session.add(draft)
    await session.flush()
    profile.draft_version_id = draft.id
    record_event(session, E.POLICY_DRAFT_UPDATED, aggregate_type="PolicyProfile", aggregate_id=profile.id,
        tenant_id=profile.organization_id, payload={"profileId": profile.id, "versionId": draft.id, "number": number})
    await session.flush()
    return await profile_out(session, profile)


async def activate(session, actor, profile_id):
    profile = await get_profile(session, actor, profile_id)
    await require_member(session, actor, profile.organization_id, OrgRole.ORG_ADMIN)
    actor.require_step_up()
    from sqlalchemy import text
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": profile.organization_id.int % (2**63 - 1)})
    profile = await get_profile(session, actor, profile_id, lock=True)
    if not profile.draft_version_id:
        raise Conflict("There is no draft version to activate")
    draft = await session.get(PolicyVersion, profile.draft_version_id, with_for_update=True)
    SettingsIn(**draft.settings)
    for raw in draft.rules:
        RuleIn(**raw)
    # Serialize activation per organization, including competing business-unit profiles.
    others = (await session.scalars(select(PolicyProfile).where(
        PolicyProfile.organization_id == profile.organization_id, PolicyProfile.id != profile.id,
        PolicyProfile.active_version_id.is_not(None)).with_for_update())).all()
    for other in others:
        if profile.business_unit_ids and set(profile.business_unit_ids).intersection(other.business_unit_ids):
            raise Conflict("Another active policy covers the same business unit", code="POLICY_SCOPE_CONFLICT")
        if not profile.business_unit_ids and not other.business_unit_ids:
            other.active_version_id = None
    draft.status, draft.activated_at, draft.activated_by = "ACTIVE", clock.now(), actor.identity_id
    profile.active_version_id, profile.draft_version_id = draft.id, None
    record_event(session, E.POLICY_VERSION_ACTIVATED, aggregate_type="PolicyProfile", aggregate_id=profile.id,
        tenant_id=profile.organization_id, policy_version=label(profile, draft),
        payload={"organizationId": profile.organization_id, "profileId": profile.id, "versionId": draft.id,
            "policyVersionLabel": label(profile, draft), "businessUnitIds": profile.business_unit_ids})
    await session.flush()
    return await profile_out(session, profile)


async def list_profiles(session, actor, org_id, cursor=None, limit=30):
    await require_member(session, actor, org_id)
    stmt, lim = paginate(select(PolicyProfile).where(PolicyProfile.organization_id == org_id), PolicyProfile, cursor, limit)
    rows = list((await session.scalars(stmt)).all())
    outputs = {p.id: await profile_out(session, p) for p in rows[:lim]}
    return page_of(rows, lim, lambda p: outputs[p.id])


def context_hash(ctx, version_id):
    # Commercial facts bind authority; live trust facts are always evaluated again.
    facts = {k: v for k, v in ctx.attributes.items() if not k.startswith("professional.")}
    return sha256_hex(canonical_json({"org": ctx.org_id, "subject": ctx.subject_id,
        "type": ctx.subject_type, "action": ctx.action, "actor": ctx.actor_identity_id,
        "version": version_id, "facts": facts}))


def reason_out(reason):
    return {"code": reason.code, "message": reason.message,
        "policy_id": str(reason.policy_id) if reason.policy_id else None, "rule_id": reason.rule_id}


async def valid_votes(session, request):
    votes = (await session.scalars(select(ApprovalVote).where(
        ApprovalVote.request_id == request.id, ApprovalVote.decision == "GRANT"))).all()
    valid = []
    for vote in votes:
        account = await identity.get_identity(session, vote.identity_id)
        roles = await buyer.get_member_roles(session, request.organization_id, vote.identity_id)
        limit = await buyer.get_member_spend_limit(session, request.organization_id, vote.identity_id)
        amount = request.attributes.get(Attr.AMOUNT_MINOR, request.attributes.get(Attr.ENGAGEMENT_VALUE_MINOR, 0))
        currency = request.attributes.get(Attr.ENGAGEMENT_CURRENCY)
        authorized = (limit is None and OrgRole.ORG_ADMIN in roles) or (
            limit is not None and limit.currency == currency and amount <= limit.minor)
        if account and await identity.account_is_active(session, vote.identity_id) and vote.authority_role in roles and authorized:
            valid.append(vote)
    return valid


def steps_satisfied(workflows, votes):
    return all(sum(v.step_id == step["id"] for v in votes) >= step["count"]
        for workflow in workflows for step in workflow["steps"])


async def evaluate(session, ctx, *, dry_run=False, preview_profile_id=None):
    if ctx.action not in PolicyAction.ALL:
        raise ValidationFailed("Unknown policy action")
    profile, version = await effective_version(session, ctx.org_id, ctx.pinned_policy_version_id, ctx.attributes)
    if preview_profile_id:
        if not dry_run:
            raise ValidationFailed("Draft policies can only be used in a dry run")
        profile = await session.get(PolicyProfile, preview_profile_id)
        if not profile or profile.organization_id != ctx.org_id:
            raise NotFound("Preview policy profile not found")
        version = await session.get(PolicyVersion, profile.draft_version_id or profile.active_version_id)
        if not version:
            raise Conflict("The preview profile has no draft or active version")
    settings = version.settings if version else {}
    findings = []
    def fail(decision, code, message, rule=None):
        findings.append((decision, PolicyReason(code, message, profile.id if profile else None, rule)))
    attrs = ctx.attributes
    if attrs.get(Attr.PRO_RESTRICTED):
        fail(Decision.BLOCK, "PROFESSIONAL_RESTRICTED", "This professional is currently restricted")
    if ctx.action in (PolicyAction.PROPOSAL_SUBMIT, PolicyAction.PROPOSAL_ACCEPT) and attrs.get(Attr.PRO_TIER) == "C":
        fail(Decision.BLOCK, "MINIMUM_PLATFORM_TIER", "Tier C professionals cannot submit or receive accepted proposals")
    if version:
        minimum = settings.get("minTrustTier", "B")
        if TIER_RANK.get(attrs.get(Attr.PRO_TIER), -1) < TIER_RANK[minimum]:
            fail(Decision.BLOCK, "POLICY_BLOCKED_MINIMUM_TRUST_TIER", f"This policy requires Trust Tier {minimum}")
        dimensions = attrs.get(Attr.PRO_DIMENSIONS, {})
        for dimension in settings.get("requiredDimensions", ["identity"]):
            if dimensions.get(dimension) not in DIMENSION_OK[dimension]:
                fail(Decision.BLOCK, "POLICY_BLOCKED_TRUST_DIMENSION", f"The {dimension} requirement is not satisfied")
        allowed = settings.get("allowedJurisdictions")
        if allowed and attrs.get(Attr.BUYER_COUNTRY) not in allowed:
            fail(Decision.BLOCK, "POLICY_BLOCKED_JURISDICTION", "The buyer country is outside the policy's allowed jurisdictions")
        currencies = settings.get("allowedCurrencies")
        if currencies and attrs.get(Attr.ENGAGEMENT_CURRENCY) not in currencies:
            fail(Decision.BLOCK, "POLICY_BLOCKED_CURRENCY", "This currency is not permitted by the policy")
        for rule in version.rules:
            if ctx.action in rule["appliesTo"] and matches(rule["condition"], attrs):
                fail(rule["decision"], rule["reasonCode"], rule["message"], rule["id"])
    decision = max((f[0] for f in findings), key=lambda d: Decision.SEVERITY[d], default=Decision.ALLOW)
    digest = context_hash(ctx, version.id if version else None)
    approval_id = exception_id = None
    if not dry_run and decision != Decision.BLOCK:
        # An exception waives exception rules only, never hard blocks or independent approvals.
        if decision == Decision.REQUIRE_EXCEPTION and ctx.org_id:
            candidates = (await session.scalars(select(ExceptionRequest).where(
                ExceptionRequest.organization_id == ctx.org_id, ExceptionRequest.context_hash == digest,
                ExceptionRequest.status == "GRANTED", ExceptionRequest.expires_at > clock.now()))).all()
            for granted in candidates:
                roles = await buyer.get_member_roles(session, ctx.org_id, granted.decided_by)
                account = await identity.get_identity(session, granted.decided_by)
                if OrgRole.EXCEPTION_AUTHORITY in roles and account and await identity.account_is_active(session, granted.decided_by):
                    exception_id = granted.id
                    decision = max((d for d, _ in findings if d != Decision.REQUIRE_EXCEPTION),
                        key=lambda d: Decision.SEVERITY[d], default=Decision.ALLOW)
                    break
        if decision == Decision.REQUIRE_APPROVAL and ctx.org_id:
            request_key = digest
            request = await session.scalar(select(ApprovalRequest).where(ApprovalRequest.request_key == request_key))
            if request and request.status == "GRANTED" and steps_satisfied(request.workflows, await valid_votes(session, request)):
                decision, approval_id = Decision.ALLOW, request.id
            elif request and request.status in ("DENIED", "EXPIRED", "CANCELLED", "GRANTED"):
                fail(Decision.BLOCK, "APPROVAL_NOT_VALID", "Approval was denied, expired, or its authority was revoked; request a new commercial version")
                decision = Decision.BLOCK
            else:
                if request is None:
                    workflows = []
                    for rule in version.rules:
                        if rule["decision"] == Decision.REQUIRE_APPROVAL and ctx.action in rule["appliesTo"] and matches(rule["condition"], attrs):
                            route = rule["approval"]
                            workflows.append({**route, "steps": [{**step, "id": f'{rule["id"]}:{i}'} for i, step in enumerate(route["steps"])]})
                    request_id = uuid.uuid4()
                    timeout = min(w["timeoutHours"] for w in workflows)
                    values = dict(id=request_id, organization_id=ctx.org_id, policy_version_id=version.id,
                        subject_type=ctx.subject_type, subject_id=ctx.subject_id, action=ctx.action,
                        requester_identity_id=ctx.actor_identity_id, context_hash=digest, request_key=request_key,
                        attributes=attrs, workflows=workflows, reasons=[reason_out(r) for _, r in findings], version=1,
                        deadline=clock.now() + timedelta(hours=timeout), escalation_role=workflows[0]["escalationRole"],
                        step_up_required=settings.get("stepUpForApprovals", True), status="PENDING")
                    await session.execute(insert(ApprovalRequest).values(**values).on_conflict_do_nothing(index_elements=["request_key"]))
                    request = await session.scalar(select(ApprovalRequest).where(ApprovalRequest.request_key == request_key))
                    if request.id == request_id:
                        await schedule_timer(session, APPROVAL_TIMER, str(request.id), request.deadline)
                        record_event(session, E.APPROVAL_REQUIRED, aggregate_type="ApprovalRequest", aggregate_id=request.id,
                            tenant_id=ctx.org_id, policy_version=label(profile, version), payload={
                                "organizationId": ctx.org_id, "requesterIdentityId": ctx.actor_identity_id,
                                "subjectType": ctx.subject_type, "subjectId": ctx.subject_id, "action": ctx.action,
                                "approvalRequestId": request.id, "deadline": request.deadline})
                approval_id = request.id
    evaluation = PolicyEvaluation(id=uuid.uuid4(), organization_id=ctx.org_id,
        policy_profile_id=profile.id if profile else None, policy_version_id=version.id if version else None,
        policy_version_label=label(profile, version), subject_type=ctx.subject_type, subject_id=ctx.subject_id,
        action=ctx.action, actor_identity_id=ctx.actor_identity_id, attributes=attrs, context_hash=digest,
        decision=decision, reasons=[reason_out(r) for _, r in findings], dry_run=dry_run, created_at=clock.now())
    session.add(evaluation)
    record_event(session, E.POLICY_EVALUATED, aggregate_type="PolicyEvaluation", aggregate_id=evaluation.id,
        tenant_id=ctx.org_id, policy_version=evaluation.policy_version_label, payload={
            "subjectType": ctx.subject_type, "subjectId": ctx.subject_id, "action": ctx.action,
            "decision": decision, "reasons": evaluation.reasons, "dryRun": dry_run,
            "policyVersionId": evaluation.policy_version_id, "contextHash": digest})
    if decision == Decision.BLOCK and not dry_run:
        record_event(session, E.POLICY_VIOLATION_DETECTED, aggregate_type="PolicyEvaluation", aggregate_id=evaluation.id,
            tenant_id=ctx.org_id, policy_version=evaluation.policy_version_label,
            payload={"subjectType": ctx.subject_type, "subjectId": ctx.subject_id,
                "action": ctx.action, "reasons": evaluation.reasons, "organizationId": ctx.org_id})
    await session.flush()
    if not session.info.get("policy_audit_replay"):
        async def audit_after_rollback(audit_session):
            audit_session.info["policy_audit_replay"] = True
            await evaluate(audit_session, ctx, dry_run=dry_run, preview_profile_id=preview_profile_id)
        session.info.setdefault("after_rollback_audit", []).append(audit_after_rollback)
    return PolicyDecision(decision, tuple(r for _, r in findings), evaluation.policy_profile_id,
        evaluation.policy_version_id, evaluation.policy_version_label, evaluation.id, approval_id, exception_id)


async def approval_out(session, request):
    votes = (await session.scalars(select(ApprovalVote).where(ApprovalVote.request_id == request.id).order_by(ApprovalVote.created_at))).all()
    valid_ids = {v.id for v in await valid_votes(session, request)}
    return {"id": request.id, "orgId": request.organization_id, "subjectType": request.subject_type,
        "subjectId": request.subject_id, "action": request.action, "status": request.status,
        "requesterIdentityId": request.requester_identity_id, "policyVersionId": request.policy_version_id,
        "workflows": request.workflows, "reasons": request.reasons, "deadline": request.deadline,
        "escalationCount": request.escalation_count, "createdAt": request.created_at,
        "votes": [{"id": v.id, "stepId": v.step_id, "identityId": v.identity_id,
            "decision": v.decision, "role": v.authority_role, "reason": v.reason,
            "valid": v.id in valid_ids, "createdAt": v.created_at} for v in votes]}


async def decide_approval(session, actor, request_id, body):
    request = await session.get(ApprovalRequest, request_id, with_for_update=True)
    if not request:
        raise NotFound("Approval request not found")
    roles = await require_member(session, actor, request.organization_id)
    if request.requester_identity_id == actor.identity_id:
        raise Forbidden("Requesters cannot approve their own actions", code="SEPARATION_OF_DUTIES")
    if request.step_up_required:
        actor.require_step_up()
    if request.status != "PENDING" or request.deadline <= clock.now():
        raise Conflict("This approval is no longer pending")
    limit = await buyer.get_member_spend_limit(session, request.organization_id, actor.identity_id)
    amount = request.attributes.get(Attr.AMOUNT_MINOR, request.attributes.get(Attr.ENGAGEMENT_VALUE_MINOR, 0))
    currency = request.attributes.get(Attr.ENGAGEMENT_CURRENCY)
    if (limit is None and OrgRole.ORG_ADMIN not in roles) or (limit is not None and (limit.currency != currency or amount > limit.minor)):
        raise Forbidden("This action exceeds your spend authority", code="SPEND_LIMIT_EXCEEDED")
    votes = await valid_votes(session, request)
    previous_vote = await session.scalar(select(ApprovalVote.id).where(ApprovalVote.request_id == request.id,
        ApprovalVote.identity_id == actor.identity_id))
    if previous_vote:
        raise Conflict("Each approver can contribute one independent decision")
    candidates = []
    for workflow in request.workflows:
        for step in workflow["steps"]:
            if sum(v.step_id == step["id"] for v in votes) < step["count"]:
                if step["role"] in roles and (body.stepId is None or body.stepId == step["id"]):
                    candidates.append(step)
                if workflow["mode"] == "SEQUENTIAL":
                    break
    if not candidates:
        raise Forbidden("You do not hold the authority required for an available approval step")
    step = candidates[0]
    vote = ApprovalVote(id=uuid.uuid4(), request_id=request.id, step_id=step["id"],
        identity_id=actor.identity_id, authority_role=step["role"], decision=body.decision,
        reason=body.reason, created_at=clock.now())
    session.add(vote)
    if body.decision == "DENY":
        request.status = "DENIED"
    elif steps_satisfied(request.workflows, [*votes, vote]):
        request.status = "GRANTED"
    if request.status != "PENDING":
        await cancel_timer(session, APPROVAL_TIMER, str(request.id))
        await cancel_timer(session, APPROVAL_TIMER, f"{request.id}:1")
        record_event(session, E.APPROVAL_GRANTED if request.status == "GRANTED" else E.APPROVAL_DENIED,
            aggregate_type="ApprovalRequest", aggregate_id=request.id, tenant_id=request.organization_id,
            payload={"organizationId": request.organization_id, "approvalRequestId": request.id,
                "subjectType": request.subject_type, "subjectId": request.subject_id, "action": request.action,
                "requesterIdentityId": request.requester_identity_id, "contextHash": request.context_hash})
    await session.flush()
    return await approval_out(session, request)


async def approval_deadline(session, key):
    request = await session.get(ApprovalRequest, uuid.UUID(key.split(":")[0]), with_for_update=True)
    if not request or request.status != "PENDING" or request.deadline > clock.now():
        return
    if not request.escalation_count:
        request.escalation_count = 1
        request.deadline = clock.now() + timedelta(hours=48)
        await schedule_timer(session, APPROVAL_TIMER, f"{request.id}:1", request.deadline)
        event = E.APPROVAL_ESCALATED
    else:
        request.status = "EXPIRED"
        event = E.APPROVAL_EXPIRED
    record_event(session, event, aggregate_type="ApprovalRequest", aggregate_id=request.id,
        tenant_id=request.organization_id, payload={"organizationId": request.organization_id,
            "approvalRequestId": request.id, "subjectId": request.subject_id, "subjectType": request.subject_type,
            "action": request.action, "escalationRole": request.escalation_role, "deadline": request.deadline})


def exception_out(request):
    return {"id": request.id, "orgId": request.organization_id, "subjectType": request.subject_type,
        "subjectId": request.subject_id, "action": request.action, "policyVersionId": request.policy_version_id,
        "requesterIdentityId": request.requester_identity_id, "justification": request.justification,
        "documents": [file_out(d).model_dump() for d in request.documents], "status": request.status,
        "expiresAt": request.expires_at, "decidedBy": request.decided_by,
        "decisionReason": request.decision_reason, "decidedAt": request.decided_at, "createdAt": request.created_at}


async def create_exception(session, actor, body):
    await require_member(session, actor, body.orgId)
    if body.expiresAt.tzinfo is None or not clock.now() < body.expiresAt <= clock.now() + timedelta(days=90):
        raise ValidationFailed("Exception expiry must be within the next 90 days")
    # Bind to a real, recorded commercial evaluation, never client-supplied facts.
    evaluation = await session.scalar(select(PolicyEvaluation).where(
        PolicyEvaluation.organization_id == body.orgId, PolicyEvaluation.subject_type == body.subjectType,
        PolicyEvaluation.subject_id == body.subjectId, PolicyEvaluation.action == body.action,
        PolicyEvaluation.actor_identity_id == actor.identity_id, PolicyEvaluation.dry_run.is_(False)
        ).order_by(PolicyEvaluation.created_at.desc()).limit(1))
    if not evaluation or evaluation.decision != Decision.REQUIRE_EXCEPTION:
        raise Conflict("A current commercial evaluation requiring an exception is needed")
    existing = await session.scalar(select(ExceptionRequest).where(ExceptionRequest.context_hash == evaluation.context_hash,
        ExceptionRequest.status.in_(["PENDING", "GRANTED"]), ExceptionRequest.expires_at > clock.now()))
    if existing:
        return exception_out(existing)
    request_id = uuid.uuid4()
    request = ExceptionRequest(id=request_id, organization_id=body.orgId, policy_version_id=evaluation.policy_version_id,
        subject_type=body.subjectType, subject_id=body.subjectId, action=body.action,
        context_hash=evaluation.context_hash, requester_identity_id=actor.identity_id,
        justification=body.justification, documents=store_uploads(f"policy/exceptions/{request_id}", body.documents),
        expires_at=body.expiresAt, status="PENDING", created_at=clock.now())
    session.add(request)
    await schedule_timer(session, EXCEPTION_TIMER, str(request.id), request.expires_at)
    record_event(session, E.EXCEPTION_REQUESTED, aggregate_type="ExceptionRequest", aggregate_id=request.id,
        tenant_id=body.orgId, payload={"organizationId": body.orgId, "exceptionRequestId": request.id,
            "requesterIdentityId": actor.identity_id, "subjectId": request.subject_id, "action": request.action,
            "expiresAt": request.expires_at})
    await session.flush()
    return exception_out(request)


async def decide_exception(session, actor, request_id, body):
    request = await session.get(ExceptionRequest, request_id, with_for_update=True)
    if not request:
        raise NotFound("Exception request not found")
    await require_member(session, actor, request.organization_id, OrgRole.EXCEPTION_AUTHORITY)
    actor.require_step_up()
    if request.requester_identity_id == actor.identity_id:
        raise Forbidden("Requesters cannot decide their own exceptions", code="SEPARATION_OF_DUTIES")
    if request.status != "PENDING" or request.expires_at <= clock.now():
        raise Conflict("This exception is no longer pending")
    request.status = "GRANTED" if body.decision == "GRANT" else "DENIED"
    request.decided_by, request.decided_at, request.decision_reason = actor.identity_id, clock.now(), body.reason
    record_event(session, E.EXCEPTION_GRANTED if request.status == "GRANTED" else E.EXCEPTION_DENIED,
        aggregate_type="ExceptionRequest", aggregate_id=request.id, tenant_id=request.organization_id,
        payload={"organizationId": request.organization_id, "exceptionRequestId": request.id,
            "requesterIdentityId": request.requester_identity_id, "subjectType": request.subject_type,
            "subjectId": request.subject_id, "action": request.action, "expiresAt": request.expires_at})
    await session.flush()
    return exception_out(request)


async def exception_expiry(session, key):
    request = await session.get(ExceptionRequest, uuid.UUID(key), with_for_update=True)
    if not request or request.status not in ("PENDING", "GRANTED") or request.expires_at > clock.now():
        return
    request.status = "EXPIRED"
    record_event(session, E.EXCEPTION_EXPIRED, aggregate_type="ExceptionRequest", aggregate_id=request.id,
        tenant_id=request.organization_id, payload={"organizationId": request.organization_id,
            "exceptionRequestId": request.id, "subjectId": request.subject_id, "action": request.action})
