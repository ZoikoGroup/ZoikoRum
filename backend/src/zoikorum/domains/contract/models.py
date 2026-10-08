"""Contract domain tables: the agreement generated from an accepted proposal, its milestones, signatures and
milestone submissions. Signatures are append-only (database trigger): a signature is never edited or removed."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk, Versioned

SCHEMA = "contract"


class Contract(Base, UUIDPk, Timestamps, Versioned):
    """PENDING_SIGNATURE -> ACTIVE -> COMPLETED | TERMINATED; ACTIVE <-> DISPUTED. One per accepted proposal."""

    __tablename__ = "contracts"
    __table_args__ = (
        Index("ix_contracts_org", "organization_id", "created_at"),
        Index("ix_contracts_professional", "professional_id", "created_at"),
        {"schema": SCHEMA},
    )

    reference: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # ZK-ENG-XXXXXXXX, shown to people
    proposal_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    request_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    buyer_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    firm_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))  # firm the professional practised under
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    engagement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    pricing_model: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING_SIGNATURE")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    terms: Mapped[dict] = mapped_column(JSONB, nullable=False)  # snapshot of the accepted terms
    terms_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parties: Mapped[dict] = mapped_column(JSONB, nullable=False)  # names at generation time, for the document
    nda_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    document: Mapped[str] = mapped_column(Text, nullable=False)  # rendered agreement (blob storage in production)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version_label: Mapped[str] = mapped_column(String(80), nullable=False)
    signature_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Milestone(Base, UUIDPk, Timestamps, Versioned):
    """PENDING_FUNDING -> IN_PROGRESS -> SUBMITTED -> (REVISION_REQUESTED -> SUBMITTED) -> ACCEPTED. No work before funding."""

    __tablename__ = "milestones"
    __table_args__ = (UniqueConstraint("contract_id", "sequence"), {"schema": SCHEMA})

    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contracts.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    deliverable_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING_FUNDING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acceptance_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_revision_reason: Mapped[str | None] = mapped_column(String(1000))
    # Partial acceptance (Payments & Escrow s.18): the buyer offers to accept for less; only the professional's agreement releases it.
    partial_offer_minor: Mapped[int | None] = mapped_column(BigInteger)
    partial_offer_reason: Mapped[str | None] = mapped_column(String(1000))
    partial_offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_release_minor: Mapped[int | None] = mapped_column(BigInteger)  # set when accepted for less than the full amount


class Signature(Base, UUIDPk, CreatedAt):
    """Append-only receipt: who signed which version and terms, how strongly authenticated, from where."""

    __tablename__ = "signatures"
    __table_args__ = (UniqueConstraint("contract_id", "contract_version", "party"), {"schema": SCHEMA})

    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contracts.id"), nullable=False, index=True)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    party: Mapped[str] = mapped_column(String(20), nullable=False)  # BUYER | PROFESSIONAL
    signer_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    signer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    terms_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    auth_strength: Mapped[str] = mapped_column(String(20), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Submission(Base, UUIDPk, CreatedAt):
    """A professional's delivery for a milestone: a note plus file fingerprints. Never edited; resubmitting adds a row."""

    __tablename__ = "submissions"
    __table_args__ = {"schema": SCHEMA}

    milestone_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.milestones.id"), nullable=False, index=True)
    submitted_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    files: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{name, sha256, size, contentType, key}]: the files themselves live in blob storage
