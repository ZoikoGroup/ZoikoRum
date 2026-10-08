"""Verification domain tables. Evidence files live in blob storage; only metadata + SHA-256 are stored here."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk, Versioned

SCHEMA = "verification"


class VerificationCase(Base, UUIDPk, Timestamps, Versioned):
    """One check of one subject. PENDING -> IN_REVIEW -> NEEDS_INFO -> VERIFIED | FAILED;
    VERIFIED -> EXPIRED | REVOKED. Verified only on a positive provider result or an approved human review."""

    __tablename__ = "cases"
    __table_args__ = (
        Index("ix_cases_subject", "subject_type", "subject_id"),
        Index("ix_cases_queue", "status", "created_at"),
        {"schema": SCHEMA},
    )

    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)  # PROFESSIONAL | FIRM
    subject_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    owner_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)  # sees the case, adds evidence
    verification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(10))
    credential_claim_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), unique=True)
    specialization: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    provider_result: Mapped[str | None] = mapped_column(String(20))  # PASS | REVIEW | FAIL
    estimated_completion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[str | None] = mapped_column(String(60))
    public_reason: Mapped[str | None] = mapped_column(String(500))


class EvidenceItem(Base, UUIDPk, CreatedAt):
    """Append-only (database trigger): evidence is never edited or deleted, only added."""

    __tablename__ = "evidence_items"
    __table_args__ = {"schema": SCHEMA}

    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.cases.id"), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), nullable=False)  # ID_DOCUMENT | LICENSE | CERTIFICATE | ...
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(500))  # blob storage key (the file itself)
    content_type: Mapped[str | None] = mapped_column(String(100))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class Appeal(Base, UUIDPk, Timestamps):
    """An appeal against a FAILED or REVOKED verification (Governance playbook s.11, Onboarding s.16 "appeal path").
    One per case, time-bounded, evidence-based, decided once by a compliance officer who did not make the original decision."""

    __tablename__ = "appeals"
    __table_args__ = (Index("ix_appeals_status", "status", "created_at"), {"schema": SCHEMA})

    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.cases.id"), nullable=False, unique=True)
    filed_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    statement: Mapped[str] = mapped_column(String(2000), nullable=False)
    case_status_at_filing: Mapped[str] = mapped_column(String(20), nullable=False)  # FAILED | REVOKED
    original_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")  # OPEN | UPHELD | OVERTURNED
    decided_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(1000))
