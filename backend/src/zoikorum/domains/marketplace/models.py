from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
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
