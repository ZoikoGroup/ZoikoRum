import uuid
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

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
    # Ethics: who is affected and how (the person, their clients, ongoing engagements), recorded before any action.
    userImpact: str = Field(min_length=10, max_length=2000)


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
    action: Literal["WARNING", "VISIBILITY_REDUCTION", "DISPUTE_ACCESS_RESTRICTION", "MANDATORY_REMEDIATION", "ENGAGEMENT_SUSPENSION",
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


class PostReviewIn(BaseModel):
    """Level 3+ cases: what caused it, how the product experience contributed or was affected, and which policy
    changes are proposed. Required before the case is closed or concluded."""
    rootCause: str = Field(min_length=10, max_length=4000)
    uxImpact: str = Field(min_length=10, max_length=4000)
    policyUpdates: str = Field(min_length=5, max_length=4000)  # "None proposed: ..." is an answer too


class ReferralIn(BaseModel):
    """Level 4: a referral to law enforcement or a regulator, with Legal's sign-off."""
    agency: str = Field(min_length=2, max_length=200)
    agencyReference: str = Field(min_length=2, max_length=200)
    referredOn: date
    legalSignOff: str = Field(min_length=10, max_length=2000)  # the sign-off statement (who approved, on what basis)


class ConflictIn(BaseModel):
    """A staff member declares a conflict of interest with a subject, or recuses themselves from one case."""
    kind: Literal["DECLARATION", "RECUSAL"]
    subjectType: Literal["IDENTITY", "PROFESSIONAL", "ORGANIZATION"] | None = None
    subjectId: uuid.UUID | None = None
    caseKind: Literal["DISPUTE", "ENFORCEMENT_CASE"] | None = None
    caseId: str | None = Field(default=None, max_length=80)
    reason: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def target(self):
        if self.kind == "DECLARATION" and not (self.subjectType and self.subjectId):
            raise ValueError("a declaration names the person, professional or organisation it concerns")
        if self.kind == "RECUSAL" and not (self.caseKind and self.caseId):
            raise ValueError("a recusal names the case")
        return self


class FraudAlertIn(BaseModel):
    """A third-party fraud alert (signed with the platform webhook secret). Advisory: it opens a review, never a restriction."""
    provider: str = Field(min_length=2, max_length=60, pattern="^[A-Za-z0-9_.-]+$")
    alertId: str = Field(min_length=1, max_length=120)
    subjectType: Literal["IDENTITY", "PROFESSIONAL", "ORGANIZATION"]
    subjectId: uuid.UUID
    reasonCode: str = Field(min_length=3, max_length=100)
    score: int | None = Field(default=None, ge=0, le=100)
    details: dict = Field(default_factory=dict)



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
