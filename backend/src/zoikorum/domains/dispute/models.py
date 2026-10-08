"""Dispute domain tables (Dispute Resolution doc, BUILD_SPEC s.dispute).

A case covers one or more milestones of one contract. Evidence is append-only (database trigger) and fingerprinted.
Resolution proposals are structured (release / refund per milestone), never free-form chat. The timeline is the
case's visible history; the audit ledger keeps the tamper-evident record.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk, Versioned

SCHEMA = "dispute"


class DisputeCase(Base, UUIDPk, Timestamps, Versioned):
    """EVIDENCE_COLLECTION -> DIRECT_RESOLUTION -> MEDIATION -> DECIDED -> ENFORCED -> CLOSED (conduct/compliance skip direct)."""

    __tablename__ = "cases"
    __table_args__ = (Index("ix_dispute_cases_contract", "contract_id", "status"), {"schema": SCHEMA})

    reference: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # ZK-DSP-XXXXXXXX
    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    contract_reference: Mapped[str] = mapped_column(String(20), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    milestone_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # immutable after submission
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    desired_outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    context: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    initiator_party: Mapped[str] = mapped_column(String(20), nullable=False)  # BUYER | PROFESSIONAL | PLATFORM
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="EVIDENCE_COLLECTION")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    disputed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    evidence_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_complete: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # parties that finished
    direct_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mediator_identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    recommendation: Mapped[dict | None] = mapped_column(JSONB)  # {outcome, allocations, summary, citations, acceptedBy[]}
    pending_decision: Mapped[dict | None] = mapped_column(JSONB)  # mediator's platform decision awaiting LEGAL approval
    decision: Mapped[dict | None] = mapped_column(JSONB)  # final decision package
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceItem(Base, UUIDPk, CreatedAt):
    """Append-only (database trigger): evidence is never edited or deleted, only added."""

    __tablename__ = "evidence_items"
    __table_args__ = {"schema": SCHEMA}

    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.cases.id"), nullable=False, index=True)
    party: Mapped[str] = mapped_column(String(20), nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{name, sha256, size, contentType, key}]: the files themselves live in blob storage


class ResolutionProposal(Base, UUIDPk, Timestamps):
    """OPEN -> ACCEPTED | REJECTED | SUPERSEDED. Structured: outcome + release/refund per milestone."""

    __tablename__ = "resolution_proposals"
    __table_args__ = {"schema": SCHEMA}

    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.cases.id"), nullable=False, index=True)
    party: Mapped[str] = mapped_column(String(20), nullable=False)
    proposed_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    allocations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TimelineEntry(Base, UUIDPk, CreatedAt):
    """What both parties see on the visual timeline (Dispute doc s.15)."""

    __tablename__ = "timeline"
    __table_args__ = {"schema": SCHEMA}

    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.cases.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)  # "Buyer (Lennox)", "Mediator", "System"
    text: Mapped[str] = mapped_column(String(500), nullable=False)
