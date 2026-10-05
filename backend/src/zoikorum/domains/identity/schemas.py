from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    displayName: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=2, max_length=2, pattern="^[A-Z]{2}$")
    acceptTerms: Literal[True]
    termsVersion: str = "2026-01"


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


class TokenPair(BaseModel):
    accessToken: str
    refreshToken: str
    tokenType: str = "Bearer"
    expiresIn: int


class LinkOut(BaseModel):
    type: str
    targetId: uuid.UUID
    roles: list[str]


class IdentityOut(BaseModel):
    id: uuid.UUID
    email: str
    displayName: str
    country: str
    status: str
    emailConfirmed: bool
    mfaEnabled: bool
    platformRoles: list[str]
    links: list[LinkOut] = []
    createdAt: datetime


class RegisterOut(BaseModel):
    identity: IdentityOut
    tokens: TokenPair
    # Only returned outside production so tests/dev can confirm without email.
    emailConfirmationToken: str | None = None


class MfaEnrollOut(BaseModel):
    secret: str
    otpauthUri: str
