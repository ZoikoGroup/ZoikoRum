import uuid
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
