"""Firm domain tables: professional firms, their people and invitations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, Timestamps, UUIDPk, Versioned

SCHEMA = "firm"


class Firm(Base, UUIDPk, Timestamps, Versioned):
    """Aggregate root. A firm cannot publish regulated offerings until it is verified and
    has a verified authorized representative (enforced when offerings arrive)."""

    __tablename__ = "firms"
    __table_args__ = {"schema": SCHEMA}

    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(200))
    registration_number: Mapped[str | None] = mapped_column(String(100))
    hq_country: Mapped[str] = mapped_column(String(2), nullable=False)
    size_band: Mapped[str | None] = mapped_column(String(10))  # 1-5 | 6-20 | 21-100 | 100+
    primary_category: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING_VERIFICATION")
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)


class FirmMember(Base, UUIDPk, Timestamps):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("firm_id", "identity_id"), {"schema": SCHEMA})

    firm_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.firms.id"), nullable=False, index=True)
    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)  # shared.auth.FirmRole
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")


class FirmInvitation(Base, UUIDPk, Timestamps):
    __tablename__ = "invitations"
    __table_args__ = (
        Index("ix_firm_invitations_pending_email", "email", postgresql_where=text("status = 'PENDING'")),
        {"schema": SCHEMA},
    )

    firm_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.firms.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
