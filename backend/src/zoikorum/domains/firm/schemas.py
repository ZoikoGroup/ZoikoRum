from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

FirmRoleName = Literal["FIRM_ADMIN", "FIRM_MEMBER", "AUTHORIZED_REPRESENTATIVE"]
SizeBand = Literal["1-5", "6-20", "21-100", "100+"]


class RepresentativeOut(BaseModel):
    identityId: uuid.UUID
    displayName: str
    identityVerified: bool


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
    # At least one representative whose own identity check is verified (needed for regulated firm work).
    hasVerifiedRepresentative: bool
    representatives: list[RepresentativeOut]
    version: int
    createdAt: datetime


class MoneyTotal(BaseModel):
    currency: str
    heldMinor: int
    releasedMinor: int


class FirmProfessionalWork(BaseModel):
    """One member professional's work, as counts and totals only: no buyers, contract terms or documents."""
    professionalId: uuid.UUID
    displayName: str
    headline: str | None
    published: bool
    tier: str = "C"  # Trust Tier: the firm sees which professionals still need verification
    openRequests: int
    awaitingSignature: int
    activeContracts: int
    completedContracts: int
    money: list[MoneyTotal]


class FirmOverviewOut(BaseModel):
    professionals: list[FirmProfessionalWork]
    openRequests: int
    awaitingSignature: int
    activeContracts: int
    completedContracts: int
    money: list[MoneyTotal]  # per currency, never converted


class FirmPageMember(BaseModel):
    professionalId: uuid.UUID
    displayName: str
    headline: str | None
    photoUrl: str | None
    tier: str


class FirmPageOut(BaseModel):
    """What buyers see about a firm (no registration number, people's emails or internal roles)."""
    id: uuid.UUID
    name: str
    legalName: str
    hqCountry: str
    sizeBand: str | None
    primaryCategory: str | None
    website: str | None
    verified: bool
    hasVerifiedRepresentative: bool
    verifiedCredentials: list[str]
    professionals: list[FirmPageMember]


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
