from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.uploads import StoredFileOut, UploadIn

Category = Literal["SCOPE_DELIVERABLES", "QUALITY_ACCEPTANCE", "TIMELINE_DELAY", "PAYMENT_RELEASE", "PROFESSIONAL_CONDUCT",
                   "COMPLIANCE_BREACH", "JURISDICTION_LEGAL"]
Outcome = Literal["REWORK", "PARTIAL_RELEASE", "FULL_RELEASE", "PARTIAL_REFUND", "FULL_REFUND", "TIMELINE_EXTENSION", "TERMINATION"]
EvidenceType = Literal["CONTRACT_SCOPE", "MILESTONE_DEFINITION", "DELIVERABLE", "COMMUNICATION", "CHANGE_ORDER", "PAYMENT_RECORD",
                       "THIRD_PARTY", "OTHER"]


class AppealIn(BaseModel):
    grounds: Literal["NEW_MATERIAL_EVIDENCE", "PROCEDURAL_ERROR"]
    explanation: str = Field(min_length=20, max_length=4000)
    evidence: list[UploadIn] = Field(default_factory=list, max_length=10)


class AppealDecisionIn(BaseModel):
    outcome: Literal["UPHELD", "REJECTED"]
    reason: str = Field(min_length=20, max_length=4000)
    remediation: str = Field(default="", max_length=4000)


class DisputeIn(BaseModel):
    contractId: uuid.UUID
    milestoneIds: list[uuid.UUID] = Field(min_length=1, max_length=20)
    category: Category
    summary: str = Field(min_length=10, max_length=300)
    desiredOutcome: Outcome
    context: str = Field(default="", max_length=1000)
    prefersEarlyResolution: bool = False  # happy to settle directly before formal steps


class EvidenceIn(BaseModel):
    evidenceType: EvidenceType
    description: str = Field(min_length=5, max_length=1000)
    items: list[UploadIn] = Field(default_factory=list, max_length=10)


class AllocationIn(BaseModel):
    milestoneId: uuid.UUID
    releaseMinor: int = Field(ge=0)
    refundMinor: int = Field(ge=0)


class ResolutionIn(BaseModel):
    """Allocations may be left empty for full release / full refund (filled in) or rework / extension (money stays held)."""

    outcome: Outcome
    allocations: list[AllocationIn] = Field(default_factory=list, max_length=20)
    extendDays: int | None = Field(default=None, ge=1, le=180)  # timeline extension: how much later the work is due
    note: str = Field(default="", max_length=1000)


class RecommendationIn(ResolutionIn):
    summary: str = Field(min_length=20, max_length=2000)  # plain-language reasoning
    citations: list[str] = Field(default_factory=list, max_length=20)  # evidence and policy references


class AssignIn(BaseModel):
    mediatorIdentityId: uuid.UUID


class AllocationOut(BaseModel):
    milestoneId: uuid.UUID
    sequence: int
    title: str
    release: MoneyDTO
    refund: MoneyDTO
    milestoneOutcome: str  # ACCEPT | CANCEL | REWORK | EXTEND


class EvidenceOut(BaseModel):
    id: uuid.UUID
    party: str
    evidenceType: str
    description: str
    items: list[StoredFileOut]
    submittedAt: datetime


class ProposalOut(BaseModel):
    id: uuid.UUID
    party: str
    outcome: str
    allocations: list[AllocationOut]
    note: str
    status: str
    createdAt: datetime
    respondedAt: datetime | None
    mine: bool


class TimelineOut(BaseModel):
    kind: str
    actor: str
    text: str
    at: datetime
    ref: str | None = None  # links the entry to evidence, a proposal or a decision


class MilestoneRef(BaseModel):
    id: uuid.UUID
    sequence: int
    title: str
    amount: MoneyDTO


class DisputeOut(BaseModel):
    prefersEarlyResolution: bool = False
    clarifications: list[dict] = []
    canCooldown: bool = False
    id: uuid.UUID
    reference: str
    contractId: uuid.UUID
    contractReference: str
    milestones: list[MilestoneRef]
    category: str
    summary: str
    desiredOutcome: str
    context: str
    initiatorParty: str
    status: str
    disputed: MoneyDTO
    evidenceDeadline: datetime
    evidenceComplete: list[str]
    directDeadline: datetime | None
    mediatorAssigned: bool
    recommendation: dict | None
    pendingDecision: dict | None
    decision: dict | None
    decidedAt: datetime | None
    closedAt: datetime | None
    evidence: list[EvidenceOut]
    proposals: list[ProposalOut]
    timeline: list[TimelineOut]
    viewerRole: Literal["BUYER", "PROFESSIONAL", "MEDIATOR", "OPERATOR"]
    canEscalate: bool
    mediationRequired: bool = False  # the buyer organisation's policy sends settlements of this size to a mediator
    legalReviewRequired: bool = False  # the buyer's settlement needs the organisation's Legal Reviewer
    arbitration: dict | None = None  # referred to an outside arbitrator; money stays frozen until the award is recorded
    retainUntil: date | None = None  # closed records are kept at least until this date
    retentionBasis: str | None = None
    legalHold: bool = False
    nextStep: str  # plain-language "what happens next"
    createdAt: datetime


class ClarificationIn(BaseModel):
    to: Literal["BUYER", "PROFESSIONAL"]
    question: str = Field(min_length=10, max_length=500)


class ArbitrationReferIn(BaseModel):
    forum: str = Field(min_length=3, max_length=200)  # e.g. "ICC", "AAA", "LCIA", or the forum the engagement names
    reason: str = Field(min_length=20, max_length=2000)


class ArbitrationAwardIn(RecommendationIn):
    awardReference: str = Field(min_length=3, max_length=200)  # the arbitrator's award or case number


class LegalHoldIn(BaseModel):
    hold: bool
    reason: str = Field(min_length=10, max_length=500)
