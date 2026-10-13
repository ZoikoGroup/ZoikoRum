"""Infrastructure tables in the ``platform`` schema.

These hold no business data: outbox (events awaiting publish), inbox (events a
consumer already processed), consumer failures / dead letters, idempotency
keys, and durable timers.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, UUIDPk

SCHEMA = "platform"


class OutboxEvent(Base, CreatedAt):
    """Transactional outbox (Handbook 21.1). Written in the same TX as the state change."""

    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_unpublished", "seq", postgresql_where=text("published_at IS NULL")),
        {"schema": SCHEMA},
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(100))
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InboxEntry(Base, CreatedAt):
    """Consumer idempotency (Handbook 21.2). One row per (consumer, event)."""

    __tablename__ = "inbox"
    __table_args__ = (UniqueConstraint("consumer", "event_id"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(150), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class ConsumerFailure(Base, UUIDPk, CreatedAt):
    """Retry queue + dead-letter queue for event consumers.

    status: RETRYING -> (DEAD | RESOLVED). Financial events never auto-replay
    once DEAD; an operator must authorise replay (Architecture 6.4).
    """

    __tablename__ = "consumer_failures"
    __table_args__ = (UniqueConstraint("consumer", "event_id"), {"schema": SCHEMA})

    consumer: Mapped[str] = mapped_column(String(150), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RETRYING")
    financial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base, CreatedAt):
    """API idempotency (Handbook ch. 12). Stored in the same TX as the mutation."""

    __tablename__ = "idempotency_keys"
    __table_args__ = {"schema": SCHEMA}

    scope: Mapped[str] = mapped_column(String(300), primary_key=True)  # actor + route + key
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict | list | None] = mapped_column(JSONB)


class Timer(Base, UUIDPk, CreatedAt):
    """Durable timer: deadlines, expiries, SLA escalations, reminders.

    A timer fires at most once; firing runs the registered handler in its own
    transaction. ``key`` makes scheduling idempotent per business object.
    """

    __tablename__ = "timers"
    __table_args__ = (
        UniqueConstraint("kind", "key"),
        Index("ix_timers_due", "fire_at", postgresql_where=text("fired_at IS NULL AND cancelled_at IS NULL")),
        {"schema": SCHEMA},
    )

    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
