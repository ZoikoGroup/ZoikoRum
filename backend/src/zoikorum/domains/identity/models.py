from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk, Versioned

SCHEMA = "identity"


class Identity(Base, UUIDPk, Timestamps, Versioned):
    """Aggregate root: one ZoikoID per human or service actor."""

    __tablename__ = "identities"
    __table_args__ = {"schema": SCHEMA}

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    email_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE|SUSPENDED|DELETED
    platform_roles: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False, default=list)
    # Marketplace account roles (shared.auth.Persona) - BUYER, PROFESSIONAL, FIRM_ADMIN, ENTERPRISE_ADMIN.
    personas: Mapped[list[str]] = mapped_column(ARRAY(String(30)), nullable=False, default=list)
    primary_persona: Mapped[str | None] = mapped_column(String(30))
    # Organization name captured at Firm/Enterprise signup. The firm/buyer domains create the
    # organization itself from the IDENTITY_CREATED event (next build step).
    signup_organization_name: Mapped[str | None] = mapped_column(String(200))
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(500))  # AES-GCM encrypted TOTP secret
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enterprise_federated: Mapped[bool] = mapped_column(default=False, nullable=False)


class Session(Base, UUIDPk, CreatedAt):
    """Refresh-token session. Refresh tokens rotate; reuse revokes the family."""

    __tablename__ = "sessions"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.identities.id"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    auth_strength: Mapped[str] = mapped_column(String(20), nullable=False)
    auth_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(500))


class IdentityLink(Base, UUIDPk, Timestamps):
    """Projection of the actor's memberships in other domains, built from their
    events. Used only to mint token claims - the owning domain stays authoritative."""

    __tablename__ = "identity_links"
    __table_args__ = (UniqueConstraint("identity_id", "link_type", "target_id"), {"schema": SCHEMA})

    identity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.identities.id"), nullable=False, index=True
    )
    link_type: Mapped[str] = mapped_column(String(30), nullable=False)  # PROFESSIONAL | ORG_MEMBER | FIRM_MEMBER
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False, default=list)


class ConsentRecord(Base, UUIDPk, CreatedAt):
    __tablename__ = "consent_records"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.identities.id"), nullable=False, index=True
    )
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False)  # TERMS | PRIVACY | MARKETING
    document_version: Mapped[str] = mapped_column(String(50), nullable=False)
