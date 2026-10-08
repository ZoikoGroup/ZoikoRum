from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

AccountType = Literal["BUYER", "PROFESSIONAL", "FIRM", "ENTERPRISE"]
Dashboard = Literal["buyer", "professional", "firm", "enterprise", "ops"]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    displayName: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=2, max_length=2, pattern="^[A-Z]{2}$")
    accountType: AccountType = "BUYER"
    organizationName: str | None = Field(default=None, max_length=200)
    acceptTerms: Literal[True]
    termsVersion: str = "2026-01"

    @model_validator(mode="after")
    def _org_name_for_organizations(self) -> "RegisterIn":
        if self.accountType in ("FIRM", "ENTERPRISE") and not (self.organizationName or "").strip():
            raise ValueError("organizationName is required for Firm and Enterprise accounts")
        return self


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    totpCode: str | None = Field(default=None, pattern=r"^\d{6}$")


class RefreshIn(BaseModel):
    refreshToken: str


class ConfirmEmailIn(BaseModel):
    token: str


class StepUpIn(BaseModel):
    totpCode: str = Field(pattern=r"^\d{6}$")


class MfaVerifyIn(BaseModel):
    totpCode: str = Field(pattern=r"^\d{6}$")


class GrantRoleIn(BaseModel):
    role: str


class AddPersonaIn(BaseModel):
    accountType: Literal["BUYER", "PROFESSIONAL"]


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    newPassword: str = Field(min_length=12, max_length=256)


class TokenPair(BaseModel):
    accessToken: str
    refreshToken: str
    tokenType: str = "Bearer"
    expiresIn: int


class LinkOut(BaseModel):
    type: str
    targetId: uuid.UUID
    roles: list[str]
    kind: str | None = None


class IdentityOut(BaseModel):
    id: uuid.UUID
    email: str
    displayName: str
    country: str
    status: str
    emailConfirmed: bool
    mfaEnabled: bool
    # True when this account's roles demand MFA but it is not enabled yet (staff, enterprise admins).
    mfaRequired: bool
    mfaBypass: bool = False  # development only: authenticator codes are switched off
    personas: list[str]
    primaryPersona: str | None
    platformRoles: list[str]
    organizationName: str | None
    defaultDashboard: Dashboard
    links: list[LinkOut] = []
    phone: str | None = None
    language: str = "en"
    timeZone: str | None = None
    createdAt: datetime


class AuthOut(BaseModel):
    tokens: TokenPair
    user: IdentityOut


class RegisterOut(AuthOut):
    # Only returned outside production so tests/dev can confirm without email.
    emailConfirmationToken: str | None = None


class ForgotPasswordOut(BaseModel):
    message: str = "If an account exists for that email, a reset link has been sent."
    # Only returned outside production (no email provider yet).
    resetToken: str | None = None


class StaffMemberOut(BaseModel):
    id: uuid.UUID
    email: str
    displayName: str
    platformRoles: list[str]
    mfaEnabled: bool
    status: str


class MfaEnrollOut(BaseModel):
    secret: str
    otpauthUri: str


class MePatch(BaseModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, pattern=r"^(\+[1-9]\d{6,14})?$")  # E.164; "" clears it
    language: Literal["en", "en-GB", "en-US", "es", "fr", "de", "hi"] | None = None
    timeZone: str | None = Field(default=None, max_length=64)


class SessionOut(BaseModel):
    id: uuid.UUID
    device: str | None
    authStrength: str
    signedInAt: datetime
    current: bool


class DataRequestIn(BaseModel):
    requestType: Literal["ACCESS", "ERASURE"]


class DataRequestOut(BaseModel):
    id: uuid.UUID
    requestType: str
    status: str
    createdAt: datetime
    completedAt: datetime | None


class DuplicateAnswerIn(BaseModel):
    answer: Literal["MERGE_REQUESTED", "NOT_ME"]
    note: str | None = Field(default=None, max_length=500)


class DuplicateResolveIn(BaseModel):
    outcome: Literal["MERGED", "NOT_DUPLICATE"]
    keepIdentityId: uuid.UUID | None = None  # required for MERGED: the account that stays
    note: str = Field(min_length=5, max_length=500)


class DuplicateOut(BaseModel):
    id: uuid.UUID
    signal: str
    status: str
    userAnswer: str | None
    userNote: str | None
    resolutionNote: str | None
    createdAt: datetime
    resolvedAt: datetime | None
    account: str | None = None  # staff only
    accountName: str | None = None
    otherAccount: str | None  # masked for the person, full for staff
    otherAccountName: str | None = None
    identityId: uuid.UUID | None = None
    otherIdentityId: uuid.UUID | None = None
