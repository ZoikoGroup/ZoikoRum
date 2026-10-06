from __future__ import annotations

import uuid
from datetime import datetime

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


class FundingOut(BaseModel):
    id: uuid.UUID
    amount: MoneyDTO
    milestoneIds: list[uuid.UUID]
    status: str
    failureMessage: str | None
    createdAt: datetime
    capturedAt: datetime | None


class EscrowOut(BaseModel):
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
