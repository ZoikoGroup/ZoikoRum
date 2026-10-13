from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Integer, String
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
