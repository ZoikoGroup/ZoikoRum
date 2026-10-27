from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.uploads import StoredFileOut, UploadIn


class SignIn(BaseModel):
    termsHash: str = Field(pattern="^[a-f0-9]{64}$")  # the version the signer read; a mismatch is refused


class SubmitIn(BaseModel):
    """Sends the saved draft (confirmed + optional lateReason). Without a draft, note and files are sent in one step."""

    note: str = Field(default="", max_length=2000)
    files: list[UploadIn] = Field(default_factory=list, max_length=10)
    confirmed: bool = False  # the professional confirmed the declaration shown with the draft
    lateReason: str | None = Field(default=None, max_length=500)


class DraftTextIn(BaseModel):
    """Autosave of the draft's text: the message to the buyer and/or the note on any deliverable."""

    note: str | None = Field(default=None, max_length=2000)
    itemNotes: dict[str, str] = Field(default_factory=dict, max_length=50)

    @field_validator("itemNotes")
    @classmethod
    def short_notes(cls, value: dict[str, str]) -> dict[str, str]:
        if any(len(v) > 2000 for v in value.values()):
            raise ValueError("each note must be 2000 characters or fewer")
        return value


class EvidenceIn(BaseModel):
    """One piece of evidence for a deliverable: a file, or a link (website, shared document or code repository)."""

    file: UploadIn | None = None
    url: str | None = Field(default=None, max_length=2000)
    label: str | None = Field(default=None, max_length=200)
    version: str | None = Field(default=None, max_length=100)  # commit, tag or release the link points at


class VerdictIn(BaseModel):
    deliverableKey: str = Field(min_length=1, max_length=100)
    verdict: Literal["MET", "CHANGES_REQUESTED"]
    comment: str = Field(default="", max_length=1000)


class ReviewIn(BaseModel):
    verdicts: list[VerdictIn] = Field(min_length=1, max_length=50)


class PartialOfferIn(BaseModel):
    amountMinor: int = Field(gt=0)  # to release; the rest of the milestone is refunded to the buyer
    reason: str = Field(min_length=10, max_length=1000)  # against the acceptance criteria


class PartialOfferOut(BaseModel):
    amount: MoneyDTO
    refund: MoneyDTO
    reason: str
    offeredAt: datetime


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


class EvidenceOut(BaseModel):
    id: str
    type: Literal["FILE", "LINK"]
    file: StoredFileOut | None = None
    url: str | None = None
    host: str | None = None
    provider: str | None = None  # GOOGLE_SHEET, GITHUB, WEBSITE, ...
    kind: str | None = None  # DOCUMENT | REPOSITORY | WEBSITE
    label: str = ""
    version: str = ""


class SubmissionItemOut(BaseModel):
    deliverableKey: str
    title: str
    acceptanceCriteria: str
    note: str
    evidence: list[EvidenceOut]
    carriedOver: bool = False  # unchanged since the previous delivery


class VerdictOut(BaseModel):
    deliverableKey: str
    verdict: Literal["MET", "CHANGES_REQUESTED"]
    comment: str


class SubmissionReviewOut(BaseModel):
    verdicts: list[VerdictOut]
    outcome: Literal["ACCEPTED", "REVISION_REQUESTED"]
    reviewedAt: datetime


class SubmissionOut(BaseModel):
    id: uuid.UUID
    note: str
    files: list[StoredFileOut]
    submittedAt: datetime
    revisionNumber: int = 0
    items: list[SubmissionItemOut] = Field(default_factory=list)  # empty for one-step deliveries (note + files)
    declaredAt: datetime | None = None
    lateReason: str | None = None
    review: SubmissionReviewOut | None = None  # the buyer's verdict per deliverable, when given that way


class IssueOut(BaseModel):
    code: str
    message: str
    deliverableKey: str | None = None


class DraftItemOut(BaseModel):
    deliverableKey: str
    title: str
    acceptanceCriteria: str
    note: str
    evidence: list[EvidenceOut]
    ready: bool  # has at least one piece of evidence
    changesRequested: str | None = None  # the buyer's comment on this item in the last review


class SubmissionDraftOut(BaseModel):
    milestoneId: uuid.UUID
    revisionNumber: int  # what this delivery will be when sent
    note: str
    items: list[DraftItemOut]
    blockers: list[IssueOut]
    warnings: list[IssueOut]
    canSubmit: bool
    declaration: str  # the text the professional confirms when sending
    savedAt: datetime | None  # None until the first change is saved


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
    reviewOverdue: bool = False  # submitted work not reviewed within the window
    acceptedAt: datetime | None
    revisionCount: int
    lastRevisionReason: str | None
    submissions: list[SubmissionOut]
    partialOffer: "PartialOfferOut | None" = None  # a pending offer to accept for less
    acceptedRelease: MoneyDTO | None = None  # what was released when accepted for less than the full amount


class TerminateIn(BaseModel):
    """End the engagement. ``mutual``: ask the other side to agree (needed while money is in escrow); otherwise it ends
    at once, which is allowed only when nothing is held and no dispute is open."""
    reason: str = Field(min_length=5, max_length=1000)
    mutual: bool = False


class TerminationDecisionIn(BaseModel):
    agree: bool
    note: str | None = Field(default=None, max_length=1000)


class TerminationRequestOut(BaseModel):
    id: uuid.UUID
    requesterParty: Literal["BUYER", "PROFESSIONAL"]
    reason: str
    status: str
    expiresAt: datetime
    decisionNote: str | None
    decidedAt: datetime | None
    createdAt: datetime
    canAnswer: bool  # the viewer is on the other side and may agree or decline
    canWithdraw: bool


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
    # What people see: AWAITING_SIGNATURES | AWAITING_PAYMENT_PROTECTION (signed, first funding not in place yet; status
    # stays ACTIVE) | ACTIVE | DISPUTED | COMPLETED | TERMINATED.
    stage: str = ""
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
    # Ending the engagement: at once (nothing in escrow, no dispute) or by asking the other side to agree.
    pausedAt: datetime | None = None  # retainer paused by the buyer
    pauseReason: str | None = None
    canEndNow: bool = False
    canRequestEnd: bool = False
    terminationRequest: TerminationRequestOut | None = None
    createdAt: datetime
    version: int


class ContractSummaryOut(BaseModel):
    role: Literal["buyer", "professional"]
    contracts: dict[str, int]  # by contract status
    milestones: dict[str, int]  # by milestone status
    awaitingPaymentProtection: int = 0  # of the ACTIVE ones: signed, first funding not in place yet


# ---- Staff admin console ------------------------------------------------------------------------------------------

class AdminMilestoneOut(BaseModel):
    id: uuid.UUID
    sequence: int
    title: str
    status: str
    amountMinor: int
    dueDate: date | None


class AdminBuyerPartyOut(BaseModel):
    organizationId: uuid.UUID
    name: str
    country: str | None


class AdminProfessionalPartyOut(BaseModel):
    id: uuid.UUID
    name: str
    country: str | None


class AdminContractOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    version: int  # the signed terms' version (contract_version)
    currency: str
    totalMinor: int
    buyer: AdminBuyerPartyOut
    professional: AdminProfessionalPartyOut
    milestones: list[AdminMilestoneOut]
    fundedMinor: int  # escrow, in the contract's currency
    releasedMinor: int
    hasOpenDispute: bool
    createdAt: datetime
    signedAt: datetime | None  # both parties signed (the engagement became active)
    updatedAt: datetime


class AdminContractSummaryOut(BaseModel):
    total: int
    byStatus: dict[str, int]
    milestonesByStatus: dict[str, int]
    openDisputes: int
