"""Support schema: help requests and their conversation."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk

SCHEMA = "support"


class SupportRequest(Base, UUIDPk, Timestamps):
    """OPEN -> WAITING_ON_YOU (staff replied) -> OPEN (the person replied) ... -> RESOLVED. A first answer is due within
    one business day (``first_response_due_at``); late requests show first in the staff queue."""

    __tablename__ = "requests"
    __table_args__ = (Index("ix_support_requests_status", "status", "created_at"), {"schema": SCHEMA})

    reference: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # ZK-SUP-XXXXXXXX
    requester_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # page, engagement, error reference
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    first_response_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportMessage(Base, UUIDPk, CreatedAt):
    """Append-only conversation on a request."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_support_messages_request", "request_id", "created_at"), {"schema": SCHEMA})

    request_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.requests.id"), nullable=False)
    author_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    from_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
