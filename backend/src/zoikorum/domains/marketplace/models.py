from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk

SCHEMA = "marketplace"


class TaxonomyNode(Base, UUIDPk, Timestamps):
    """Capability taxonomy: CATEGORY -> GROUP -> SPECIALIZATION (Architecture 12.2).
    Hierarchical and versioned; specializations are never deleted, only DEPRECATED."""

    __tablename__ = "taxonomy_nodes"
    __table_args__ = (UniqueConstraint("slug"), {"schema": SCHEMA})

    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)  # CATEGORY | GROUP | SPECIALIZATION
    parent_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.taxonomy_nodes.id"))
    category_slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_credential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    regulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_insurance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    deliverable_templates: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    credential_hints: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE | DEPRECATED
    taxonomy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SavedProfessional(Base, UUIDPk, CreatedAt):
    """A buyer's shortlist ("Saved & Monitoring" on the buyer dashboard)."""

    __tablename__ = "saved_professionals"
    __table_args__ = (UniqueConstraint("identity_id", "professional_id"), {"schema": SCHEMA})

    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)


class Collection(Base, UUIDPk, Timestamps):
    """A named group of saved professionals ("Data Privacy Project", "Q1 2027 Advisory")."""

    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("identity_id", "name"), {"schema": SCHEMA})

    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class CollectionItem(Base, UUIDPk, CreatedAt):
    __tablename__ = "collection_items"
    __table_args__ = (UniqueConstraint("collection_id", "professional_id"), {"schema": SCHEMA})

    collection_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)


class SavedSearch(Base, UUIDPk, Timestamps):
    """A buyer's saved search (Buyer Dashboard s.13): filters persist; "new since you last looked" uses last_viewed_at."""

    __tablename__ = "saved_searches"
    __table_args__ = (UniqueConstraint("identity_id", "name"), {"schema": SCHEMA})

    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # search query parameters
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpecializationSuggestion(Base, UUIDPk, Timestamps):
    """A professional's "can't find mine" suggestion (AI-drafted or typed). PENDING until an admin approves it
    (new specialization), merges it into an existing one, or rejects it. Nothing goes live without that decision."""

    __tablename__ = "specialization_suggestions"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    professional_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    text: Mapped[str] = mapped_column(String(1000), nullable=False)  # the professional's own words
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_slug: Mapped[str | None] = mapped_column(String(120))
    group_slug: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    credential_likely: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)  # ai:<model>@<prompt> | fallback:keyword | manual
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    resolved_slug: Mapped[str | None] = mapped_column(String(120))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(String(500))
