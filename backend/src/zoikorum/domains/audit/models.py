from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk

SCHEMA = "audit"


class AuditRecord(Base, UUIDPk, CreatedAt):
    """Insert-only. hash = sha256(prev_hash || canonical(record)). Never UPDATE/DELETE."""

    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_object", "object_type", "object_id"),
        Index("ix_audit_correlation", "correlation_id"),
        Index("ix_audit_tenant_time", "tenant_id", "occurred_at"),
        {"schema": SCHEMA},
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True, nullable=False)
    source_event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(100))
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    auth_strength: Mapped[str | None] = mapped_column(String(20))
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(100))
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(100))
    policy_version: Mapped[str | None] = mapped_column(String(100))
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class ExportJob(Base, UUIDPk, Timestamps):
    __tablename__ = "export_jobs"
    __table_args__ = {"schema": SCHEMA}

    requested_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING|COMPLETED|FAILED
    format: Mapped[str] = mapped_column(String(10), nullable=False, default="json")
    record_count: Mapped[int | None] = mapped_column(BigInteger)
    content: Mapped[str | None] = mapped_column(Text)  # moves to S3 Object Lock in production
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    chain_head_hash: Mapped[str | None] = mapped_column(String(64))
