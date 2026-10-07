from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from zoikorum.shared.money import MoneyDTO


class FileRef(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    size: int = Field(gt=0, le=100 * 1024 * 1024)


class SignIn(BaseModel):
    termsHash: str = Field(pattern="^[a-f0-9]{64}$")  # the version the signer read; a mismatch is refused


class SubmitIn(BaseModel):
    note: str = Field(default="", max_length=2000)
    files: list[FileRef] = Field(default_factory=list, max_length=10)


class RevisionIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class ChangeOrderIn(BaseModel):
    type: Literal["ADD_DELIVERABLE", "MODIFY_DELIVERABLE", "EXTEND_TIMELINE", "PRICING_CHANGE"]
    delta: dict[str, Any]
    impact: str = Field(min_length=5, max_length=1000)

    @field_validator("impact")
    @classmethod
    def normalize_impact(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("impact must contain at least 5 non-whitespace characters")
        return value


class ChangeOrderDecisionIn(BaseModel):
    reason: str | None = Field(default=None, min_length=5, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) < 5:
            raise ValueError("reason must contain at least 5 non-whitespace characters")
        return value


class ChangeOrderOut(BaseModel):
    id: uuid.UUID
    contractId: uuid.UUID
    proposedByIdentityId: uuid.UUID
    proposerParty: Literal["BUYER", "PROFESSIONAL"]
    type: str
    delta: dict[str, Any]
    impact: str
    baseContractVersion: int
    status: Literal["PROPOSED", "APPROVED", "REJECTED"]
    decidedByIdentityId: uuid.UUID | None
    decisionReason: str | None
    decidedAt: datetime | None
    appliedVersion: int | None
    createdAt: datetime
    preview: list[ChangePreviewOut] = Field(default_factory=list)


class ChangePreviewOut(BaseModel):
    label: str
    before: str
    after: str


class ContractRevisionOut(BaseModel):
    contractVersion: int
    changeOrderId: uuid.UUID | None
    currency: str
    total: MoneyDTO
    terms: dict
    milestones: list[dict]
    termsHash: str
    documentSha256: str
    createdAt: datetime


class PartyOut(BaseModel):
    role: Literal["BUYER", "PROFESSIONAL"]
    name: str
    detail: str | None  # organisation / firm line


class SignatureOut(BaseModel):
    party: str
    signerName: str
    contractVersion: int
    termsHash: str
    authStrength: str
    signedAt: datetime


class SubmissionOut(BaseModel):
    id: uuid.UUID
    note: str
    files: list[FileRef]
    submittedAt: datetime


class MilestoneOut(BaseModel):
    id: uuid.UUID
    sequence: int
    title: str
    description: str
    amount: MoneyDTO
    dueDate: date | None
    deliverableKeys: list[str]
    status: str
    startedAt: datetime | None
    submittedAt: datetime | None
    acceptanceDueAt: datetime | None
    acceptedAt: datetime | None
    revisionCount: int
    lastRevisionReason: str | None
    submissions: list[SubmissionOut]


class ContractOut(BaseModel):
    id: uuid.UUID
    reference: str
    proposalId: uuid.UUID
    requestId: uuid.UUID
    organizationId: uuid.UUID
    professionalId: uuid.UUID
    title: str
    engagementType: str
    pricingModel: str | None
    status: str
    pendingChangeOrderId: uuid.UUID | None
    total: MoneyDTO
    termsHash: str
    contractVersion: int
    parties: list[PartyOut]
    terms: dict
    ndaRequired: bool
    documentSha256: str
    policyVersionLabel: str
    signatureDeadline: datetime
    activatedAt: datetime | None
    completedAt: datetime | None
    signatures: list[SignatureOut]
    changeOrders: list[ChangeOrderOut]
    revisions: list[ContractRevisionOut]
    milestones: list[MilestoneOut]
    viewerRole: Literal["BUYER", "PROFESSIONAL", "OPERATOR"]
    nextAction: str  # plain language, from the viewer's side
    canSign: bool  # the viewer may sign now (still needs a fresh two-step confirmation)
    acceptedAmount: MoneyDTO
    createdAt: datetime
    version: int


class ContractSummaryOut(BaseModel):
    role: Literal["buyer", "professional"]
    contracts: dict[str, int]  # by contract status
    milestones: dict[str, int]  # by milestone status
