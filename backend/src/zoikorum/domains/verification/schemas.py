from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SubjectType = Literal["PROFESSIONAL", "FIRM"]
# Types a subject owner may start themselves. CREDENTIAL cases open from credential claims and
# RESTRICTIONS (sanctions screening) opens automatically at registration.
SelfServiceType = Literal["IDENTITY", "JURISDICTION", "INSURANCE", "FIRM_REGISTRATION"]


class CaseIn(BaseModel):
    verificationType: SelfServiceType
    subjectType: SubjectType
    subjectId: uuid.UUID
    jurisdiction: str | None = Field(default=None, pattern="^[A-Za-z]{2}$")
    details: dict = Field(default_factory=dict)


EvidenceContentType = Literal["application/pdf", "image/jpeg", "image/png"]


class EvidenceFile(BaseModel):
    """The document itself (base64) plus the fingerprint the browser computed; the server checks both."""

    name: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    size: int = Field(gt=0, le=10 * 1024 * 1024)
    contentType: EvidenceContentType
    dataBase64: str = Field(min_length=4, max_length=14 * 1024 * 1024)


class EvidenceIn(BaseModel):
    evidenceType: Literal["ID_DOCUMENT", "PROOF_OF_ADDRESS", "LICENSE", "CERTIFICATE", "INSURANCE_POLICY",
                          "REGISTRATION_DOCUMENT", "OTHER"]
    items: list[EvidenceFile] = Field(min_length=1, max_length=5)


class DecisionIn(BaseModel):
    decision: Literal["VERIFIED", "FAILED", "NEEDS_INFO"]
    reasonCode: str = Field(min_length=2, max_length=60)
    publicReason: str | None = Field(default=None, max_length=500)  # shown to the subject; required unless VERIFIED
    expiresAt: datetime | None = None


class RevokeIn(BaseModel):
    reasonCode: str = Field(min_length=2, max_length=60)
    publicReason: str = Field(min_length=5, max_length=500)


class EvidenceOut(BaseModel):
    id: uuid.UUID
    evidenceType: str
    fileName: str
    sha256: str
    sizeBytes: int
    contentType: str | None
    hasFile: bool
    uploadedAt: datetime


class CaseOut(BaseModel):
    id: uuid.UUID
    subjectType: str
    subjectId: uuid.UUID
    verificationType: str
    status: str
    label: str
    jurisdiction: str | None
    credentialClaimId: uuid.UUID | None
    specialization: str | None
    estimatedCompletion: datetime | None
    verifiedAt: datetime | None
    expiresAt: datetime | None
    reasonCode: str | None
    publicReason: str | None
    isMine: bool
    evidence: list[EvidenceOut]
    createdAt: datetime
    version: int


class QueueItemOut(BaseModel):
    id: uuid.UUID
    subjectType: str
    subjectId: uuid.UUID
    subjectName: str | None
    verificationType: str
    status: str
    label: str
    jurisdiction: str | None
    providerResult: str | None
    evidenceCount: int
    estimatedCompletion: datetime | None
    overdue: bool
    createdAt: datetime
