from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

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
    totals: dict[str, MoneyDTO]  # Legacy single-currency summary; empty for multiple currencies.
    totalsByCurrency: dict[str, dict[str, MoneyDTO]]
    monthlySettledByCurrency: list[MoneyDTO]


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


class OpsItemOut(BaseModel):
    kind: Literal["PAYOUT", "REFUND", "CHARGEBACK_LOSS"]
    id: uuid.UUID
    amount: MoneyDTO
    engagement: str
    contractId: uuid.UUID
    buyer: str
    professional: str
    problem: str
    since: datetime
    canRetry: bool
    resolution: str | None
    resolvedAt: datetime | None


class OpsWorklistOut(BaseModel):
    items: list[OpsItemOut]
    open: int


class OpsResolveIn(BaseModel):
    outcome: Literal["RECOVERED", "WRITTEN_OFF", "SETTLED_OUTSIDE"]
    note: str = Field(min_length=5, max_length=1000)
    # Why the exception should be closed this way, for the second person who approves it (defaults to the note).
    justification: str | None = Field(default=None, min_length=10, max_length=2000)


class RefundOut(BaseModel):
    id: uuid.UUID
    contractId: uuid.UUID
    milestoneId: uuid.UUID | None
    disputeId: uuid.UUID | None
    amount: MoneyDTO
    status: str
    failureMessage: str | None = None
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
    # CLEAN only when nothing differed and no break for the day is unresolved; BREAKS_OPEN while any break is not CLOSED.
    runStatus: Literal["CLEAN", "BREAKS_OPEN", "BREAKS_RESOLVED"]
    breaks: int = 0
    openBreaks: int = 0


class ReconcileIn(BaseModel):
    day: date


BreakStatus = Literal["OPEN", "EVIDENCE_GATHERING", "REVIEWED", "CLOSED"]


class ReconciliationBreakEvent(BaseModel):
    at: datetime
    by: str
    fromStatus: str | None
    toStatus: str
    note: str | None


class ReconciliationBreakOut(BaseModel):
    id: uuid.UUID
    batchId: uuid.UUID
    day: date
    kind: str
    currency: str
    amountMinor: int
    references: dict
    status: BreakStatus
    ownerId: uuid.UUID | None
    owner: str | None
    resolutionNote: str | None
    reviewedBy: uuid.UUID | None
    reviewedAt: datetime | None
    closedBy: uuid.UUID | None
    closedAt: datetime | None
    history: list[ReconciliationBreakEvent]
    createdAt: datetime
    updatedAt: datetime


class BreakAdvanceIn(BaseModel):
    status: Literal["EVIDENCE_GATHERING", "REVIEWED", "CLOSED"]
    note: str = Field(min_length=5, max_length=2000)
