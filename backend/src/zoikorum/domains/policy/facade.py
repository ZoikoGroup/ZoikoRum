"""Policy facade - CONTRACT. Signatures and DTOs are fixed; implement bodies.

Policy decisions: ALLOW < REQUIRE_APPROVAL < REQUIRE_EXCEPTION < BLOCK.
Most restrictive wins (Handbook 10.3). Every evaluation is persisted and audited.

How callers use it (e.g. proposal acceptance):

    decision = await policy.evaluate(session, PolicyContext(
        org_id=req.organization_id, action=PolicyAction.PROPOSAL_ACCEPT,
        subject_type="Proposal", subject_id=proposal.id,
        actor_identity_id=actor.identity_id,
        attributes={"engagement.valueMinor": 6_000_00, "engagement.currency": "USD", ...}))
    if decision.decision == Decision.BLOCK: raise PolicyBlocked(...)
    if decision.decision == Decision.REQUIRE_APPROVAL:
        # an ApprovalRequest now exists (decision.approval_request_id) and
        # APPROVAL_REQUIRED was emitted. Park the aggregate in a pending state and
        # finish when APPROVAL_GRANTED arrives with matching subjectType/subjectId/action.

Re-evaluating the same (subject, action) after its approval was GRANTED returns
ALLOW (the approval satisfies the rule). Same for a granted, unexpired exception.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class Decision:
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    REQUIRE_EXCEPTION = "REQUIRE_EXCEPTION"
    BLOCK = "BLOCK"
    SEVERITY = {ALLOW: 0, REQUIRE_APPROVAL: 1, REQUIRE_EXCEPTION: 2, BLOCK: 3}


class PolicyAction:
    """Actions that domains ask the policy engine about."""

    ENGAGEMENT_ELIGIBILITY = "ENGAGEMENT_ELIGIBILITY"  # buyer -> professional request allowed?
    PROPOSAL_SUBMIT = "PROPOSAL_SUBMIT"  # professional may submit to this buyer?
    PROPOSAL_ACCEPT = "PROPOSAL_ACCEPT"
    CONTRACT_SIGN = "CONTRACT_SIGN"
    CHANGE_ORDER_APPROVE = "CHANGE_ORDER_APPROVE"
    ESCROW_FUND = "ESCROW_FUND"
    MILESTONE_ACCEPT = "MILESTONE_ACCEPT"
    ESCROW_RELEASE = "ESCROW_RELEASE"
    ALL = (ENGAGEMENT_ELIGIBILITY, PROPOSAL_SUBMIT, PROPOSAL_ACCEPT, CONTRACT_SIGN,
           CHANGE_ORDER_APPROVE, ESCROW_FUND, MILESTONE_ACCEPT, ESCROW_RELEASE)


class Attr:
    """Standard attribute keys for PolicyContext.attributes (rules reference these)."""

    ENGAGEMENT_VALUE_MINOR = "engagement.valueMinor"
    ENGAGEMENT_CURRENCY = "engagement.currency"
    ENGAGEMENT_TYPE = "engagement.type"  # ADVISORY|PROJECT|RETAINER|FRACTIONAL
    ENGAGEMENT_CATEGORY = "engagement.category"  # taxonomy category slug
    ENGAGEMENT_SPECIALIZATION = "engagement.specialization"
    ENGAGEMENT_CROSS_BORDER = "engagement.crossBorder"  # bool
    ENGAGEMENT_REGULATED = "engagement.regulated"  # bool (taxonomy flag)
    PRO_ID = "professional.id"
    PRO_TIER = "professional.tier"  # "A"|"B"|"C"
    PRO_DIMENSIONS = "professional.dimensions"  # dict dimension->status (trust facade)
    PRO_JURISDICTIONS = "professional.jurisdictions"  # list ISO-2 served
    PRO_LICENSED = "professional.licensedJurisdictions"
    PRO_RESTRICTED = "professional.restricted"  # bool, active enforcement restriction
    BUYER_COUNTRY = "buyer.country"
    BUYER_ORG_TYPE = "buyer.orgType"
    COST_CENTER_ID = "buyer.costCenterId"
    AMOUNT_MINOR = "action.amountMinor"  # amount this specific action moves (release, milestone)


TIER_RANK = {"C": 0, "B": 1, "A": 2}


@dataclass(frozen=True)
class PolicyContext:
    org_id: uuid.UUID | None
    action: str
    subject_type: str
    subject_id: uuid.UUID
    actor_identity_id: uuid.UUID | None
    attributes: dict[str, Any] = field(default_factory=dict)
    pinned_policy_version_id: uuid.UUID | None = None  # engagements keep the version they started with


@dataclass(frozen=True)
class PolicyReason:
    code: str  # e.g. POLICY_BLOCKED_MINIMUM_TRUST_TIER
    message: str  # plain language, shown to users ("Why?")
    policy_id: uuid.UUID | None = None
    rule_id: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    reasons: tuple[PolicyReason, ...]
    policy_profile_id: uuid.UUID | None
    policy_version_id: uuid.UUID | None
    policy_version_label: str  # e.g. "platform-default@1" or "<profile name>@v4" - goes into audit
    evaluation_id: uuid.UUID
    approval_request_id: uuid.UUID | None = None
    exception_request_id: uuid.UUID | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == Decision.ALLOW

    @property
    def first_reason(self) -> PolicyReason | None:
        return self.reasons[0] if self.reasons else None


@dataclass(frozen=True)
class ProfileSettings:
    """Structured settings of the effective policy profile for an org."""

    policy_profile_id: uuid.UUID | None
    policy_version_id: uuid.UUID | None
    policy_version_label: str
    min_trust_tier: str = "B"
    required_dimensions: tuple[str, ...] = ("identity",)
    allowed_jurisdictions: tuple[str, ...] | None = None
    escrow_required: bool = True
    partial_release_allowed: bool = True
    acceptance_window_days: int = 14
    auto_accept_after_days: int | None = None  # None => never auto-accept
    signature_deadline_days: int = 3
    dispute_evidence_days: int = 7
    direct_resolution_business_days: int = 5
    challenge_window_days: int = 14  # accepted milestones may be disputed within this window
    required_clauses: tuple[str, ...] = ("CONFIDENTIALITY", "IP_OWNERSHIP", "TERMINATION", "GOVERNING_LAW")
    allowed_currencies: tuple[str, ...] | None = None
    step_up_for_approvals: bool = True


@dataclass(frozen=True)
class ApprovalSummary:
    id: uuid.UUID
    org_id: uuid.UUID | None
    subject_type: str
    subject_id: uuid.UUID
    action: str
    status: str  # PENDING|GRANTED|DENIED|EXPIRED|CANCELLED


async def evaluate(session: AsyncSession, ctx: PolicyContext) -> PolicyDecision:
    from zoikorum.domains.policy import service
    return await service.evaluate(session, ctx)


async def get_settings_for_org(
    session: AsyncSession, org_id: uuid.UUID | None, pinned_version_id: uuid.UUID | None = None
) -> ProfileSettings:
    """Effective settings; platform defaults when the org has no active profile."""
    from zoikorum.domains.policy import service
    return await service.settings_for_org(session, org_id, pinned_version_id)


async def get_approval(session: AsyncSession, approval_id: uuid.UUID) -> ApprovalSummary | None:
    from zoikorum.domains.policy.models import ApprovalRequest
    request = await session.get(ApprovalRequest, approval_id)
    return ApprovalSummary(request.id, request.organization_id, request.subject_type,
        request.subject_id, request.action, request.status) if request else None


async def search_eligibility(session: AsyncSession, org_id: uuid.UUID | None) -> dict[str, Any]:
    """Filter that search must apply for a buyer org:
    {"minTier": "B", "requiredDimensions": [...], "jurisdictions": [...]|None}"""
    from zoikorum.domains.policy import service
    profile, version = await service.effective_version(session, org_id)
    if not version:
        return {"minTier": "C", "requiredDimensions": [], "jurisdictions": None}
    return {"minTier": version.settings["minTrustTier"],
        "requiredDimensions": version.settings["requiredDimensions"],
        "jurisdictions": version.settings.get("allowedJurisdictions")}


async def commercial_context(session, *, org_id, professional_id, action, subject_type,
    subject_id, actor_identity_id, amount=0, currency=None, engagement_type=None,
    specialization=None, cost_center_id=None, pinned_version_id=None, extra=None, platform_default_pinned=False):
    """Gather authoritative cross-domain facts; callers never accept these from a client."""
    from zoikorum.domains.policy import service
    attrs = await service.attributes_for(session, org_id, professional_id, amount=amount,
        currency=currency, engagement_type=engagement_type, specialization=specialization,
        cost_center_id=cost_center_id, extra=extra)
    if platform_default_pinned:
        attrs["policy.platformDefaultPinned"] = True
    return PolicyContext(org_id, action, subject_type, subject_id, actor_identity_id, attrs, pinned_version_id)


async def require_allowed(session: AsyncSession, ctx: PolicyContext) -> PolicyDecision:
    from zoikorum.shared.errors import ApprovalRequired, ExceptionRequired, PolicyBlocked
    result = await evaluate(session, ctx)
    if result.allowed:
        return result
    reason = result.first_reason
    extra = {"organizationId": str(ctx.org_id), "subjectType": ctx.subject_type,
        "subjectId": str(ctx.subject_id), "action": ctx.action,
        "approvalRequestId": str(result.approval_request_id) if result.approval_request_id else None,
        "policyVersionLabel": result.policy_version_label}
    error = {Decision.BLOCK: PolicyBlocked, Decision.REQUIRE_APPROVAL: ApprovalRequired,
        Decision.REQUIRE_EXCEPTION: ExceptionRequired}[result.decision]
    raise error(reason.message if reason else "Organization policy requires authorization", extra=extra)


async def contract_terms(session: AsyncSession, org_id: uuid.UUID, version_id: uuid.UUID) -> dict:
    from zoikorum.domains.policy import service
    _, version = await service.effective_version(session, org_id, version_id)
    return {"governingLaw": version.settings.get("governingLaw"), "clauseTexts": version.settings.get("clauseTexts", {})}
