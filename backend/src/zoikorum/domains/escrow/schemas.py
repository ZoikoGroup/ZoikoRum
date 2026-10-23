from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from zoikorum.shared.money import MoneyDTO


class FundIn(BaseModel):
    """Fund specific milestones, or every unfunded one (all=true). The token comes from the payment provider; card data
    never reaches Zoikorum."""

    milestoneIds: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    all: bool = False
    paymentMethodToken: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_\-]+$")

    @model_validator(mode="after")
    def _choice(self):
        if not self.all and not self.milestoneIds:
            raise ValueError("choose the milestones to fund, or all")
        return self


class AllocationOut(BaseModel):
    milestoneId: uuid.UUID
    sequence: int
    title: str
    amount: MoneyDTO
    state: str
    released: MoneyDTO
    fee: MoneyDTO
    fundedAt: datetime | None
    releasedAt: datetime | None
    releaseReference: str | None = None  # shown on "Funds released": the release's transaction reference
    releaseId: uuid.UUID | None = None  # its receipt: GET /v1/escrow/releases/{releaseId}/receipt
    releaseApprovalDueAt: datetime | None = None  # RELEASE_PENDING_APPROVAL: the buyer's approval is due by then (SLA)


class FundingOut(BaseModel):
    id: uuid.UUID
    amount: MoneyDTO
    milestoneIds: list[uuid.UUID]
    status: str
    failureMessage: str | None
    createdAt: datetime
    capturedAt: datetime | None


ReleaseModel = Literal["MILESTONE", "RETAINER", "FIXED"]


class ProtectionIn(BaseModel):
    """Payment protection setup, after both signatures and before the first funding. Escrow is mandatory whatever the model."""
    releaseModel: ReleaseModel
    approverIdentityId: uuid.UUID | None = None  # who approves releases on the buyer side; empty: the person setting it up
    disputeHoldAcknowledged: bool = False  # "a dispute freezes the affected money until it is resolved"


class ProtectionOut(BaseModel):
    releaseModel: ReleaseModel | None  # null: not set up yet (MILESTONE applies)
    approverIdentityId: uuid.UUID | None
    approverName: str | None
    confirmedAt: datetime | None
    explanation: str  # how money moves under the chosen model
    disputeHold: str  # what happens to the money in a dispute
    firstFunding: list[uuid.UUID]  # milestones the first funding must cover under this model


class ScreeningOut(BaseModel):
    """Buyer organisation screening, checked before any funding: FLAGGED blocks funding, PENDING warns."""
    status: Literal["CLEAR", "PENDING", "FLAGGED", "NOT_SCREENED"]
    message: str | None


class EscrowOut(BaseModel):
    autoFundingEnabledAt: datetime | None = None  # retainer cycles funded automatically from a saved method
    protection: ProtectionOut | None = None
    buyerScreening: ScreeningOut | None = None  # buyer side only
    id: uuid.UUID
    contractId: uuid.UUID
    status: str
    currency: str
    total: MoneyDTO
    funded: MoneyDTO
    held: MoneyDTO  # protected right now
    released: MoneyDTO
    fees: MoneyDTO
    refunded: MoneyDTO
    unfunded: MoneyDTO
    feeBps: int
    allocations: list[AllocationOut]
    fundings: list[FundingOut]
    viewerRole: str
    canFund: bool


class LedgerLineOut(BaseModel):
    id: uuid.UUID
    entryGroupId: uuid.UUID
    entryType: str
    ledgerAccount: str
    debit: MoneyDTO
    credit: MoneyDTO
    referenceType: str
    referenceId: uuid.UUID
    milestoneId: uuid.UUID | None
    memo: str
    createdAt: datetime


class AutoFundingIn(BaseModel):
    paymentMethodToken: str | None = Field(default=None, min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_\-]+$")  # null: turn off


class BulkFundItem(BaseModel):
    accountId: uuid.UUID
    milestoneIds: list[uuid.UUID] = Field(min_length=1, max_length=50)


class BulkFundIn(BaseModel):
    """Fund milestones across several engagements at once. Each engagement is checked (roles, spend limit, policy) and
    funded on its own, so one refusal does not stop the others."""

    items: list[BulkFundItem] = Field(min_length=1, max_length=25)
    paymentMethodToken: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_\-]+$")


# ---- Staff admin console: protected funds, one row per milestone allocation -----------------------------------------

class AdminEscrowRowOut(BaseModel):
    id: uuid.UUID  # the allocation
    contractId: uuid.UUID
    contractTitle: str
    milestoneId: uuid.UUID | None
    milestoneSequence: int | None
    buyerName: str
    professionalName: str
    currency: str
    amountMinor: int
    status: str  # UNFUNDED | FUNDING | HELD | ON_HOLD | RELEASE_PENDING_APPROVAL | RELEASED | PARTIALLY_RELEASED | REFUNDED
    provider: str | None  # payment provider that took the funding, once one was started
    providerReference: str | None
    updatedAt: datetime


class AdminEscrowBucketOut(BaseModel):
    status: str
    currency: str
    count: int
    amountMinor: int


class AdminEscrowSummaryOut(BaseModel):
    buckets: list[AdminEscrowBucketOut]  # per status and currency: amounts are never added across currencies
