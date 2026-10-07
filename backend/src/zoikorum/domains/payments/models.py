"""Payments domain tables: charges (payment intents), professional payout accounts, payouts and buyer invoices.

No raw card or bank data is stored: only provider references and masked labels.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, Sequence, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk

SCHEMA = "payments"
# Sequential invoice numbers without gaps from concurrent issuers.
INVOICE_NUMBER_SEQ = Sequence("invoice_number_seq", schema=SCHEMA, metadata=Base.metadata)


class PaymentIntent(Base, UUIDPk, Timestamps):
    """CREATED -> CAPTURED | FAILED; CAPTURED -> CHARGED_BACK if the card issuer reverses it. One per escrow funding."""

    __tablename__ = "payment_intents"
    __table_args__ = {"schema": SCHEMA}

    funding_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    escrow_account_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(100))
    method_label: Mapped[str] = mapped_column(String(80), nullable=False, default="Card")
    failure_code: Mapped[str | None] = mapped_column(String(60))
    failure_message: Mapped[str | None] = mapped_column(String(300))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    charged_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chargeback_minor: Mapped[int | None] = mapped_column(BigInteger)
    chargeback_reason: Mapped[str | None] = mapped_column(String(200))


class PayoutAccount(Base, UUIDPk, Timestamps):
    __tablename__ = "payout_accounts"
    __table_args__ = {"schema": SCHEMA}

    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    holder_name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_account_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class Payout(Base, UUIDPk, Timestamps):
    """QUEUED (no payout account yet) -> INITIATED -> SETTLED | FAILED. One per escrow release."""

    __tablename__ = "payouts"
    __table_args__ = (Index("ix_payouts_professional", "professional_id", "created_at"), {"schema": SCHEMA})

    release_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)  # net paid out
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED")
    provider_ref: Mapped[str | None] = mapped_column(String(100))
    failure_message: Mapped[str | None] = mapped_column(String(300))
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the bank should receive it
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invoice(Base, UUIDPk, Timestamps):
    """Buyer receipt for released work. Numbers are sequential (database sequence payments.invoice_number_seq)."""

    __tablename__ = "invoices"
    __table_args__ = (Index("ix_invoices_org", "organization_id", "created_at"), {"schema": SCHEMA})

    number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    release_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    lines: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{description, amountMinor}]
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Refund(Base, UUIDPk, Timestamps):
    """Money returned to the buyer's original payment method. One per escrow refund (idempotent)."""

    __tablename__ = "refunds"
    __table_args__ = (Index("ix_refunds_org", "organization_id", "created_at"), {"schema": SCHEMA})

    escrow_refund_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    payment_intent_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="INITIATED")  # INITIATED | SETTLED | FAILED
    provider_ref: Mapped[str | None] = mapped_column(String(100))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEvent(Base, UUIDPk, CreatedAt):
    """Every verified provider callback, stored once (provider + event id is unique): duplicates are ignored."""

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"), {"schema": SCHEMA})

    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(200), nullable=False, default="")


class ReconciliationBatch(Base, UUIDPk, Timestamps):
    """Daily reconciliation (Engineering Handbook 15.4): escrow ledger vs payments records vs the provider's report.
    MATCHED or MISMATCH; a mismatch is a P0 financial incident. Re-running a day updates its batch."""

    __tablename__ = "reconciliation_batches"
    __table_args__ = {"schema": SCHEMA}

    day: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{name, currency, ledger, payments, provider, difference, ok}]
    mismatches: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    run_by: Mapped[str] = mapped_column(String(60), nullable=False, default="SCHEDULE")
