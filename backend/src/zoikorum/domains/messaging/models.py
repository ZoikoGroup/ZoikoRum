"""Context-bound communication. Message and attachment content is append-only."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk

SCHEMA = "messaging"


class Thread(Base, UUIDPk, Timestamps):
    __tablename__ = "threads"
    __table_args__ = (UniqueConstraint("context_type", "context_id"), {"schema": SCHEMA})
    context_type: Mapped[str] = mapped_column(String(30), nullable=False)
    context_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked: Mapped[bool] = mapped_column(nullable=False, default=False)
    lock_reason: Mapped[str | None] = mapped_column(String(300))


class DisputeContext(Base):
    """Event projection used to bind dispute threads without depending on dispute internals."""

    __tablename__ = "dispute_contexts"
    __table_args__ = (
        Index("ix_messaging_dispute_contract_open", "contract_id", "is_open"),
        {"schema": SCHEMA},
    )
    dispute_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    initiated_by_identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    is_open: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")


class ReadPosition(Base, UUIDPk, Timestamps):
    __tablename__ = "read_positions"
    __table_args__ = (UniqueConstraint("thread_id", "identity_id"), {"schema": SCHEMA})
    thread_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("messaging.threads.id"), nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Attachment(Base, UUIDPk, CreatedAt):
    __tablename__ = "attachments"
    __table_args__ = (UniqueConstraint("thread_id", "name", "file_version"), {"schema": SCHEMA})
    thread_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("messaging.threads.id"), nullable=False, index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_version: Mapped[int] = mapped_column(Integer, nullable=False)


class Message(Base, UUIDPk, CreatedAt):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("thread_id", "sequence"), UniqueConstraint("thread_id", "source_event_id"),
                      Index("ix_messages_thread_created", "thread_id", "created_at"), {"schema": SCHEMA})
    thread_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("messaging.threads.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    sender_identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    sender_name: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
