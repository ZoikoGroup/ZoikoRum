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
    recoveryCode: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{5}(-[0-9A-Fa-f]{5}){3}$")  # lost authenticator
    # Which sign-in page this came from: staff accounts sign in only on the staff page, everyone else only on the
    # customer page. Omitted by API clients and scripts, which are not tied to a page.
    portal: Literal["customer", "staff"] | None = None


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


class ResendConfirmationOut(BaseModel):
    message: str = "We have sent a new confirmation link to your email address."
    # Only returned in local development and tests (no email provider there).
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


class UserOut(BaseModel):
    """One account in the staff Users list (Platform Admin, Trust & Safety)."""

    id: uuid.UUID
    email: str
    displayName: str
    country: str
    personas: list[str]
    platformRoles: list[str]
    status: str  # ACTIVE | SUSPENDED | DELETED
    emailConfirmed: bool
    mfaEnabled: bool
    createdAt: datetime
    lastSignInAt: datetime | None


class RecoveryCodesOut(BaseModel):
    recoveryCodes: list[str]  # shown once: keep them somewhere safe


class MfaResetIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)  # how the person's identity was confirmed


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
    status: str  # RECEIVED | COMPLETED | SCHEDULED | BLOCKED | CANCELLED
    createdAt: datetime
    completedAt: datetime | None
    scheduledFor: datetime | None = None  # erasure date (cancellable until then)
    expiresAt: datetime | None = None  # export download available until
    downloadable: bool = False
    reasons: list[str] = []  # why an erasure is on hold
    retained: dict[str, str] = {}  # what is kept by law, per area


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


# ---- Passkeys ----------------------------------------------------------------------------------------------------------

class PasskeyOptionsIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)  # adding a sign-in method needs the account password


class PasskeyRegisterIn(BaseModel):
    name: str = Field(default="Passkey", max_length=100)  # e.g. "Work laptop"
    credential: dict  # the browser's PublicKeyCredential, as JSON


class PasskeyLoginIn(BaseModel):
    credential: dict
    portal: Literal["customer", "staff"] | None = None


class PasskeyStepUpIn(BaseModel):
    credential: dict


class PasskeyOut(BaseModel):
    id: uuid.UUID
    name: str
    backedUp: bool
    createdAt: datetime
    lastUsedAt: datetime | None
