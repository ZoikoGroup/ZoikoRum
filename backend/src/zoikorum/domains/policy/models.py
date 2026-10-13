"""Enterprise policy versions, evaluations and separated approval authority."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk, Versioned

SCHEMA = "policy"


class PolicyProfile(Base, UUIDPk, Timestamps, Versioned):
    __tablename__ = "profiles"
    __table_args__ = (Index("ix_policy_profiles_org", "organization_id"), {"schema": SCHEMA})

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False, default="MEDIUM")
    business_unit_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    draft_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class PolicyVersion(Base, UUIDPk, CreatedAt):
    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("profile_id", "number", name="uq_policy_version_number"), {"schema": SCHEMA})

    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("policy.profiles.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="DRAFT")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rules: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    activated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PolicyEvaluation(Base, UUIDPk, CreatedAt):
    __tablename__ = "policy_evaluations"
    __table_args__ = (Index("ix_policy_evaluations_subject", "organization_id", "subject_id", "action"), {"schema": SCHEMA})

    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    policy_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    policy_version_label: Mapped[str] = mapped_column(String(120), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(25), nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False)
    dry_run: Mapped[bool] = mapped_column(default=False, nullable=False)


class ApprovalRequest(Base, UUIDPk, Timestamps, Versioned):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint("request_key", name="uq_policy_approval_request_key"),
        Index("ix_policy_approvals_org_status", "organization_id", "status"),
        {"schema": SCHEMA},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    subject_type: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    requester_identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    workflows: Mapped[list] = mapped_column(JSONB, nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="PENDING")
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalation_role: Mapped[str] = mapped_column(String(30), nullable=False, default="ORG_ADMIN")
    escalation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_up_required: Mapped[bool] = mapped_column(default=True, nullable=False)


class ApprovalVote(Base, UUIDPk, CreatedAt):
    __tablename__ = "approval_votes"
    __table_args__ = (
        UniqueConstraint("request_id", "identity_id", name="uq_policy_approval_vote"),
        {"schema": SCHEMA},
    )

    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("policy.approval_requests.id"), nullable=False)
    step_id: Mapped[str] = mapped_column(String(100), nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    authority_role: Mapped[str] = mapped_column(String(30), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)


class ExceptionRequest(Base, UUIDPk, Timestamps, Versioned):
    __tablename__ = "exception_requests"
    __table_args__ = (Index("ix_policy_exceptions_org_status", "organization_id", "status"), {"schema": SCHEMA})

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    subject_type: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    documents: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decision_reason: Mapped[str | None] = mapped_column(String(1000))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
