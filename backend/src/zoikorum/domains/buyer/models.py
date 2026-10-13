"""Buyer domain tables: organizations and the people who act for them."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, Timestamps, UUIDPk, Versioned

SCHEMA = "buyer"


class Organization(Base, UUIDPk, Timestamps, Versioned):
    """Aggregate root (BuyerOrganization). Every buyer acts through one:
    INDIVIDUAL for a single buyer, ENTERPRISE for procurement teams."""

    __tablename__ = "organizations"
    __table_args__ = {"schema": SCHEMA}

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    org_type: Mapped[str] = mapped_column(String(20), nullable=False)  # INDIVIDUAL | BUSINESS | ENTERPRISE
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    business_context: Mapped[str | None] = mapped_column(String(30))  # STARTUP|SME|MID_MARKET|ENTERPRISE|INDIVIDUAL
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    industry: Mapped[str | None] = mapped_column(String(80))
    time_zone: Mapped[str | None] = mapped_column(String(64))


class OrgMember(Base, UUIDPk, Timestamps):
    """A person's membership, roles and approval authority (spend limit) in an organization."""

    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("organization_id", "identity_id"), {"schema": SCHEMA})

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.organizations.id"), nullable=False, index=True
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)  # snapshot for team lists
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    # Approval authority. NULL = no limit configured (unlimited for ORG_ADMIN, none for others).
    spend_limit_minor: Mapped[int | None] = mapped_column(BigInteger)
    spend_limit_currency: Mapped[str | None] = mapped_column(String(3))
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE | REMOVED


class Invitation(Base, UUIDPk, Timestamps):
    __tablename__ = "invitations"
    __table_args__ = (
        Index("ix_invitations_pending_email", "email", postgresql_where=text("status = 'PENDING'")),
        {"schema": SCHEMA},
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    spend_limit_minor: Mapped[int | None] = mapped_column(BigInteger)
    spend_limit_currency: Mapped[str | None] = mapped_column(String(3))
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING|ACCEPTED|DECLINED|REVOKED
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BusinessUnit(Base, UUIDPk, Timestamps):
    __tablename__ = "business_units"
    __table_args__ = (UniqueConstraint("organization_id", "name"), {"schema": SCHEMA})

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.business_units.id"))


class CostCenter(Base, UUIDPk, Timestamps):
    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("organization_id", "code"), {"schema": SCHEMA})

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.organizations.id"), nullable=False, index=True
    )
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.business_units.id"))
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    quarterly_budget_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))


class BillingContact(Base, UUIDPk, Timestamps):
    """Who receives invoices and billing notices for the organisation: one primary, optionally one backup."""

    __tablename__ = "billing_contacts"
    __table_args__ = (UniqueConstraint("organization_id", "identity_id"), {"schema": SCHEMA})

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.organizations.id"), nullable=False, index=True
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False)
