"""Trust domain tables: the computed trust profile, tier history and the signals that drove it."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk

SCHEMA = "trust"


class TrustProfile(Base, UUIDPk, Timestamps):
    """Derived state: always recomputable from verification, profile and enforcement facts."""

    __tablename__ = "profiles"
    __table_args__ = {"schema": SCHEMA}

    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(1), nullable=False, default="C")
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dimensions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    explanation: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    flags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, default=list)  # risk flags: shown, never tier-changing
    engagement_suspended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recomputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TierHistory(Base, UUIDPk, CreatedAt):
    __tablename__ = "tier_history"
    __table_args__ = {"schema": SCHEMA}

    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    from_tier: Mapped[str] = mapped_column(String(1), nullable=False)
    to_tier: Mapped[str] = mapped_column(String(1), nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_event_type: Mapped[str] = mapped_column(String(120), nullable=False)


class TrustSignal(Base, UUIDPk, CreatedAt):
    """A fact that fed the trust computation (one per source event)."""

    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("professional_id", "source_event_id"), {"schema": SCHEMA})

    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    source_event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(30), nullable=False)  # VERIFICATION | PROFILE | ENFORCEMENT | RISK_FLAG
    adverse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
