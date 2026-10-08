from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.uploads import StoredFileOut, UploadIn

EngagementType = Literal["ADVISORY", "PROJECT", "RETAINER", "FRACTIONAL"]
Duration = Literal["ONE_TWO_WEEKS", "THREE_SIX_WEEKS", "TWO_THREE_MONTHS", "THREE_SIX_MONTHS", "ONGOING"]
DeclineReason = Literal["OUT_OF_SCOPE", "NO_CAPACITY", "TIMELINE", "BUDGET", "CONFLICT_OF_INTEREST", "JURISDICTION", "OTHER"]
ATTACHMENT_TYPES = (".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg")


class Budget(BaseModel):
    minMinor: int | None = Field(default=None, ge=0)
    maxMinor: int = Field(gt=0)
    currency: str = Field(pattern="^[A-Z]{3}$")

    @model_validator(mode="after")
    def _range(self):
        if self.minMinor is not None and self.minMinor > self.maxMinor:
            raise ValueError("budget minimum is above the maximum")
        return self


class Attachment(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    size: int = Field(gt=0, le=25 * 1024 * 1024)

    @model_validator(mode="after")
    def _type(self):
        if not self.name.lower().endswith(ATTACHMENT_TYPES):
            raise ValueError("attachments must be PDF, DOCX, XLSX, PNG or JPG")
        return self


def _clean_deliverables(items: list[str]) -> list[str]:
    out = []
    for d in items:
        d = d.strip()
        if not 2 <= len(d) <= 200:
            raise ValueError("each deliverable is 2-200 characters")
        if d not in out:
            out.append(d)
    return out


class RequestIn(BaseModel):
    organizationId: uuid.UUID
    costCenterId: uuid.UUID | None = None
    professionalIds: list[uuid.UUID] = Field(min_length=1, max_length=3)
    offeringId: uuid.UUID | None = None
    service: str = Field(min_length=2, max_length=200)
    specialization: str | None = Field(default=None, max_length=120)
    engagementType: EngagementType
    businessContext: Literal["STARTUP", "SME", "MID_MARKET", "ENTERPRISE", "INDIVIDUAL"] | None = None
    objective: str = Field(min_length=5, max_length=300)
    details: str = Field(default="", max_length=1200)
    desiredStartDate: date
    estimatedDuration: Duration
    budget: Budget | None = None
    deliveryMode: Literal["REMOTE", "ONSITE", "HYBRID"] = "REMOTE"
    location: str | None = Field(default=None, max_length=200)
    ndaRequired: bool = False
    attachments: list[UploadIn] = Field(default_factory=list, max_length=3)  # PDF, Word, Excel, CSV, JPG or PNG
    deliverables: list[str] = Field(default_factory=list, max_length=15)
    dependencies: list[Literal["BUYER_DATA", "THIRD_PARTY_ACCESS", "INTERNAL_APPROVALS"]] = Field(default_factory=list, max_length=3)
    pricingPreferences: list[Literal["HOURLY", "FIXED", "RETAINER", "OPEN"]] = Field(default_factory=list, max_length=4)
    paymentCadence: Literal["MILESTONE", "MONTHLY", "COMPLETION"] | None = None
    acknowledged: bool = False  # "Zoikorum facilitates the engagement but does not provide professional services"
    draft: bool = False

    @model_validator(mode="after")
    def _rules(self):
        self.deliverables = _clean_deliverables(self.deliverables)
        if len(set(self.professionalIds)) != len(self.professionalIds):
            raise ValueError("each professional can be chosen once")
        if self.offeringId and len(self.professionalIds) > 1:
            raise ValueError("a service offering belongs to one professional")
        if self.deliveryMode != "REMOTE" and not (self.location or "").strip():
            raise ValueError("location is required for on-site or hybrid work")
        return self


class CancelIn(BaseModel):
    reasonCode: str = Field(default="BUYER_CANCELLED", min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)


class DeclineIn(BaseModel):
    reasonCode: DeclineReason
    note: str | None = Field(default=None, max_length=500)


class ProfessionalBrief(BaseModel):
    id: uuid.UUID
    displayName: str
    headline: str | None
    photoUrl: str | None
    tier: str
    country: str | None = None


class ProposalBrief(BaseModel):
    id: uuid.UUID
    status: str
    total: MoneyDTO
    submittedAt: datetime | None
    validUntil: date | None


class RequestOut(BaseModel):
    id: uuid.UUID
    groupId: uuid.UUID
    organizationId: uuid.UUID
    costCenterId: uuid.UUID | None = None
    organizationName: str | None
    buyerIdentityId: uuid.UUID
    buyerName: str | None
    professional: ProfessionalBrief
    offeringId: uuid.UUID | None
    service: str
    specialization: str | None
    engagementType: str
    businessContext: str | None
    detailsHidden: bool  # NDA required and not yet accepted by the professional
    objective: str | None
    details: str | None
    location: str | None
    attachments: list[StoredFileOut]
    desiredStartDate: date
    estimatedDuration: str
    budget: Budget | None
    deliveryMode: str
    ndaRequired: bool
    ndaAccepted: bool
    status: str
    sentAt: datetime | None
    closedAt: datetime | None
    reasonCode: str | None
    reasonNote: str | None
    proposal: ProposalBrief | None
    groupSize: int
    deliverables: list[str]  # hidden with the details until the NDA is accepted
    dependencies: list[str]
    pricingPreferences: list[str]
    paymentCadence: str | None
    jurisdictionConflict: bool  # the professional does not serve the buyer's country (block before agreement)
    viewerRole: Literal["BUYER", "PROFESSIONAL", "OPERATOR"]
    createdAt: datetime
    version: int


class RequestSummaryOut(BaseModel):
    role: Literal["buyer", "professional"]
    requests: dict[str, int]  # by request status
    proposals: dict[str, int]  # by proposal status


# ---- Proposals ------------------------------------------------------------------

class Deliverable(BaseModel):
    key: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=1000)
    acceptanceCriteria: str = Field(min_length=2, max_length=1000)


class Milestone(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=1000)
    amountMinor: int = Field(gt=0)
    dueDate: date | None = None
    deliverableKeys: list[str] = Field(min_length=1, max_length=20)


class RevisionChange(BaseModel):
    field: Literal["scope", "deliverables", "milestones", "price", "timeline", "assumptions", "exclusions", "other"]
    requested: str = Field(min_length=2, max_length=500)


class ProposalIn(BaseModel):
    """Drafts may be incomplete; submitting checks completeness (at least one deliverable and a price)."""

    summary: str = Field(default="", max_length=500)
    scopeAlignment: Literal["CONFIRMED", "ADJUSTED"] = "CONFIRMED"
    scopeNotes: str | None = Field(default=None, max_length=1000)
    deliverables: list[Deliverable] = Field(default_factory=list, max_length=20)
    milestones: list[Milestone] = Field(default_factory=list, max_length=20)
    pricingModel: Literal["HOURLY", "FIXED", "RETAINER"] = "FIXED"
    currency: str = Field(pattern="^[A-Z]{3}$")
    total: MoneyDTO | None = None  # optional; must equal the sum of milestone amounts when given
    startDate: date | None = None
    endDate: date | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    exclusions: list[str] = Field(default_factory=list, max_length=20)
    validUntil: date | None = None

    @model_validator(mode="after")
    def _rules(self):
        keys = [d.key for d in self.deliverables]
        if len(set(keys)) != len(keys):
            raise ValueError("deliverable keys must be unique")
        for m in self.milestones:
            unknown = set(m.deliverableKeys) - set(keys)
            if unknown:
                raise ValueError(f"milestone '{m.title}' refers to unknown deliverables: {', '.join(sorted(unknown))}")
        total = sum(m.amountMinor for m in self.milestones)
        if self.total is not None and (self.total.currency != self.currency or self.total.amountMinor != total):
            raise ValueError("total must equal the sum of the milestone amounts")
        if self.startDate and self.endDate and self.endDate < self.startDate:
            raise ValueError("end date is before the start date")
        if any(not s.strip() or len(s) > 300 for s in [*self.assumptions, *self.exclusions]):
            raise ValueError("assumptions and exclusions are short non-empty lines (300 characters max)")
        return self


class RevisionIn(BaseModel):
    changes: list[RevisionChange] = Field(min_length=1, max_length=10)
    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    reasonCode: str = Field(default="NOT_SELECTED", min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)


class Delta(BaseModel):
    field: str
    label: str
    requested: str
    proposed: str
    status: Literal["MATCH", "WITHIN", "ABOVE", "BELOW", "EARLIER", "LATER", "CHANGED"]


class ProposalOut(BaseModel):
    id: uuid.UUID
    requestId: uuid.UUID
    groupId: uuid.UUID
    organizationId: uuid.UUID
    professional: ProfessionalBrief
    status: str
    summary: str
    scopeAlignment: str
    scopeNotes: str | None
    deliverables: list[Deliverable]
    milestones: list[Milestone]
    pricingModel: str
    currency: str
    total: MoneyDTO
    startDate: date | None
    endDate: date | None
    assumptions: list[str]
    exclusions: list[str]
    validUntil: date | None
    expired: bool
    revisionRequests: list[dict]
    revisionCount: int
    submittedAt: datetime | None
    decidedAt: datetime | None
    reasonCode: str | None
    reasonNote: str | None
    termsHash: str | None
    deltas: list[Delta]
    createdAt: datetime
    updatedAt: datetime
    version: int
