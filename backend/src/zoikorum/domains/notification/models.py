"""Notification domain tables. First slice: per-person channel preferences (delivery comes later)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk

SCHEMA = "notification"


class Preference(Base, UUIDPk, Timestamps):
    """Channel opt-ins. Security and enforcement notices are always sent by email, whatever is chosen here."""

    __tablename__ = "preferences"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    marketing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Notification(Base, UUIDPk, Timestamps):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("source_event_id", "identity_id"),
        Index("ix_notifications_recipient", "identity_id", "created_at"), {"schema": SCHEMA})
    source_event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    notice: Mapped[dict | None] = mapped_column(JSONB)
    in_app: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str] = mapped_column(String(20), nullable=False)
    email_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))


class WebhookEndpoint(Base, UUIDPk, Timestamps):
    __tablename__ = "webhook_endpoints"
    __table_args__ = {"schema": SCHEMA}
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    event_types: Mapped[list] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WebhookDelivery(Base, UUIDPk, Timestamps):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("endpoint_id", "source_event_id"), {"schema": SCHEMA})
    endpoint_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("notification.webhook_endpoints.id"), nullable=False)
    source_event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryAttempt(Base, UUIDPk, CreatedAt):
    __tablename__ = "delivery_attempts"
    __table_args__ = {"schema": SCHEMA}
    delivery_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("notification.webhook_deliveries.id"), nullable=False, index=True)
    response_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(300))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
