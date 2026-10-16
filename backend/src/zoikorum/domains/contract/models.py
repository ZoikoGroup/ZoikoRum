"""Contract domain tables: the agreement generated from an accepted proposal, its milestones, signatures, milestone
submissions (with the professional's drafts) and the buyer's reviews of them. Signatures, submissions and reviews are
append-only (database trigger): they are never edited or removed."""

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
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    policy_version_label: Mapped[str] = mapped_column(String(120), nullable=False)
    signature_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # retainer paused: no new cycles funded
    pause_reason: Mapped[str | None] = mapped_column(String(500))
    pending_change_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.change_orders.id", use_alter=True, name="fk_contracts_pending_change_order_id_change_orders"),
    )


class ChangeOrder(Base, UUIDPk, Timestamps, Versioned):
    """Append-only decision history; proposal status advances only from PROPOSED to APPROVED or REJECTED."""

    __tablename__ = "change_orders"
    __table_args__ = (
        Index("ix_change_orders_contract", "contract_id", "created_at"),
        {"schema": SCHEMA},
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contracts.id"), nullable=False
    )
    proposed_by_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    proposer_party: Mapped[str] = mapped_column(String(20), nullable=False)
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    delta: Mapped[dict] = mapped_column(JSONB, nullable=False)
    impact: Mapped[str] = mapped_column(String(1000), nullable=False)
    base_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PROPOSED")
    decided_by_identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    decision_reason: Mapped[str | None] = mapped_column(String(1000))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_version: Mapped[int | None] = mapped_column(Integer)


class TerminationRequest(Base, UUIDPk, Timestamps):
    """One side asks to end the engagement by agreement (needed while money is in escrow). PENDING -> AGREED |
    DECLINED | WITHDRAWN | LAPSED | CANCELLED (a dispute was opened). Kept as history, never deleted."""

    __tablename__ = "termination_requests"
    __table_args__ = (Index("ix_termination_requests_contract", "contract_id", "created_at"), {"schema": SCHEMA})

    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contracts.id"), nullable=False)
    requested_by_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    requester_party: Mapped[str] = mapped_column(String(20), nullable=False)  # BUYER | PROFESSIONAL
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by_identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    decision_note: Mapped[str | None] = mapped_column(String(1000))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContractRevision(Base, UUIDPk, CreatedAt):
    """Immutable terms and rendered-document snapshot for one contract version."""

    __tablename__ = "contract_revisions"
    __table_args__ = (
        UniqueConstraint("contract_id", "contract_version"),
        UniqueConstraint("change_order_id"),
        {"schema": SCHEMA},
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contracts.id"), nullable=False, index=True
    )
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.change_orders.id")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    terms: Mapped[dict] = mapped_column(JSONB, nullable=False)
    milestones: Mapped[list] = mapped_column(JSONB, nullable=False)
    terms_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


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
    """A professional's delivery for a milestone, item by item against the contract's deliverables. Append-only
    (database trigger): resubmitting adds a row with the next revision number."""

    __tablename__ = "submissions"
    __table_args__ = {"schema": SCHEMA}

    milestone_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.milestones.id"), nullable=False, index=True)
    submitted_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    files: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{name, sha256, size, contentType, key}]: the files themselves live in blob storage
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")  # 0 first delivery, 1.. resubmissions
    # [{deliverableKey, title, acceptanceCriteria, note, evidence: [FILE | LINK record], carriedOver}]; empty for one-step deliveries
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    declaration: Mapped[dict | None] = mapped_column(JSONB)  # {text, confirmedAt, ip}: what the professional confirmed when sending
    late_reason: Mapped[str | None] = mapped_column(String(500))


class SubmissionDraft(Base, UUIDPk, Timestamps, Versioned):
    """Work being prepared for a milestone, saved as the professional goes. Only the professional sees it; sending turns it
    into a Submission and removes the draft. One per milestone."""

    __tablename__ = "submission_drafts"
    __table_args__ = {"schema": SCHEMA}

    milestone_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.milestones.id"), nullable=False, unique=True)
    professional_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    items: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {deliverableKey: {note, evidence: [...]}}


class SubmissionReview(Base, UUIDPk, CreatedAt):
    """The buyer's verdict on each deliverable of one submission, and what followed (accepted or sent back). Append-only."""

    __tablename__ = "submission_reviews"
    __table_args__ = {"schema": SCHEMA}

    submission_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.submissions.id"), nullable=False, index=True)
    milestone_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.milestones.id"), nullable=False, index=True)
    reviewer_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    verdicts: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{deliverableKey, verdict: MET | CHANGES_REQUESTED, comment}]
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)  # ACCEPTED | REVISION_REQUESTED


class EngagementTask(Base, UUIDPk, Timestamps):
    """A shared to-do on an engagement (tasks.py): who does what by when. Not part of the signed terms."""

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_contract", "contract_id", "created_at"), {"schema": SCHEMA})
    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.contracts.id"), nullable=False)
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    owner: Mapped[str] = mapped_column(String(20), nullable=False)  # BUYER | PROFESSIONAL
    due_date: Mapped[date | None] = mapped_column(Date)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
