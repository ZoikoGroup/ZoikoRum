from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from zoikorum.shared.db import Base, UUIDPk, Timestamps, Versioned


class EnforcementCase(Base, UUIDPk, Timestamps, Versioned):
    __tablename__ = "enforcement_cases"
    __table_args__ = {"schema": "admin"}
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    signal_source: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="TRIAGE")
    action: Mapped[str | None] = mapped_column(String(40))
    notice: Mapped[dict | None] = mapped_column(JSONB)
    opened_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approvals: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    appeal: Mapped[dict | None] = mapped_column(JSONB)
    # Level 2 mandatory remediation: [{task, done, doneAt, note, confirmedBy, confirmedAt}] (Governance playbook s.6)
    remediation: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")


class UserReport(Base, UUIDPk, Timestamps):
    """A buyer or professional reporting a profile, person, organisation, review or message (Trust & Safety Charter:
    user reporting pathway). Each report feeds an enforcement case; the reported person is never told who reported.
    ``confidential``: the reporter's name is hidden from case handlers too (only Risk Lead and Legal can see it)."""

    __tablename__ = "user_reports"
    __table_args__ = {"schema": "admin"}

    reporter_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)  # PROFESSIONAL|IDENTITY|ORGANIZATION|REVIEW|MESSAGE
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    possible_retaliation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RECEIVED")  # RECEIVED | CLOSED
    outcome: Mapped[str | None] = mapped_column(String(20))  # ACTION_TAKEN | NO_ACTION (no details: the subject's privacy)


class Incident(Base, UUIDPk, Timestamps):
    """Incident register (Regulator assurance s.11): what happened, severity, containment, who was notified, root cause,
    remediation, and the post-incident review. OPEN -> CONTAINED -> RESOLVED -> CLOSED."""

    __tablename__ = "incidents"
    __table_args__ = {"schema": "admin"}

    reference: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # ZK-INC-XXXXXX
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # SECURITY | DATA | PAYMENTS | OUTAGE | SAFETY | OTHER
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # SEV1 (critical) .. SEV4 (minor)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    summary: Mapped[str] = mapped_column(String(4000), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    timeline: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{at, by, note}] append-only by the API
    notifications: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{party, at, by, note}]
    root_cause: Mapped[str | None] = mapped_column(String(4000))
    remediation: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{task, done, doneAt, by}]
    review: Mapped[str | None] = mapped_column(String(8000))  # post-incident review


class FeatureSwitch(Base, UUIDPk, Timestamps):
    """An operational switch (admin/switches.py): while ``paused``, its kind of action is refused or deferred."""
    __tablename__ = "feature_switches"
    __table_args__ = {"schema": "admin"}
    key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class FeatureFlag(Base, UUIDPk, Timestamps):
    """Gradual rollout of a feature defined in code (admin/flags.py): a percentage of people, plus named organisations."""
    __tablename__ = "feature_flags"
    __table_args__ = {"schema": "admin"}
    key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    rollout_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    organization_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # always on for these
    reason: Mapped[str | None] = mapped_column(String(500))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
