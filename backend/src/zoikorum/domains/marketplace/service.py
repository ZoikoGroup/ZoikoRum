"""Marketplace: capability taxonomy and buyers' saved professionals."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.marketplace.models import SavedProfessional, TaxonomyNode
from zoikorum.domains.marketplace.schemas import SavedOut, SpecializationAdminOut, SpecializationIn, SpecializationPatch
from zoikorum.domains.marketplace.taxonomy_data import default_taxonomy_rows, slugify
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import Conflict, NotFound
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event


async def seed_default_taxonomy(session: AsyncSession) -> None:
    """Idempotent: inserts missing nodes, never overwrites edited ones."""
    for row in default_taxonomy_rows():
        await session.execute(pg_insert(TaxonomyNode).values(**row).on_conflict_do_nothing(index_elements=["slug"]))


def _node(n: TaxonomyNode) -> dict:
    return {"slug": n.slug, "name": n.name, "requiresCredential": n.requires_credential, "regulated": n.regulated,
            "requiresInsurance": n.requires_insurance,
            "deliverableTemplates": list(n.deliverable_templates), "credentialHints": list(n.credential_hints)}


async def tree(session: AsyncSession, category_slug: str | None = None) -> list[dict]:
    """Category -> groups -> specializations, in display order. Public (used before sign-in)."""
    stmt = select(TaxonomyNode).where(TaxonomyNode.status == "ACTIVE").order_by(TaxonomyNode.sort_order, TaxonomyNode.name)
    if category_slug:
        stmt = stmt.where(TaxonomyNode.category_slug == category_slug)
    nodes = (await session.scalars(stmt)).all()
    if category_slug and not nodes:
        raise NotFound("Category not found")
    children: dict = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n)
    out = []
    for cat in children.get(None, []):
        groups = []
        for g in children.get(cat.id, []):
            groups.append({**_node(g), "specializations": [_node(s) for s in children.get(g.id, [])]})
        out.append({**_node(cat), "version": cat.taxonomy_version, "groups": groups})
    return out


# ---- Admin: taxonomy changes (PLATFORM_ADMIN) ---------------------------------
# Specializations are never deleted: professionals and contracts keep referencing their slugs.

async def admin_seed(session: AsyncSession, actor: Actor) -> dict:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    await seed_default_taxonomy(session)
    count = await session.scalar(select(func.count()).select_from(TaxonomyNode).where(TaxonomyNode.level == "SPECIALIZATION"))
    return {"specializations": count}


async def _spec(session: AsyncSession, slug: str) -> TaxonomyNode:
    n = await session.scalar(select(TaxonomyNode).where(TaxonomyNode.slug == slug, TaxonomyNode.level == "SPECIALIZATION")
                             .with_for_update())
    if n is None:
        raise NotFound("Specialization not found")
    return n


async def _bump_version(session: AsyncSession, actor: Actor, spec: TaxonomyNode, change: str) -> SpecializationAdminOut:
    """Every change produces a new taxonomy version of the category (Architecture 12.2)."""
    cat = await session.scalar(select(TaxonomyNode).where(TaxonomyNode.slug == spec.category_slug,
                                                          TaxonomyNode.level == "CATEGORY").with_for_update())
    cat.taxonomy_version += 1
    spec.taxonomy_version = cat.taxonomy_version
    await session.flush()
    record_event(session, E.TAXONOMY_UPDATED, aggregate_type="Taxonomy", aggregate_id=cat.id,
                 payload={"categorySlug": cat.slug, "taxonomyVersion": cat.taxonomy_version, "change": change,
                          "specialization": spec.slug, "changedBy": actor.identity_id})
    group = await session.get(TaxonomyNode, spec.parent_id)
    return SpecializationAdminOut(
        slug=spec.slug, name=spec.name, groupSlug=group.slug, categorySlug=spec.category_slug,
        requiresCredential=spec.requires_credential, regulated=spec.regulated, requiresInsurance=spec.requires_insurance,
        deliverableTemplates=list(spec.deliverable_templates), credentialHints=list(spec.credential_hints),
        status=spec.status, taxonomyVersion=spec.taxonomy_version,
    )


async def create_specialization(session: AsyncSession, actor: Actor, body: SpecializationIn) -> SpecializationAdminOut:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    group = await session.scalar(select(TaxonomyNode).where(TaxonomyNode.slug == body.groupSlug, TaxonomyNode.level == "GROUP"))
    if group is None:
        raise NotFound("Group not found")
    slug = slugify(body.name)
    if await session.scalar(select(TaxonomyNode.id).where(TaxonomyNode.slug == slug)):
        raise Conflict(f"A taxonomy entry named {body.name!r} already exists", code="SPECIALIZATION_EXISTS")
    last = await session.scalar(select(func.max(TaxonomyNode.sort_order)).where(TaxonomyNode.parent_id == group.id))
    spec = TaxonomyNode(
        slug=slug, name=body.name.strip(), level="SPECIALIZATION", parent_id=group.id, category_slug=group.category_slug,
        sort_order=(last or 0) + 1, requires_credential=body.requiresCredential, regulated=body.regulated,
        requires_insurance=body.requiresInsurance,
        deliverable_templates=body.deliverableTemplates, credential_hints=body.credentialHints, status="ACTIVE",
    )
    session.add(spec)
    return await _bump_version(session, actor, spec, "CREATED")


async def update_specialization(session: AsyncSession, actor: Actor, slug: str, patch: SpecializationPatch) -> SpecializationAdminOut:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    spec = await _spec(session, slug)
    fields = {"name": "name", "requiresCredential": "requires_credential", "regulated": "regulated",
              "requiresInsurance": "requires_insurance",
              "deliverableTemplates": "deliverable_templates", "credentialHints": "credential_hints"}
    for api_name, col in fields.items():
        value = getattr(patch, api_name)
        if value is not None:
            setattr(spec, col, value.strip() if isinstance(value, str) else value)
    return await _bump_version(session, actor, spec, "UPDATED")


async def deprecate_specialization(session: AsyncSession, actor: Actor, slug: str) -> SpecializationAdminOut:
    """Deprecated specializations can no longer be chosen; existing profiles keep them."""
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    spec = await _spec(session, slug)
    if spec.status == "DEPRECATED":
        raise Conflict("Specialization is already deprecated", code="ALREADY_DEPRECATED")
    spec.status = "DEPRECATED"
    return await _bump_version(session, actor, spec, "DEPRECATED")


# ---- Saved professionals (buyer shortlist) ---------------------------------------

async def save_professional(session: AsyncSession, actor: Actor, professional_id: uuid.UUID) -> None:
    """Idempotent. Only published professionals can be saved."""
    pro = await professional_facade.get_professional(session, professional_id)
    if pro is None or pro.status != "PUBLISHED":
        raise NotFound("Professional not found")
    res = await session.execute(pg_insert(SavedProfessional).values(id=uuid.uuid4(), identity_id=actor.identity_id,
                                                                    professional_id=professional_id)
                                .on_conflict_do_nothing(index_elements=["identity_id", "professional_id"]))
    if res.rowcount:
        record_event(session, E.PROFESSIONAL_SAVED, aggregate_type="SavedProfessional", aggregate_id=professional_id,
                     payload={"professionalId": professional_id, "identityId": actor.identity_id})


async def unsave_professional(session: AsyncSession, actor: Actor, professional_id: uuid.UUID) -> None:
    await session.execute(delete(SavedProfessional).where(SavedProfessional.identity_id == actor.identity_id,
                                                          SavedProfessional.professional_id == professional_id))


async def saved_professionals(session: AsyncSession, actor: Actor) -> list[SavedOut]:
    rows = (await session.scalars(select(SavedProfessional).where(SavedProfessional.identity_id == actor.identity_id)
                                  .order_by(SavedProfessional.created_at.desc()).limit(200))).all()
    ids = [r.professional_id for r in rows]
    pros = await professional_facade.get_professionals(session, ids)
    trust = await trust_facade.get_trust_many(session, ids)
    specs = await get_specialization_names(session, [p.primary_specialization for p in pros.values() if p.primary_specialization])
    out = []
    for r in rows:
        p = pros.get(r.professional_id)
        if p is None:
            continue
        out.append(SavedOut(professionalId=p.id, displayName=p.display_name, headline=p.headline,
                            primarySpecialization=specs.get(p.primary_specialization or ""), tier=trust[p.id].tier,
                            availability=p.availability, available=p.status == "PUBLISHED", savedAt=r.created_at))
    return out


async def get_specialization_names(session: AsyncSession, slugs: list[str]) -> dict[str, str]:
    if not slugs:
        return {}
    rows = await session.execute(select(TaxonomyNode.slug, TaxonomyNode.name).where(TaxonomyNode.slug.in_(slugs)))
    return dict(rows.all())
