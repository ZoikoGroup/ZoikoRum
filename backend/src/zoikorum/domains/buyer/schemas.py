from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from zoikorum.shared.money import MoneyDTO

OrgRoleName = Literal["ORG_ADMIN", "REQUESTER", "APPROVER", "BUDGET_OWNER", "LEGAL_REVIEWER", "EXCEPTION_AUTHORITY"]


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    orgType: str
    country: str
    status: str
    businessContext: str | None
    industry: str | None = None
    timeZone: str | None = None
    myRoles: list[str]
    memberCount: int
    createdAt: datetime


class OrganizationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    businessContext: Literal["STARTUP", "SME", "MID_MARKET", "ENTERPRISE"] | None = None
    industry: str | None = Field(default=None, max_length=80)
    timeZone: str | None = Field(default=None, max_length=64)


class MemberOut(BaseModel):
    identityId: uuid.UUID
    email: str
    displayName: str
    roles: list[str]
    spendLimit: MoneyDTO | None
    businessUnitId: uuid.UUID | None
    joinedAt: datetime
    lastActiveAt: datetime | None = None


class MemberPatch(BaseModel):
    roles: list[OrgRoleName] | None = Field(default=None, min_length=1)
    spendLimit: MoneyDTO | None = None
    clearSpendLimit: bool = False
    businessUnitId: uuid.UUID | None = None


class InviteIn(BaseModel):
    email: EmailStr
    roles: list[OrgRoleName] = Field(min_length=1)
    spendLimit: MoneyDTO | None = None
    businessUnitId: uuid.UUID | None = None


class InvitationOut(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    organizationName: str
    email: str
    roles: list[str]
    spendLimit: MoneyDTO | None
    status: str
    expiresAt: datetime
    createdAt: datetime
    # Only outside production (no email provider yet): link the admin can share.
    devInviteUrl: str | None = None


class AcceptByTokenIn(BaseModel):
    token: str = Field(min_length=10)


class BusinessUnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    parentId: uuid.UUID | None = None


class BusinessUnitOut(BaseModel):
    id: uuid.UUID
    name: str
    parentId: uuid.UUID | None


class CostCenterIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    businessUnitId: uuid.UUID | None = None
    quarterlyBudget: MoneyDTO | None = None


class CostCenterOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    businessUnitId: uuid.UUID | None
    quarterlyBudget: MoneyDTO | None


class BillingContactsIn(BaseModel):
    primaryIdentityId: uuid.UUID
    backupIdentityId: uuid.UUID | None = None


class BillingContactOut(BaseModel):
    identityId: uuid.UUID
    displayName: str
    email: str
    isPrimary: bool
