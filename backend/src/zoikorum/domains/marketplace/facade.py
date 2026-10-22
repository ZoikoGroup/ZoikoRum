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


async def specialization_catalog(session: AsyncSession) -> list:
    """Every active specialization with its group and category, for AI matching (ai.facade.CatalogEntry)."""
    from zoikorum.domains.ai import facade as ai_facade

    nodes = (await session.scalars(select(TaxonomyNode).where(TaxonomyNode.status == "ACTIVE"))).all()
    by_id = {n.id: n for n in nodes}
    out = []
    for n in nodes:
        if n.level != "SPECIALIZATION":
            continue
        group = by_id.get(n.parent_id)
        cat = by_id.get(group.parent_id) if group else None
        if group and cat:
            out.append(ai_facade.CatalogEntry(slug=n.slug, name=n.name, category_slug=cat.slug, category_name=cat.name,
                                              group_slug=group.slug, group_name=group.name))
    return out


async def saved_by(session: AsyncSession, professional_id: uuid.UUID) -> list[uuid.UUID]:
    """Identity ids that saved this professional (availability alerts)."""
    return list((await session.scalars(select(SavedProfessional.identity_id).where(
        SavedProfessional.professional_id == professional_id))).all())



async def pending_specialization_names(session: AsyncSession, professional_id: uuid.UUID) -> list[str]:
    """Suggested specializations still waiting for an admin (shown on the profile as "under review")."""
    from zoikorum.domains.marketplace.service import pending_names

    return await pending_names(session, professional_id)


async def search_specializations(session: AsyncSession, q: str, limit: int = 6) -> list[dict]:
    """Active specializations whose name contains the text (autocomplete), names starting with it first."""
    from sqlalchemy import case

    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = (await session.execute(select(TaxonomyNode.slug, TaxonomyNode.name).where(
        TaxonomyNode.level == "SPECIALIZATION", TaxonomyNode.status == "ACTIVE", TaxonomyNode.name.ilike(like, escape="\\"))
        .order_by(case((TaxonomyNode.name.ilike(q + "%"), 0), else_=1), TaxonomyNode.name).limit(limit))).all()
    return [{"slug": slug, "name": name} for slug, name in rows]


async def category_specializations(session: AsyncSession, category_slug: str) -> list[str]:
    rows = (await session.scalars(select(TaxonomyNode.slug).where(
        TaxonomyNode.category_slug == category_slug, TaxonomyNode.level == "SPECIALIZATION", TaxonomyNode.status == "ACTIVE"))).all()
    return list(rows)


async def all_specializations(session: AsyncSession) -> list[dict]:
    """Every active specialization (slug, name), for search's concept matching."""
    rows = (await session.execute(select(TaxonomyNode.slug, TaxonomyNode.name).where(
        TaxonomyNode.level == "SPECIALIZATION", TaxonomyNode.status == "ACTIVE"))).all()
    return [{"slug": s, "name": n} for s, n in rows]


async def suggestion_exists(session: AsyncSession, suggestion_id: uuid.UUID) -> bool:
    """A specialization suggestion with this id (staff case ownership checks the case is real)."""
    from zoikorum.domains.marketplace.models import SpecializationSuggestion

    return await session.get(SpecializationSuggestion, suggestion_id) is not None
