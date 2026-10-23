from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zoikorum.config import get_settings

from zoikorum.domains.policy.facade import Attr, PolicyAction
from zoikorum.shared.auth import OrgRole
from zoikorum.shared.uploads import UploadIn


OrgRoleName = Literal["ORG_ADMIN", "REQUESTER", "APPROVER", "BUDGET_OWNER", "LEGAL_REVIEWER", "EXCEPTION_AUTHORITY"]
CLAUSE_NAMES = {"CONFIDENTIALITY", "IP_OWNERSHIP", "TERMINATION", "GOVERNING_LAW"}


class ContractVariantIn(BaseModel):
    """A regional contract variant: engagements whose contracting jurisdiction is listed use this governing law and
    these clause texts (over the profile's own) when the contract is generated."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=40, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=80)
    jurisdictions: list[str] = Field(min_length=1, max_length=50)
    governingLaw: str | None = Field(default=None, max_length=200)
    clauseTexts: dict[str, str] = Field(default_factory=dict)

    @field_validator("jurisdictions")
    @classmethod
    def countries(cls, values):
        values = sorted(set(v.upper() for v in values))
        if any(len(v) != 2 or not v.isalpha() or not v.isascii() for v in values):
            raise ValueError("use ISO two-letter country codes")
        return values

    @model_validator(mode="after")
    def clauses(self):
        if any(k not in CLAUSE_NAMES or not v.strip() or len(v) > 6000 for k, v in self.clauseTexts.items()):
            raise ValueError("variant clause texts must use supported clause names with nonempty text of at most 6000 characters")
        if not self.governingLaw and not self.clauseTexts:
            raise ValueError("a contract variant sets a governing law, clause texts, or both")
        return self


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minTrustTier: Literal["A", "B", "C"] = "B"
    requiredDimensions: list[Literal["identity", "credentials", "jurisdiction", "restrictions", "insurance"]] = ["identity"]
    allowedJurisdictions: list[str] | None = None
    allowedCurrencies: list[str] | None = None
    escrowRequired: bool = True
    partialReleaseAllowed: bool = True
    # Deadlines: leave empty to use the platform defaults (ZK_ACCEPTANCE_WINDOW_DAYS, ...; policy.service.platform_deadlines),
    # so a profile that only sets other rules never changes them silently.
    acceptanceWindowDays: int | None = Field(default=None, ge=1, le=90)
    autoAcceptAfterDays: int | None = Field(default=None, ge=1, le=90)
    signatureDeadlineDays: int | None = Field(default=None, ge=1, le=90)
    disputeEvidenceDays: int | None = Field(default=None, ge=1, le=90)
    directResolutionBusinessDays: int | None = Field(default=None, ge=1, le=90)
    challengeWindowDays: int | None = Field(default=None, ge=1, le=90)
    autoDisputeMissedDeadline: bool = False
    autoDisputeRejectionCount: int | None = Field(default=None, ge=2, le=20)
    autoDisputeComplianceFlag: bool = False
    # Enterprise dispute controls: above these amounts (minor units, engagement currency) a settlement needs a mediator,
    # or a Legal Reviewer of the organisation; escalation roles name who may take a case to mediation for the organisation.
    disputeMediationAboveMinor: int | None = Field(default=None, ge=0)
    disputeLegalReviewAboveMinor: int | None = Field(default=None, ge=0)
    disputeRetentionYears: int | None = Field(default=None, ge=1, le=25)  # keep closed dispute records at least this long
    disputeEscalationRoles: list[Literal["ORG_ADMIN", "REQUESTER", "APPROVER", "BUDGET_OWNER", "LEGAL_REVIEWER", "EXCEPTION_AUTHORITY"]] | None = None
    requiredClauses: list[Literal["CONFIDENTIALITY", "IP_OWNERSHIP", "TERMINATION", "GOVERNING_LAW"]] = [
        "CONFIDENTIALITY", "IP_OWNERSHIP", "TERMINATION", "GOVERNING_LAW",
    ]
    governingLaw: str | None = Field(default=None, max_length=200)
    clauseTexts: dict[str, str] = Field(default_factory=dict)
    stepUpForApprovals: bool = True
    # Payment rules. Escrow itself is never optional (platform baseline); these shape how milestones and retainers use it.
    milestoneMaxSharePercent: int | None = Field(default=None, ge=1, le=100)  # no milestone above this share of the total
    milestoneAcceptanceCriteriaRequired: bool = False  # every milestone names deliverables with acceptance criteria
    retainerAutoFundAllowed: bool = True  # retainer cycles may be funded automatically from a saved payment method
    retainerCycleApproval: bool = False  # each retainer cycle needs an approval before it is funded
    retainerCycleApprovalRole: OrgRoleName = "APPROVER"
    # Exceptions: who may ask (None: any member) and who may decide (None: Exception Authority only).
    exceptionRequestRoles: list[OrgRoleName] | None = None
    exceptionApproverRoles: list[OrgRoleName] | None = None
    # Regional contract variants, chosen by the contracting jurisdiction when the contract is generated.
    contractVariants: list[ContractVariantIn] = Field(default_factory=list, max_length=20)

    @field_validator("exceptionRequestRoles", "exceptionApproverRoles")
    @classmethod
    def role_lists(cls, values):
        if values is None:
            return values
        if not values:
            raise ValueError("name at least one role, or leave empty for the default")
        return sorted(set(values))

    @field_validator("allowedJurisdictions", "allowedCurrencies")
    @classmethod
    def countries_and_currencies(cls, values, info):
        if values is None:
            return values
        length = 2 if info.field_name == "allowedJurisdictions" else 3
        values = sorted(set(v.upper() for v in values))
        if not values or any(len(v) != length or not v.isalpha() or not v.isascii() for v in values):
            raise ValueError("use a nonempty list of ISO country/currency codes, or null for no restriction")
        return values

    @model_validator(mode="after")
    def platform_safety(self):
        if any(k not in CLAUSE_NAMES or not v.strip() or len(v) > 6000 for k, v in self.clauseTexts.items()):
            raise ValueError("clause texts must use supported clause names with nonempty text of at most 6000 characters")
        if not self.escrowRequired:
            raise ValueError("the platform baseline requires escrow before work; enterprise profiles cannot disable it")
        if len({v.id for v in self.contractVariants}) != len(self.contractVariants):
            raise ValueError("contract variant ids must be unique")
        seen: set[str] = set()
        for variant in self.contractVariants:
            if seen & set(variant.jurisdictions):
                raise ValueError("a country can belong to one contract variant only")
            seen |= set(variant.jurisdictions)
        window = self.acceptanceWindowDays or get_settings().acceptance_window_days
        if self.autoAcceptAfterDays is not None and self.autoAcceptAfterDays < window:
            raise ValueError("automatic acceptance cannot precede the review window")
        return self


class ApprovalStepIn(BaseModel):
    role: str
    count: int = Field(default=1, ge=1, le=10)

    @field_validator("role")
    @classmethod
    def role_exists(cls, value):
        if value not in OrgRole.ALL:
            raise ValueError("unknown organization role")
        return value


class ApprovalRouteIn(BaseModel):
    mode: Literal["SINGLE", "SEQUENTIAL", "PARALLEL"] = "SINGLE"
    steps: list[ApprovalStepIn] = Field(default_factory=lambda: [ApprovalStepIn(role="APPROVER")], min_length=1, max_length=10)
    timeoutHours: int = Field(default=48, ge=1, le=720)
    escalationRole: str = "ORG_ADMIN"

    @model_validator(mode="after")
    def route_valid(self):
        if self.escalationRole not in OrgRole.ALL:
            raise ValueError("unknown escalation role")
        if self.mode == "SINGLE" and (len(self.steps) != 1 or self.steps[0].count != 1):
            raise ValueError("single approval requires one approver")
        return self


FIELDS = {v for k, v in vars(Attr).items() if k.isupper()} | {
    "contract.termsHash", "contract.version", "contract.signerParty", "proposal.termsDigest",
    "engagement.allMilestonesAccepted",
}
OPS = {"EQ", "NEQ", "GT", "GTE", "LT", "LTE", "IN", "NOT_IN", "CONTAINS", "EXISTS"}


def validate_condition(condition: dict, depth: int = 0) -> None:
    if depth > 8:
        raise ValueError("conditions may nest at most eight levels")
    if "all" in condition or "any" in condition:
        if len(condition) != 1:
            raise ValueError("a condition group has exactly one of all/any")
        children = condition.get("all", condition.get("any"))
        if not isinstance(children, list) or not 1 <= len(children) <= 25:
            raise ValueError("condition groups require 1-25 conditions")
        for child in children:
            if not isinstance(child, dict):
                raise ValueError("each condition must be an object")
            validate_condition(child, depth + 1)
        return
    if condition.get("field") not in FIELDS or condition.get("op") not in OPS:
        raise ValueError("unknown policy attribute or operator")
    if set(condition) - {"field", "op", "value"}:
        raise ValueError("unknown condition property")
    if condition["op"] != "EXISTS" and "value" not in condition:
        raise ValueError("condition value is required")
    if condition["op"] in {"IN", "NOT_IN"} and not isinstance(condition.get("value"), list):
        raise ValueError("IN and NOT_IN require a list")


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=60, pattern="^[A-Za-z0-9_-]+$")
    appliesTo: list[str] = Field(min_length=1, max_length=8)
    condition: dict[str, Any]
    decision: Literal["BLOCK", "REQUIRE_APPROVAL", "REQUIRE_EXCEPTION"]
    reasonCode: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=5, max_length=500)
    approval: ApprovalRouteIn | None = None

    @model_validator(mode="after")
    def valid(self):
        if any(a not in PolicyAction.ALL for a in self.appliesTo):
            raise ValueError("unknown policy action")
        validate_condition(self.condition)
        if self.decision == "REQUIRE_APPROVAL" and self.approval is None:
            self.approval = ApprovalRouteIn()
        return self


class ProfileIn(BaseModel):
    orgId: uuid.UUID
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=1000)
    template: Literal["REGULATED", "ENTERPRISE_STANDARD", "CROSS_BORDER", "GROWTH_ADVISORY"] | None = None
    settings: SettingsIn | None = None
    rules: list[RuleIn] | None = Field(default=None, max_length=50)
    businessUnitIds: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    riskLevel: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"


class DraftIn(BaseModel):
    version: int = Field(ge=1)
    settings: SettingsIn
    rules: list[RuleIn] = Field(default_factory=list, max_length=50)

    @field_validator("rules")
    @classmethod
    def unique_rules(cls, values):
        if len({r.id for r in values}) != len(values):
            raise ValueError("rule ids must be unique")
        return values


class ApprovalDecisionIn(BaseModel):
    decision: Literal["GRANT", "DENY"]
    reason: str = Field(min_length=3, max_length=1000)
    stepId: str | None = Field(default=None, max_length=100)


class ExceptionIn(BaseModel):
    orgId: uuid.UUID
    subjectType: str = Field(min_length=1, max_length=60)
    subjectId: uuid.UUID
    action: str
    justification: str = Field(min_length=10, max_length=4000)
    documents: list[UploadIn] = Field(default_factory=list, max_length=10)
    expiresAt: datetime
    # Emergency path: for work that cannot wait (a regulator deadline, an incident). Short-lived (72 hours at most),
    # needs a fuller reason, and every Exception Authority is told at once; the decision is still a person's.
    emergency: bool = False


class ExceptionDecisionIn(BaseModel):
    decision: Literal["GRANT", "DENY"]
    reason: str = Field(min_length=3, max_length=1000)


class EvaluateIn(BaseModel):
    orgId: uuid.UUID
    action: str
    subjectType: str = Field(min_length=1, max_length=60)
    subjectId: uuid.UUID
    attributes: dict[str, Any] = Field(default_factory=dict)
    pinnedPolicyVersionId: uuid.UUID | None = None
    previewProfileId: uuid.UUID | None = None
