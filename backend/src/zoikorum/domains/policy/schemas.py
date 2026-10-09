from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zoikorum.domains.policy.facade import Attr, PolicyAction
from zoikorum.shared.auth import OrgRole
from zoikorum.shared.uploads import UploadIn


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minTrustTier: Literal["A", "B", "C"] = "B"
    requiredDimensions: list[Literal["identity", "credentials", "jurisdiction", "restrictions", "insurance"]] = ["identity"]
    allowedJurisdictions: list[str] | None = None
    allowedCurrencies: list[str] | None = None
    escrowRequired: bool = True
    partialReleaseAllowed: bool = True
    acceptanceWindowDays: int = Field(default=14, ge=1, le=90)
    autoAcceptAfterDays: int | None = Field(default=None, ge=1, le=90)
    signatureDeadlineDays: int = Field(default=3, ge=1, le=90)
    disputeEvidenceDays: int = Field(default=7, ge=1, le=90)
    directResolutionBusinessDays: int = Field(default=5, ge=1, le=90)
    challengeWindowDays: int = Field(default=14, ge=1, le=90)
    autoDisputeMissedDeadline: bool = False
    autoDisputeRejectionCount: int | None = Field(default=None, ge=2, le=20)
    autoDisputeComplianceFlag: bool = False
    requiredClauses: list[Literal["CONFIDENTIALITY", "IP_OWNERSHIP", "TERMINATION", "GOVERNING_LAW"]] = [
        "CONFIDENTIALITY", "IP_OWNERSHIP", "TERMINATION", "GOVERNING_LAW",
    ]
    governingLaw: str | None = Field(default=None, max_length=200)
    clauseTexts: dict[str, str] = Field(default_factory=dict)
    stepUpForApprovals: bool = True

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
        allowed_clauses = {"CONFIDENTIALITY", "IP_OWNERSHIP", "TERMINATION", "GOVERNING_LAW"}
        if any(k not in allowed_clauses or not v.strip() or len(v) > 6000 for k, v in self.clauseTexts.items()):
            raise ValueError("clause texts must use supported clause names with nonempty text of at most 6000 characters")
        if not self.escrowRequired:
            raise ValueError("the platform baseline requires escrow before work; enterprise profiles cannot disable it")
        if self.autoAcceptAfterDays is not None and self.autoAcceptAfterDays < self.acceptanceWindowDays:
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
