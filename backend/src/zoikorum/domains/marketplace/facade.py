"""Marketplace facade - CONTRACT. Signatures and DTOs are fixed; implement bodies.

The capability taxonomy is hierarchical and versioned:
category (finance-accounting) -> group (finance-leadership) -> specialization (fractional-cfo).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class SpecializationInfo:
    slug: str
    name: str
    group_slug: str
    category_slug: str
    requires_credential: bool  # e.g. CPA-style licensed work
    regulated: bool  # regulated work => Tier A typically required by policy
    deliverable_templates: tuple[str, ...]
    credential_hints: tuple[str, ...]  # e.g. ("CPA", "CA", "ACCA")


@dataclass(frozen=True)
class CategoryInfo:
    slug: str
    name: str
    taxonomy_version: int


async def get_specializations(session: AsyncSession, slugs: list[str]) -> dict[str, SpecializationInfo]:
    raise NotImplementedError


async def validate_specializations(session: AsyncSession, slugs: list[str]) -> None:
    """Raise ValidationFailed if any slug is not an active taxonomy specialization."""
    raise NotImplementedError


async def get_category(session: AsyncSession, slug: str) -> CategoryInfo | None:
    raise NotImplementedError


async def saved_by(session: AsyncSession, professional_id: uuid.UUID) -> list[uuid.UUID]:
    """Identity ids that saved this professional (availability alerts)."""
    raise NotImplementedError
