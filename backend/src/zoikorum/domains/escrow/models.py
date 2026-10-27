"""Escrow domain tables (financial: strictest rules).

One account per contract, one allocation per milestone. Every money movement writes a balanced group of
append-only double-entry ledger lines (sum of debits = sum of credits) in the same transaction as the balance change.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk, Versioned

SCHEMA = "escrow"


class EscrowAccount(Base, UUIDPk, Timestamps, Versioned):
    """UNFUNDED -> FUNDED -> PARTIALLY_RELEASED -> FULLY_RELEASED (DISPUTED / REFUNDED / CLOSED arrive with disputes);
    UNFUNDED -> EXPIRED when nothing was funded within the funding window."""

    __tablename__ = "accounts"
    __table_args__ = {"schema": SCHEMA}

    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNFUNDED")
    funded_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    held_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    on_hold_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    released_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refunded_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fees_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Retainer auto-funding: a saved payment method and the member whose authority funds each new cycle.
    auto_fund_token: Mapped[str | None] = mapped_column(String(120))
    auto_fund_identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    auto_fund_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Platform fee fixed when the contract activates, so a later fee change never alters a signed engagement.
    fee_bps: Mapped[int | None] = mapped_column(Integer)
    # Payment protection setup (after both signatures, before the first funding): how money is released (MILESTONE: each
    # milestone funded and released on its acceptance; RETAINER: each cycle the same way; FIXED: the whole fee funded at
    # once, released milestone by milestone on acceptance), who approves releases, and the buyer's confirmation that
    # a dispute freezes the affected money. Escrow itself is mandatory whatever is chosen.
    release_model: Mapped[str | None] = mapped_column(String(20))
    release_approver_identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    protection_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    protection_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class Allocation(Base, UUIDPk, Timestamps, Versioned):
    """UNFUNDED -> FUNDING -> HELD -> RELEASED (ON_HOLD / REFUNDED arrive with disputes). FUNDING -> UNFUNDED on payment failure.
    UNFUNDED -> EXPIRED (terminal) when the engagement was never funded within the funding window."""

    __tablename__ = "allocations"
    __table_args__ = {"schema": SCHEMA}

    account_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.accounts.id"), nullable=False, index=True)
    milestone_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="UNFUNDED")
    funding_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    released_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refunded_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    funded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # While RELEASE_PENDING_APPROVAL: when the buyer organisation's approval is due (from the policy approval request).
    release_approval_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Funding(Base, UUIDPk, Timestamps):
    """A buyer's request to fund one or more milestones. REQUESTED -> CAPTURED | FAILED."""

    __tablename__ = "fundings"
    __table_args__ = (Index("ix_fundings_account", "account_id", "created_at"), {"schema": SCHEMA})

    account_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.accounts.id"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    milestone_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="REQUESTED")
    failure_message: Mapped[str | None] = mapped_column(String(300))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Release(Base, UUIDPk, CreatedAt):
    """Money released for an accepted milestone. Unique per milestone, so a release can never run twice."""

    __tablename__ = "releases"
    __table_args__ = {"schema": SCHEMA}

    account_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.accounts.id"), nullable=False, index=True)
    milestone_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)


class LedgerEntry(Base, UUIDPk, CreatedAt):
    """Append-only double-entry line (database trigger rejects UPDATE/DELETE)."""

    __tablename__ = "ledger_entries"
    __table_args__ = (Index("ix_ledger_account", "account_id", "created_at"), Index("ix_ledger_group", "entry_group_id"), {"schema": SCHEMA})

    entry_group_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.accounts.id"), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False)  # BUYER_FUNDING|ESCROW_HOLD|ESCROW_RELEASE|PLATFORM_FEE|REFUND|PAYOUT|CHARGEBACK
    ledger_account: Mapped[str] = mapped_column(String(30), nullable=False)  # BUYER_CLEARING|ESCROW_HELD|PRO_PAYABLE|PLATFORM_REVENUE|BUYER_REFUND_PAYABLE
    debit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    credit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(30), nullable=False)  # FUNDING | RELEASE
    reference_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    memo: Mapped[str] = mapped_column(String(200), nullable=False, default="")


class LedgerSnapshot(Base, UUIDPk, CreatedAt):
    """Periodic balance snapshot of one escrow account (escrow/snapshots.py): per-ledger-account balances through the
    newest ledger line it covers, checked against the account's own figures. Balance reads start from the latest
    snapshot and add only the lines after it."""

    __tablename__ = "ledger_snapshots"
    __table_args__ = (Index("ix_ledger_snapshots_account", "account_id", "created_at"), {"schema": SCHEMA})

    account_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.accounts.id"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    through_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # newest line included
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balances: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {ledger account: credits - debits}
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OK")  # OK | MISMATCH
    problems: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
