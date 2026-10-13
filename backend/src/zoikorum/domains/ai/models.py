from __future__ import annotations
import uuid
from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from zoikorum.shared.db import Base, UUIDPk, Timestamps, CreatedAt


class PromptVersion(Base, UUIDPk, Timestamps):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_key", "version"), {"schema": "ai"})
    prompt_key: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_model: Mapped[str] = mapped_column(String(100), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    golden_tests: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class InferenceLog(Base, UUIDPk, CreatedAt):
    __tablename__ = "inference_logs"
    __table_args__ = {"schema": "ai"}
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False)


class RiskObservation(Base, UUIDPk, CreatedAt):
    __tablename__ = "risk_observations"
    __table_args__ = {"schema": "ai"}
    source_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
