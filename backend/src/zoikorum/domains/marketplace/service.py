"""Marketplace: capability taxonomy and buyers' saved professionals."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.ai import facade as ai_facade
from zoikorum.domains.marketplace.models import Collection, CollectionItem, SavedProfessional, SavedSearch, SpecializationSuggestion, TaxonomyNode
from zoikorum.domains.marketplace.schemas import (
    SEARCH_KEYS,
    SavedSearchIn,
    SavedSearchOut,
    CollectionOut, CompareItem, SavedOut, SpecializationAdminOut, SpecializationDraftOut, SpecializationIn, SpecializationMatchOut,
    SpecializationPatch, SuggestIn, SuggestionDecisionIn, SuggestionIn, SuggestionOut, SuggestOut,
)
from zoikorum.domains.marketplace.taxonomy_data import default_taxonomy_rows, slugify
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.domains.verification import facade as verification_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import Conflict, NotFound, ValidationFailed
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
    specs = await get_specialization_names(session, sorted({s for p in pros.values() for s in p.specializations}))
    membership: dict = {}
    for cid, pid in (await session.execute(select(CollectionItem.collection_id, CollectionItem.professional_id)
                                           .join(Collection, Collection.id == CollectionItem.collection_id)
                                           .where(Collection.identity_id == actor.identity_id))).all():
        membership.setdefault(pid, []).append(cid)
    out = []
    for r in rows:
        p = pros.get(r.professional_id)
        if p is None:
            continue
        t = trust[p.id]
        out.append(SavedOut(
            professionalId=p.id, displayName=p.display_name, headline=p.headline, photoUrl=p.photo_url, city=p.city,
            country=p.country, languages=list(p.languages), yearsExperienceBand=p.years_experience_band,
            primarySpecialization=specs.get(p.primary_specialization or ""),
            specializations=[specs.get(s, s) for s in p.specializations], engagementTypes=list(p.engagement_types),
            pricingModels=list(p.pricing_models), startingPrice=await _starting_price(session, p.id), tier=t.tier,
            dimensions=_public_dimensions(t.dimensions), lastVerifiedAt=t.updated_at, availability=p.availability,
            available=p.status == "PUBLISHED", collectionIds=membership.get(p.id, []), savedAt=r.created_at))
    return out


def _public_dimensions(dimensions) -> dict[str, str]:
    """Customers never see a screening problem, only whether screening is clear."""
    out = dict(dimensions)
    if out.get("restrictions") not in (None, "CLEAR"):
        out["restrictions"] = "UNKNOWN"
    return out


async def _starting_price(session: AsyncSession, professional_id: uuid.UUID):
    from zoikorum.shared.money import MoneyDTO

    priced = [o for o in await professional_facade.list_offerings(session, professional_id, active_only=True)
              if o.starting_price_minor is not None and o.currency]
    cheapest = min(priced, key=lambda o: o.starting_price_minor, default=None)
    return MoneyDTO(amountMinor=cheapest.starting_price_minor, currency=cheapest.currency) if cheapest else None


async def get_specialization_names(session: AsyncSession, slugs: list[str]) -> dict[str, str]:
    if not slugs:
        return {}
    rows = await session.execute(select(TaxonomyNode.slug, TaxonomyNode.name).where(TaxonomyNode.slug.in_(slugs)))
    return dict(rows.all())


# ---- Collections (Saved Professionals > Collections) -----------------------------

MAX_COLLECTIONS = 50
MAX_COMPARE = 3  # Professional Profile / Category docs: compare up to 3 side by side


async def _collection(session: AsyncSession, actor: Actor, collection_id: uuid.UUID, lock: bool = False) -> Collection:
    c = await session.get(Collection, collection_id, with_for_update=lock)
    if c is None or c.identity_id != actor.identity_id:
        raise NotFound("Collection not found")
    return c


def _collection_evt(session: AsyncSession, actor: Actor, c: Collection, change: str, **extra) -> None:
    record_event(session, E.COLLECTION_UPDATED, aggregate_type="Collection", aggregate_id=c.id,
                 payload={"collectionId": c.id, "identityId": actor.identity_id, "change": change, **extra})


async def list_collections(session: AsyncSession, actor: Actor) -> list[CollectionOut]:
    rows = (await session.execute(
        select(Collection, func.count(CollectionItem.id)).outerjoin(CollectionItem, CollectionItem.collection_id == Collection.id)
        .where(Collection.identity_id == actor.identity_id).group_by(Collection.id).order_by(Collection.updated_at.desc())
    )).all()
    return [CollectionOut(id=c.id, name=c.name, count=n, updatedAt=c.updated_at) for c, n in rows]


async def create_collection(session: AsyncSession, actor: Actor, name: str) -> CollectionOut:
    name = name.strip()
    if await session.scalar(select(func.count()).select_from(Collection).where(Collection.identity_id == actor.identity_id)) >= MAX_COLLECTIONS:
        raise Conflict(f"You can have up to {MAX_COLLECTIONS} collections", code="TOO_MANY_COLLECTIONS")
    if await session.scalar(select(Collection.id).where(Collection.identity_id == actor.identity_id, Collection.name == name)):
        raise Conflict("You already have a collection with that name", code="COLLECTION_EXISTS")
    c = Collection(identity_id=actor.identity_id, name=name)
    session.add(c)
    await session.flush()
    _collection_evt(session, actor, c, "CREATED")
    return CollectionOut(id=c.id, name=c.name, count=0, updatedAt=c.updated_at)


async def rename_collection(session: AsyncSession, actor: Actor, collection_id: uuid.UUID, name: str) -> CollectionOut:
    c = await _collection(session, actor, collection_id, lock=True)
    name = name.strip()
    if name != c.name and await session.scalar(select(Collection.id).where(
            Collection.identity_id == actor.identity_id, Collection.name == name)):
        raise Conflict("You already have a collection with that name", code="COLLECTION_EXISTS")
    c.name = name
    await session.flush()
    _collection_evt(session, actor, c, "RENAMED")
    n = await session.scalar(select(func.count()).select_from(CollectionItem).where(CollectionItem.collection_id == c.id))
    return CollectionOut(id=c.id, name=c.name, count=n or 0, updatedAt=c.updated_at)


async def delete_collection(session: AsyncSession, actor: Actor, collection_id: uuid.UUID) -> None:
    """Removes the group only; the professionals stay saved."""
    c = await _collection(session, actor, collection_id, lock=True)
    await session.execute(delete(CollectionItem).where(CollectionItem.collection_id == c.id))
    _collection_evt(session, actor, c, "DELETED")
    await session.delete(c)


async def add_to_collection(session: AsyncSession, actor: Actor, collection_id: uuid.UUID, ids: list[uuid.UUID]) -> CollectionOut:
    c = await _collection(session, actor, collection_id, lock=True)
    for pid in dict.fromkeys(ids):
        await save_professional(session, actor, pid)  # a collection member is always saved too
        await session.execute(pg_insert(CollectionItem).values(id=uuid.uuid4(), collection_id=c.id, professional_id=pid)
                              .on_conflict_do_nothing(index_elements=["collection_id", "professional_id"]))
    c.updated_at = func.now()
    await session.flush()
    _collection_evt(session, actor, c, "ITEMS_ADDED", professionalIds=list(dict.fromkeys(ids)))
    n = await session.scalar(select(func.count()).select_from(CollectionItem).where(CollectionItem.collection_id == c.id))
    await session.refresh(c)
    return CollectionOut(id=c.id, name=c.name, count=n or 0, updatedAt=c.updated_at)


async def remove_from_collection(session: AsyncSession, actor: Actor, collection_id: uuid.UUID, professional_id: uuid.UUID) -> None:
    c = await _collection(session, actor, collection_id, lock=True)
    await session.execute(delete(CollectionItem).where(CollectionItem.collection_id == c.id,
                                                       CollectionItem.professional_id == professional_id))
    _collection_evt(session, actor, c, "ITEM_REMOVED", professionalId=professional_id)


# ---- Compare (max 3, published professionals only) --------------------------------

async def compare(session: AsyncSession, ids: list[uuid.UUID]) -> list[CompareItem]:
    ids = list(dict.fromkeys(ids))
    if not 1 <= len(ids) <= MAX_COMPARE:
        raise ValidationFailed(f"Compare between 1 and {MAX_COMPARE} professionals", code="COMPARE_LIMIT")
    pros = await professional_facade.get_professionals(session, ids)
    trust = await trust_facade.get_trust_many(session, ids)
    published = [pros[i] for i in ids if i in pros and pros[i].status == "PUBLISHED"]
    names = await get_specialization_names(session, sorted({s for p in published for s in p.specializations}))
    out = []
    for p in published:
        checks = await verification_facade.get_checks(session, "PROFESSIONAL", p.id)
        out.append(CompareItem(
            professionalId=p.id, displayName=p.display_name, headline=p.headline, photoUrl=p.photo_url, country=p.country,
            tier=trust[p.id].tier, dimensions=_public_dimensions(trust[p.id].dimensions),
            verifiedCredentials=[c.label for c in checks if c.verification_type == "CREDENTIAL" and c.status == "VERIFIED"],
            specializations=[names.get(s, s) for s in p.specializations], engagementTypes=list(p.engagement_types),
            deliveryModes=list(p.delivery_modes), pricingModels=list(p.pricing_models),
            startingPrice=await _starting_price(session, p.id), availability=p.availability,
            yearsExperienceBand=p.years_experience_band, servedJurisdictions=list(p.jurisdictions_served),
            licensedJurisdictions=list(p.licensed_jurisdictions), languages=list(p.languages)))
    return out


# ---- Saved searches (Buyer Dashboard s.13) ---------------------------------------------------------------

MAX_SEARCHES = 25


def _search_out(s: SavedSearch) -> SavedSearchOut:
    return SavedSearchOut(id=s.id, name=s.name, params=s.params, lastViewedAt=s.last_viewed_at, createdAt=s.created_at)


async def list_searches(session: AsyncSession, actor: Actor) -> list[SavedSearchOut]:
    rows = (await session.scalars(select(SavedSearch).where(SavedSearch.identity_id == actor.identity_id)
                                  .order_by(SavedSearch.created_at.desc()))).all()
    return [_search_out(s) for s in rows]


async def save_search(session: AsyncSession, actor: Actor, body: SavedSearchIn) -> SavedSearchOut:
    params = {k: v.strip()[:200] for k, v in body.params.items() if k in SEARCH_KEYS and v and v.strip()}
    if not params:
        raise ValidationFailed("Add a search term or at least one filter before saving", code="EMPTY_SEARCH")
    name = body.name.strip()
    if await session.scalar(select(func.count()).select_from(SavedSearch).where(SavedSearch.identity_id == actor.identity_id)) >= MAX_SEARCHES:
        raise Conflict(f"You can save up to {MAX_SEARCHES} searches", code="TOO_MANY_SEARCHES")
    if await session.scalar(select(SavedSearch.id).where(SavedSearch.identity_id == actor.identity_id, SavedSearch.name == name)):
        raise Conflict("You already have a saved search with that name", code="SEARCH_EXISTS")
    s = SavedSearch(identity_id=actor.identity_id, name=name, params=params, last_viewed_at=clock.now())
    session.add(s)
    await session.flush()
    return _search_out(s)


async def _my_search(session: AsyncSession, actor: Actor, search_id: uuid.UUID) -> SavedSearch:
    s = await session.get(SavedSearch, search_id)
    if s is None or s.identity_id != actor.identity_id:
        raise NotFound("Saved search not found")
    return s


async def mark_search_viewed(session: AsyncSession, actor: Actor, search_id: uuid.UUID) -> SavedSearchOut:
    s = await _my_search(session, actor, search_id)
    s.last_viewed_at = clock.now()
    await session.flush()
    return _search_out(s)


async def delete_search(session: AsyncSession, actor: Actor, search_id: uuid.UUID) -> None:
    await session.delete(await _my_search(session, actor, search_id))


# ---- "Can't find yours?" (specialization suggestions) ---------------------------------------------------------------

MAX_PENDING_SUGGESTIONS = 3


async def _catalog(session: AsyncSession) -> list:
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


async def suggest(session: AsyncSession, actor: Actor, body: SuggestIn) -> SuggestOut:
    """Match the professional's own words to the taxonomy (AI assists; the person chooses)."""
    catalog = await _catalog(session)
    result = await ai_facade.match_specializations(body.text, catalog)
    by_slug = {e.slug: e for e in catalog}
    draft = result.draft
    return SuggestOut(
        matches=[SpecializationMatchOut(slug=s, name=by_slug[s].name, groupName=by_slug[s].group_name, categoryName=by_slug[s].category_name)
                 for s in result.slugs if s in by_slug],
        draft=SpecializationDraftOut(name=draft.name, categorySlug=draft.category_slug, groupSlug=draft.group_slug,
                                     description=draft.description, credentialLikely=draft.credential_likely) if draft else None,
        source=result.source)


def _suggestion_out(s: SpecializationSuggestion, professional_name: str | None = None) -> SuggestionOut:
    return SuggestionOut(id=s.id, text=s.text, name=s.name, categorySlug=s.category_slug, groupSlug=s.group_slug, description=s.description,
                         credentialLikely=s.credential_likely, source=s.source, status=s.status, resolvedSlug=s.resolved_slug,
                         resolutionNote=s.resolution_note, professionalId=s.professional_id, professionalName=professional_name,
                         createdAt=s.created_at, resolvedAt=s.resolved_at)


async def submit_suggestion(session: AsyncSession, actor: Actor, body: SuggestionIn) -> SuggestionOut:
    pro = await professional_facade.get_professional_by_identity(session, actor.identity_id)
    if pro is None:
        raise ValidationFailed("Create your professional profile first", code="PROFILE_REQUIRED")
    pending = await session.scalar(select(func.count()).select_from(SpecializationSuggestion).where(
        SpecializationSuggestion.identity_id == actor.identity_id, SpecializationSuggestion.status == "PENDING"))
    if pending >= MAX_PENDING_SUGGESTIONS:
        raise Conflict(f"You already have {MAX_PENDING_SUGGESTIONS} suggestions waiting for review", code="TOO_MANY_SUGGESTIONS")
    name = " ".join(body.name.split())
    existing = await session.scalar(select(TaxonomyNode).where(TaxonomyNode.slug == slugify(name), TaxonomyNode.level == "SPECIALIZATION"))
    if existing is not None:
        raise Conflict(f"“{existing.name}” already exists: pick it from the list", code="SPECIALIZATION_EXISTS")
    group = await session.scalar(select(TaxonomyNode).where(TaxonomyNode.slug == body.groupSlug, TaxonomyNode.level == "GROUP")) \
        if body.groupSlug else None
    s = SpecializationSuggestion(identity_id=actor.identity_id, professional_id=pro.id, text=body.text.strip(), name=name,
                                 category_slug=group.category_slug if group else body.categorySlug, group_slug=group.slug if group else None,
                                 description=body.description.strip(), credential_likely=body.credentialLikely,
                                 source=body.source if body.source.startswith(("ai:", "fallback:")) else "manual", status="PENDING")
    session.add(s)
    await session.flush()
    record_event(session, E.TAXONOMY_SUGGESTION_SUBMITTED, aggregate_type="SpecializationSuggestion", aggregate_id=s.id,
                 payload={"suggestionId": s.id, "professionalId": pro.id, "name": name, "categorySlug": s.category_slug})
    return _suggestion_out(s)


async def my_suggestions(session: AsyncSession, actor: Actor) -> list[SuggestionOut]:
    rows = (await session.scalars(select(SpecializationSuggestion).where(SpecializationSuggestion.identity_id == actor.identity_id)
                                  .order_by(SpecializationSuggestion.created_at.desc()).limit(50))).all()
    return [_suggestion_out(s) for s in rows]


async def pending_names(session: AsyncSession, professional_id: uuid.UUID) -> list[str]:
    rows = await session.scalars(select(SpecializationSuggestion.name).where(
        SpecializationSuggestion.professional_id == professional_id, SpecializationSuggestion.status == "PENDING"))
    return list(rows.all())


async def suggestion_queue(session: AsyncSession, actor: Actor) -> list[SuggestionOut]:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    rows = (await session.scalars(select(SpecializationSuggestion).where(SpecializationSuggestion.status == "PENDING")
                                  .order_by(SpecializationSuggestion.created_at).limit(200))).all()
    pros = await professional_facade.get_professionals(session, [s.professional_id for s in rows if s.professional_id])
    return [_suggestion_out(s, pros[s.professional_id].display_name if s.professional_id in pros else None) for s in rows]


async def decide_suggestion(session: AsyncSession, actor: Actor, suggestion_id: uuid.UUID, body: SuggestionDecisionIn) -> SuggestionOut:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    s = await session.get(SpecializationSuggestion, suggestion_id, with_for_update=True)
    if s is None:
        raise NotFound("Suggestion not found")
    if s.status != "PENDING":
        raise Conflict("This suggestion has already been decided", code="ALREADY_DECIDED")
    if body.action == "APPROVE":
        group = body.groupSlug or s.group_slug
        if not group:
            raise ValidationFailed("Choose the group the new specialization belongs to", code="GROUP_REQUIRED")
        created = await create_specialization(session, actor, SpecializationIn(
            groupSlug=group, name=(body.name or s.name).strip(), requiresCredential=body.requiresCredential or s.credential_likely,
            regulated=body.regulated))
        s.status, s.resolved_slug = "APPROVED", created.slug
    elif body.action == "MERGE":
        target = await session.scalar(select(TaxonomyNode).where(TaxonomyNode.slug == (body.mergeSlug or ""),
                                                                 TaxonomyNode.level == "SPECIALIZATION", TaxonomyNode.status == "ACTIVE"))
        if target is None:
            raise ValidationFailed("Choose an existing specialization to merge into", code="MERGE_TARGET_REQUIRED")
        s.status, s.resolved_slug = "MERGED", target.slug
    else:
        if len(body.note.strip()) < 5:
            raise ValidationFailed("Tell the professional why, in a sentence", code="NOTE_REQUIRED")
        s.status = "REJECTED"
    s.resolved_by, s.resolved_at, s.resolution_note = actor.identity_id, clock.now(), body.note.strip() or None
    record_event(session, E.TAXONOMY_SUGGESTION_RESOLVED, aggregate_type="SpecializationSuggestion", aggregate_id=s.id,
                 payload={"suggestionId": s.id, "professionalId": s.professional_id, "outcome": s.status, "slug": s.resolved_slug})
    await session.flush()
    return _suggestion_out(s)

