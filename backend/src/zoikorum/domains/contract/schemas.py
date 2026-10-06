from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

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
