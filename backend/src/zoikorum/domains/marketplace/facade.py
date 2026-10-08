"""Marketplace facade - read-only interface other domains use.

The capability taxonomy is hierarchical and versioned:
category (finance-and-accounting) -> group (finance-leadership) -> specialization (fractional-cfo).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from zoikorum.domains.marketplace.models import SavedProfessional, TaxonomyNode
from zoikorum.shared.errors import ValidationFailed


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
    requires_insurance: bool = False  # Tier A needs verified professional indemnity insurance


@dataclass(frozen=True)
class CategoryInfo:
    slug: str
    name: str
    taxonomy_version: int


async def get_specializations(session: AsyncSession, slugs: list[str]) -> dict[str, SpecializationInfo]:
    if not slugs:
        return {}
    group = aliased(TaxonomyNode)
    rows = (
        await session.execute(
            select(TaxonomyNode, group.slug)
            .join(group, group.id == TaxonomyNode.parent_id)
            .where(TaxonomyNode.slug.in_(slugs), TaxonomyNode.level == "SPECIALIZATION", TaxonomyNode.status == "ACTIVE")
        )
    ).all()
    return {
        n.slug: SpecializationInfo(n.slug, n.name, g_slug, n.category_slug, n.requires_credential, n.regulated,
                                   tuple(n.deliverable_templates), tuple(n.credential_hints), n.requires_insurance)
        for n, g_slug in rows
    }


async def validate_specializations(session: AsyncSession, slugs: list[str]) -> None:
    """Raise ValidationFailed if any slug is not an active taxonomy specialization."""
    found = await get_specializations(session, slugs)
    unknown = sorted(set(slugs) - set(found))
    if unknown:
        raise ValidationFailed(f"Not a Zoikorum specialization: {', '.join(unknown)}", code="UNKNOWN_SPECIALIZATION")


async def get_category(session: AsyncSession, slug: str) -> CategoryInfo | None:
    n = await session.scalar(select(TaxonomyNode).where(TaxonomyNode.slug == slug, TaxonomyNode.level == "CATEGORY"))
    return CategoryInfo(n.slug, n.name, n.taxonomy_version) if n else None


async def specialization_names(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(TaxonomyNode.slug, TaxonomyNode.name).where(TaxonomyNode.level == "SPECIALIZATION"))).all()
    return dict(rows)


async def saved_by(session: AsyncSession, professional_id: uuid.UUID) -> list[uuid.UUID]:
    """Identity ids that saved this professional (availability alerts)."""
    return list((await session.scalars(select(SavedProfessional.identity_id).where(
        SavedProfessional.professional_id == professional_id))).all())
