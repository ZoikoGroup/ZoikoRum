from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

FirmRoleName = Literal["FIRM_ADMIN", "FIRM_MEMBER", "AUTHORIZED_REPRESENTATIVE"]
SizeBand = Literal["1-5", "6-20", "21-100", "100+"]


class FirmOut(BaseModel):
    id: uuid.UUID
    legalName: str
    tradingName: str | None
    registrationNumber: str | None
    hqCountry: str
    sizeBand: str | None
    primaryCategory: str | None
    website: str | None
    status: str
    myRoles: list[str]
    memberCount: int
    hasAuthorizedRepresentative: bool
    version: int
    createdAt: datetime


class FirmPatch(BaseModel):
    legalName: str | None = Field(default=None, min_length=1, max_length=200)
    tradingName: str | None = Field(default=None, max_length=200)
    registrationNumber: str | None = Field(default=None, max_length=100)
    hqCountry: str | None = Field(default=None, pattern="^[A-Z]{2}$")
    sizeBand: SizeBand | None = None
    primaryCategory: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=300, pattern=r"^https?://")


class FirmMemberOut(BaseModel):
    identityId: uuid.UUID
    email: str
    displayName: str
    roles: list[str]
    joinedAt: datetime


class FirmMemberPatch(BaseModel):
    roles: list[FirmRoleName] = Field(min_length=1)


class FirmInviteIn(BaseModel):
    email: EmailStr
    roles: list[FirmRoleName] = Field(default_factory=lambda: ["FIRM_MEMBER"], min_length=1)


class FirmInvitationOut(BaseModel):
    id: uuid.UUID
    firmId: uuid.UUID
    firmName: str
    email: str
    roles: list[str]
    status: str
    expiresAt: datetime
    createdAt: datetime
    devInviteUrl: str | None = None


class AcceptByTokenIn(BaseModel):
    token: str = Field(min_length=10)
