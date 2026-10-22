import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator

from zoikorum.shared.uploads import UploadIn


class CaseIn(BaseModel):
    subjectType: Literal["IDENTITY", "PROFESSIONAL", "ORGANIZATION"]
    subjectId: uuid.UUID
    signalSource: str = Field(min_length=3, max_length=100)
    summary: str = Field(min_length=10, max_length=2000)
    evidenceRefs: list[str] = Field(default_factory=list, max_length=50)


class AssessmentIn(BaseModel):
    level: int = Field(ge=0, le=4)
    reasonCode: str = Field(min_length=3, max_length=100)


class NoticeIn(BaseModel):
    whatHappened: str = Field(min_length=10, max_length=2000)
    whyItHappened: str = Field(min_length=10, max_length=2000)
    whatChanged: str = Field(min_length=10, max_length=2000)
    whatYouCanDo: str = Field(min_length=10, max_length=2000)
    whatHappensNext: str = Field(min_length=10, max_length=2000)
    howToGetHelp: str = Field(min_length=10, max_length=2000)

    @field_validator("*", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ActionIn(BaseModel):
    action: Literal["WARNING", "VISIBILITY_REDUCTION", "DISPUTE_ACCESS_RESTRICTION", "ENGAGEMENT_SUSPENSION",
                    "CREDENTIAL_ENFORCEMENT", "VERIFICATION_RESET", "SUSPEND_ACCOUNT", "OFFBOARD"]
    notice: NoticeIn
    durationDays: int | None = Field(default=None, ge=1, le=365)
    # Mandatory remediation (Level 2): what the person must do; tracked to completion.
    remediation: list[str] = Field(default_factory=list, max_length=10)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=20, max_length=4000)


class AppealDecisionIn(ReasonIn):
    upheld: bool


class ReportIn(BaseModel):
    subjectType: Literal["PROFESSIONAL", "IDENTITY", "ORGANIZATION", "REVIEW", "MESSAGE"]
    subjectId: uuid.UUID
    category: Literal["MISCONDUCT", "FRAUD_OR_SCAM", "MISREPRESENTATION", "HARASSMENT_OR_ABUSE", "OFF_PLATFORM_PAYMENT",
                      "UNSAFE_OR_ILLEGAL", "FAKE_REVIEW", "OTHER"]
    description: str = Field(min_length=20, max_length=2000)
    confidential: bool = False


class CloseCaseIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class AppealIn(BaseModel):
    reason: str = Field(min_length=20, max_length=4000)
    evidence: list[UploadIn] = Field(default_factory=list, max_length=5)


class RemediationDoneIn(BaseModel):
    note: str = Field(min_length=5, max_length=1000)


class OverrideIn(BaseModel):
    reason: str = Field(min_length=20, max_length=4000)



# ---- Maker-checker approvals (admin/approvals.py) ---------------------------------------------------------------------

ApprovalKind = Literal["GRANT_PLATFORM_ROLE", "REVOKE_PLATFORM_ROLE", "SWITCH_CHANGE", "FINANCIAL_EXCEPTION_RESOLVE",
                       "DEAD_LETTER_REPLAY_FINANCIAL", "AUDIT_EXPORT"]
ApprovalStatus = Literal["REQUESTED", "APPLIED", "FAILED", "REJECTED", "EXPIRED", "CANCELLED"]


class ApprovalRequestIn(BaseModel):
    kind: ApprovalKind
    payload: dict = Field(default_factory=dict)  # per kind, see admin/approvals.py PAYLOADS
    justification: str = Field(min_length=10, max_length=2000)


class ApprovalDecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=1000)  # required (5+ characters) to reject


class ApprovalPersonOut(BaseModel):
    id: uuid.UUID
    displayName: str | None
    email: str | None


class ApprovalRequestOut(BaseModel):
    """A privileged staff action waiting for, or decided by, a second person. ``status`` is the whole lifecycle:
    REQUESTED (nothing has changed yet), APPLIED (approved and carried out), FAILED (approved, could not be carried
    out: see applyError), REJECTED, EXPIRED or CANCELLED (never carried out)."""
    id: uuid.UUID
    kind: ApprovalKind
    status: ApprovalStatus
    summary: str
    payload: dict
    justification: str
    requestedBy: ApprovalPersonOut
    requestedAt: datetime
    expiresAt: datetime
    approverRoles: list[str]
    decidedBy: ApprovalPersonOut | None
    decidedAt: datetime | None
    decisionNote: str | None
    appliedAt: datetime | None
    applyError: str | None
    result: dict | None
    canDecide: bool  # the signed-in staff member may approve or reject it
    canCancel: bool  # the signed-in staff member asked for it and it is still waiting


class ApprovalSummaryOut(BaseModel):
    awaitingMe: int
    myOpen: int
    applied7d: int
    rejectedOrExpired7d: int
    failed7d: int
