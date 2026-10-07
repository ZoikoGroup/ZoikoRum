from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from zoikorum.shared.money import MoneyDTO


class PayoutAccountIn(BaseModel):
    holderName: str = Field(min_length=2, max_length=200)
    country: str = Field(pattern="^[A-Z]{2}$")
    currency: str = Field(pattern="^[A-Z]{3}$")
    accountNumber: str = Field(min_length=6, max_length=34, pattern=r"^[A-Za-z0-9 ]+$")  # passed to the provider, never stored


class PayoutAccountOut(BaseModel):
    holderName: str
    country: str
    currency: str
    label: str  # e.g. "Bank account •••• 4321"
    status: str
    createdAt: datetime


class PayoutOut(BaseModel):
    id: uuid.UUID
    contractId: uuid.UUID
    milestoneId: uuid.UUID | None
    gross: MoneyDTO
    fee: MoneyDTO
    net: MoneyDTO
    status: str
    failureMessage: str | None
    expectedAt: datetime | None = None  # when the money should reach the bank
    delayReason: str | None = None  # plain-language reason when a payout is waiting, late or failed
    settledAt: datetime | None
    createdAt: datetime


class EarningsOut(BaseModel):
    payoutAccount: PayoutAccountOut | None
    payouts: list[PayoutOut]
    totals: dict[str, MoneyDTO]  # settled / queued / failed, per currency of the first payout (single-currency summary)


class InvoiceOut(BaseModel):
    id: uuid.UUID
    number: str
    contractId: uuid.UUID
    milestoneId: uuid.UUID | None
    lines: list[dict]
    tax: MoneyDTO
    total: MoneyDTO
    issuedAt: datetime


class ChargeOut(BaseModel):
    id: uuid.UUID
    contractId: uuid.UUID
    amount: MoneyDTO
    status: str
    methodLabel: str
    failureMessage: str | None
    createdAt: datetime
    capturedAt: datetime | None
    chargedBackAt: datetime | None = None


class RefundOut(BaseModel):
    id: uuid.UUID
    contractId: uuid.UUID
    milestoneId: uuid.UUID | None
    disputeId: uuid.UUID | None
    amount: MoneyDTO
    status: str
    createdAt: datetime
    settledAt: datetime | None


class ReconciliationCheck(BaseModel):
    name: str
    currency: str
    ledger: int
    payments: int
    provider: int | None
    difference: int
    ok: bool


class ReconciliationOut(BaseModel):
    id: uuid.UUID
    day: date
    status: str
    mismatches: int
    checks: list[ReconciliationCheck]
    runBy: str
    updatedAt: datetime


class ReconcileIn(BaseModel):
    day: date
