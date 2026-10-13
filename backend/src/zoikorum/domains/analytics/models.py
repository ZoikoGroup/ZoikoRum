from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Identity, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from zoikorum.shared.db import Base, UUIDPk, CreatedAt


class EventFact(Base, UUIDPk, CreatedAt):
    """Rebuildable reporting facts sourced exclusively from domain events."""
    __tablename__ = "event_facts"
    __table_args__ = {"schema": "analytics"}
    source_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    professional_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
