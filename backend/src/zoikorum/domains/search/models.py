"""Search read model: one document per professional, rebuilt from events only (CQRS).

It can be dropped and rebuilt at any time (POST /v1/admin/search/reindex). Postgres full-text
search today; OpenSearch can rebuild from the same events later (ADR-005).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, Timestamps, UUIDPk

SCHEMA = "search"


class ProfessionalDocument(Base, UUIDPk, Timestamps):
    __tablename__ = "professional_documents"
    __table_args__ = (
        Index("ix_professional_documents_document", "document", postgresql_using="gin"),
        Index("ix_professional_documents_specializations", "specializations", postgresql_using="gin"),
        {"schema": SCHEMA},
    )

    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # published, not suspended
    visibility_reduced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100))
    years_experience_band: Mapped[str | None] = mapped_column(String(10))
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, default=list)

    categories: Mapped[list[str]] = mapped_column(ARRAY(String(120)), nullable=False, default=list)
    primary_specialization: Mapped[str | None] = mapped_column(String(120))
    specializations: Mapped[list[str]] = mapped_column(ARRAY(String(120)), nullable=False, default=list)
    specialization_names: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # slug -> display name

    engagement_types: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    delivery_modes: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    pricing_models: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    availability: Mapped[str] = mapped_column(String(20), nullable=False)  # effective (AT_CAPACITY overrides)
    served_jurisdictions: Mapped[list[str]] = mapped_column(ARRAY(String(2)), nullable=False, default=list)
    licensed_jurisdictions: Mapped[list[str]] = mapped_column(ARRAY(String(2)), nullable=False, default=list)

    tier: Mapped[str] = mapped_column(String(1), nullable=False, default="C")
    trust_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dimensions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    verified_credentials: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    verified_jurisdictions: Mapped[list[str]] = mapped_column(ARRAY(String(2)), nullable=False, default=list,
                                                              server_default="{}")  # backed by a verified check

    offering_titles: Mapped[list[str]] = mapped_column(ARRAY(String(150)), nullable=False, default=list)
    starting_price_minor: Mapped[int | None] = mapped_column(BigInteger)
    price_currency: Mapped[str | None] = mapped_column(String(3))
    bio_excerpt: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(200))

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # staleness indicator
    document: Mapped[str] = mapped_column(TSVECTOR, nullable=False)
