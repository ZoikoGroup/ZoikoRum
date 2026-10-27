"""Proposal domain tables: a buyer's request to one professional, and that professional's proposal.

A buyer may send the same requirement to several chosen professionals (up to five by default) at once (RFP wireframe s.4:
"Request Proposal for selected professional(s)"). Each professional gets their own request row; the rows share a
``group_id`` so the buyer can compare the proposals, and accepting one closes the others.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, Timestamps, UUIDPk, Versioned

SCHEMA = "proposal"


class ProposalRequest(Base, UUIDPk, Timestamps, Versioned):
    """DRAFT -> OPEN -> PROPOSAL_RECEIVED -> CLOSED; OPEN -> DECLINED; any open state -> CANCELLED."""

    __tablename__ = "requests"
    __table_args__ = (
        Index("ix_requests_org", "organization_id", "created_at"),
        Index("ix_requests_professional", "professional_id", "status", "created_at"),
        Index("ix_requests_group", "group_id"),
        {"schema": SCHEMA},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))  # buyer's contracting entity
    buyer_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    offering_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    group_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    service: Mapped[str] = mapped_column(String(200), nullable=False)
    specialization: Mapped[str | None] = mapped_column(String(120))
    engagement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    business_context: Mapped[str | None] = mapped_column(String(20))
    objective: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[str] = mapped_column(String(1200), nullable=False, default="")
    desired_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    estimated_duration: Mapped[str] = mapped_column(String(20), nullable=False)
    budget_min_minor: Mapped[int | None] = mapped_column(BigInteger)
    budget_max_minor: Mapped[int | None] = mapped_column(BigInteger)
    budget_currency: Mapped[str | None] = mapped_column(String(3))
    delivery_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="REMOTE")
    location: Mapped[str | None] = mapped_column(String(200))
    nda_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nda_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{name, sha256, size, contentType, key}]: the files themselves live in blob storage
    # Scope builder (RFP wireframe s.6-7): deliverables checklist, dependencies, commercial preferences.
    deliverables: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # titles, from templates or custom
    custom_deliverables: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # the buyer's own wording: flagged
    dependencies: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # BUYER_DATA | THIRD_PARTY_ACCESS | INTERNAL_APPROVALS
    # Structured success criteria (Request wireframe): "What does done look like" and "How will it be measured". Optional;
    # carried into every proposal and into the contract scope.
    success_definition: Mapped[str | None] = mapped_column(String(1000))
    success_measures: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    pricing_preferences: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # HOURLY | FIXED | RETAINER | OPEN
    payment_cadence: Mapped[str | None] = mapped_column(String(20))  # MILESTONE | MONTHLY | COMPLETION
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[str | None] = mapped_column(String(60))
    reason_note: Mapped[str | None] = mapped_column(String(500))


class Proposal(Base, UUIDPk, Timestamps, Versioned):
    """One per request. DRAFT -> SUBMITTED -> REVISION_REQUESTED -> SUBMITTED ... -> ACCEPTED | REJECTED | WITHDRAWN | EXPIRED."""

    __tablename__ = "proposals"
    __table_args__ = (
        Index("ix_proposals_professional", "professional_id", "status"),
        Index("ix_proposals_org", "organization_id", "status"),
        {"schema": SCHEMA},
    )

    request_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.requests.id"),
                                                  nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    buyer_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    scope_alignment: Mapped[str] = mapped_column(String(20), nullable=False, default="CONFIRMED")  # CONFIRMED | ADJUSTED
    scope_notes: Mapped[str | None] = mapped_column(String(1000))  # optional free-text context for the scope changes
    # Tracked scope suggestions (Engagement wireframe): [{id, kind, target, proposed, reason, status, decidedAt, decidedBy,
    # note}], kind ADD_DELIVERABLE | REMOVE_DELIVERABLE | MODIFY_DELIVERABLE | TIMELINE | BUDGET; the buyer accepts or
    # rejects each one (PENDING -> ACCEPTED | REJECTED); accepted ones become part of the agreed scope.
    scope_changes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    deliverables: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    milestones: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Optional attachments (RFP flow s.8: "portfolio items or supporting docs"): stored files, at most 3.
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    pricing_model: Mapped[str] = mapped_column(String(20), nullable=False, default="FIXED")
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    assumptions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    exclusions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    valid_until: Mapped[date | None] = mapped_column(Date)
    revision_requests: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{at, changes, note}]
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The professional confirmed they can take this on although at capacity (their explicit override).
    capacity_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    reason_code: Mapped[str | None] = mapped_column(String(60))
    reason_note: Mapped[str | None] = mapped_column(String(500))
    terms_hash: Mapped[str | None] = mapped_column(String(64))


# ---- Open briefs (briefs.py): a need described once; matching professionals say they are interested ----------------
class OpenBrief(Base, UUIDPk, Timestamps):
    """OPEN -> CLOSED (by the buyer, or when closes_at passes)."""

    __tablename__ = "open_briefs"
    __table_args__ = (Index("ix_open_briefs_match", "specialization", "status", "closes_at"),
                      Index("ix_open_briefs_org", "organization_id", "created_at"), {"schema": SCHEMA})

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    buyer_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)  # the buyer organisation's, for matching
    service: Mapped[str] = mapped_column(String(200), nullable=False)
    specialization: Mapped[str] = mapped_column(String(120), nullable=False)
    objective: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[str] = mapped_column(String(1200), nullable=False, default="")
    desired_start_date: Mapped[date | None] = mapped_column(Date)
    estimated_duration: Mapped[str | None] = mapped_column(String(30))
    budget_max_minor: Mapped[int | None] = mapped_column(BigInteger)
    budget_currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BriefInterest(Base, UUIDPk, Timestamps):
    __tablename__ = "brief_interests"
    __table_args__ = (UniqueConstraint("brief_id", "professional_id"), {"schema": SCHEMA})

    brief_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.open_briefs.id"), nullable=False, index=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
