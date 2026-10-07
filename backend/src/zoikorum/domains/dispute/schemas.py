from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.uploads import StoredFileOut, UploadIn

Category = Literal["SCOPE_DELIVERABLES", "QUALITY_ACCEPTANCE", "TIMELINE_DELAY", "PAYMENT_RELEASE", "PROFESSIONAL_CONDUCT",
                   "COMPLIANCE_BREACH", "JURISDICTION_LEGAL"]
Outcome = Literal["REWORK", "PARTIAL_RELEASE", "FULL_RELEASE", "PARTIAL_REFUND", "FULL_REFUND", "TIMELINE_EXTENSION", "TERMINATION"]
EvidenceType = Literal["CONTRACT_SCOPE", "MILESTONE_DEFINITION", "DELIVERABLE", "COMMUNICATION", "CHANGE_ORDER", "PAYMENT_RECORD",
                       "THIRD_PARTY", "OTHER"]


class DisputeIn(BaseModel):
    contractId: uuid.UUID
    milestoneIds: list[uuid.UUID] = Field(min_length=1, max_length=20)
    category: Category
    summary: str = Field(min_length=10, max_length=300)
    desiredOutcome: Outcome
    context: str = Field(default="", max_length=1000)


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


class MilestoneRef(BaseModel):
    id: uuid.UUID
    sequence: int
    title: str
    amount: MoneyDTO


class DisputeOut(BaseModel):
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
    nextStep: str  # plain-language "what happens next"
    createdAt: datetime
