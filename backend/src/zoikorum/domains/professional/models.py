"""Professional domain tables: the transaction-ready professional identity (Professional Profile doc)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, Timestamps, UUIDPk, Versioned

SCHEMA = "professional"


class Professional(Base, UUIDPk, Timestamps, Versioned):
    """Aggregate root. Lifecycle: DRAFT -> PUBLISHED <-> UNPUBLISHED; any -> SUSPENDED (enforcement)."""

    __tablename__ = "professionals"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    firm_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")

    # Profile basics (Onboarding s.7)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200))  # as on ID; never shown publicly
    headline: Mapped[str | None] = mapped_column(String(120))  # primary role title, e.g. "Fractional CFO"
    years_experience_band: Mapped[str | None] = mapped_column(String(10))  # 0-2 | 3-5 | 6-10 | 11-15 | 16+
    bio: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, default=list)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(300))

    # Services & specializations (s.8): taxonomy slugs only
    primary_category: Mapped[str | None] = mapped_column(String(120))
    primary_specialization: Mapped[str | None] = mapped_column(String(120))
    secondary_specializations: Mapped[list[str]] = mapped_column(ARRAY(String(120)), nullable=False, default=list)

    # Engagement, pricing, availability (s.9) - indicative, never binding
    engagement_types: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    delivery_modes: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    pricing_models: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    rate_minor: Mapped[int | None] = mapped_column(BigInteger)
    rate_currency: Mapped[str | None] = mapped_column(String(3))
    rate_unit: Mapped[str | None] = mapped_column(String(10))  # HOUR | DAY | MONTH | PROJECT
    availability: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_SPECIFIED")
    max_concurrent_engagements: Mapped[int | None] = mapped_column(Integer)
    temporarily_unavailable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weekly_hours: Mapped[int | None] = mapped_column(Integer)  # hours a week open for Zoikorum work (Professional Dashboard s.13)
    active_engagements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Jurisdiction & eligibility (s.13)
    served_jurisdictions: Mapped[list[str]] = mapped_column(ARRAY(String(2)), nullable=False, default=list)
    licensed_jurisdictions: Mapped[list[str]] = mapped_column(ARRAY(String(2)), nullable=False, default=list)
    cross_border_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Publishing (s.17)
    accuracy_attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visibility_reduced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Profile photo (Onboarding s.7): bytes in blob storage, only the key/type/hash here
    photo_key: Mapped[str | None] = mapped_column(String(200))
    photo_content_type: Mapped[str | None] = mapped_column(String(30))
    photo_sha256: Mapped[str | None] = mapped_column(String(64))


class CredentialClaim(Base, UUIDPk, Timestamps):
    """A credential the professional claims (s.12). Shown as 'Self-reported' until verified;
    FAILED claims are hidden from the public profile."""

    __tablename__ = "credential_claims"
    __table_args__ = {"schema": SCHEMA}

    professional_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.professionals.id"), nullable=False, index=True
    )
    credential_type: Mapped[str] = mapped_column(String(20), nullable=False)  # LICENSE|CERTIFICATION|MEMBERSHIP|DEGREE
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    issuing_body: Mapped[str] = mapped_column(String(200), nullable=False)
    registration_number: Mapped[str | None] = mapped_column(String(100))
    jurisdiction: Mapped[str | None] = mapped_column(String(10))
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    specialization: Mapped[str | None] = mapped_column(String(120))  # taxonomy slug this credential supports
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SELF_REPORTED")
    # SELF_REPORTED | PENDING | VERIFIED | FAILED | EXPIRED | REVOKED | WITHDRAWN


class Offering(Base, UUIDPk, Timestamps, Versioned):
    """A structured, contract-ready service (Professional Dashboard s.5-6). Paused != deleted."""

    __tablename__ = "offerings"
    __table_args__ = {"schema": SCHEMA}

    professional_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.professionals.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    specialization: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    deliverables: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    engagement_types: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    pricing_model: Mapped[str] = mapped_column(String(20), nullable=False)  # HOURLY|FIXED|RETAINER|CUSTOM
    starting_price_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    typical_duration: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")  # DRAFT | ACTIVE | PAUSED
