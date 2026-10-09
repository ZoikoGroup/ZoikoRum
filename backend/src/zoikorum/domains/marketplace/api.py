from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from zoikorum.domains.marketplace import service
from zoikorum.domains.marketplace.schemas import (
    SavedSearchIn,
    SavedSearchOut,
    CollectionIn, CollectionItemsIn, CollectionOut, CompareItem, SavedOut, SaveIn, SpecializationAdminOut, SpecializationIn,
    SpecializationPatch, SuggestIn, SuggestionDecisionIn, SuggestionIn, SuggestionOut, SuggestOut,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession

router = APIRouter(tags=["marketplace"])


@router.get("/v1/taxonomy")
async def taxonomy(session: DbSession) -> dict:
    """Public: the full capability taxonomy (category -> groups -> specializations)."""
    return {"categories": await service.tree(session)}


@router.post("/v1/taxonomy/suggest", response_model=SuggestOut)
async def suggest(body: SuggestIn, actor: CurrentActor, session: DbSession):
    """"Can't find yours?": match your own words to existing specializations (AI when configured, keywords otherwise)."""
    return await service.suggest(session, actor, body)


@router.post("/v1/taxonomy/suggestions", response_model=SuggestionOut, status_code=status.HTTP_201_CREATED)
async def submit_suggestion(body: SuggestionIn, actor: CurrentActor, session: DbSession):
    """Suggest a new specialization; an admin approves, merges or rejects it."""
    return await service.submit_suggestion(session, actor, body)


@router.get("/v1/taxonomy/suggestions/mine", response_model=list[SuggestionOut])
async def my_suggestions(actor: CurrentActor, session: DbSession):
    return await service.my_suggestions(session, actor)


@router.get("/v1/admin/taxonomy/suggestions", response_model=list[SuggestionOut])
async def suggestion_queue(actor: CurrentActor, session: DbSession):
    return await service.suggestion_queue(session, actor)


@router.post("/v1/admin/taxonomy/suggestions/{suggestion_id}/decision", response_model=SuggestionOut)
async def decide_suggestion(suggestion_id: uuid.UUID, body: SuggestionDecisionIn, actor: CurrentActor, session: DbSession):
    return await service.decide_suggestion(session, actor, suggestion_id, body)


@router.get("/v1/taxonomy/{category}")
async def category(category: str, session: DbSession) -> dict:
    cats = await service.tree(session, category)
    return cats[0]


@router.post("/v1/admin/taxonomy/seed")
async def seed(actor: CurrentActor, session: DbSession) -> dict:
    """Load the default taxonomy (idempotent; never overwrites edited entries)."""
    return await service.admin_seed(session, actor)


@router.post("/v1/admin/taxonomy/specializations", response_model=SpecializationAdminOut, status_code=status.HTTP_201_CREATED)
async def create_specialization(body: SpecializationIn, actor: CurrentActor, session: DbSession):
    return await service.create_specialization(session, actor, body)


@router.patch("/v1/admin/taxonomy/specializations/{slug}", response_model=SpecializationAdminOut)
async def update_specialization(slug: str, body: SpecializationPatch, actor: CurrentActor, session: DbSession):
    return await service.update_specialization(session, actor, slug, body)


@router.post("/v1/admin/taxonomy/specializations/{slug}/deprecate", response_model=SpecializationAdminOut)
async def deprecate_specialization(slug: str, actor: CurrentActor, session: DbSession):
    return await service.deprecate_specialization(session, actor, slug)


@router.get("/v1/saved/professionals", response_model=list[SavedOut])
async def saved(actor: CurrentActor, session: DbSession):
    """Your saved professionals, newest first."""
    return await service.saved_professionals(session, actor)


@router.post("/v1/saved/professionals", status_code=status.HTTP_204_NO_CONTENT)
async def save(body: SaveIn, actor: CurrentActor, session: DbSession) -> None:
    await service.save_professional(session, actor, body.professionalId)


@router.delete("/v1/saved/professionals/{professional_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsave(professional_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.unsave_professional(session, actor, professional_id)


@router.get("/v1/saved/collections", response_model=list[CollectionOut])
async def collections(actor: CurrentActor, session: DbSession):
    return await service.list_collections(session, actor)


@router.post("/v1/saved/collections", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
async def create_collection(body: CollectionIn, actor: CurrentActor, session: DbSession):
    return await service.create_collection(session, actor, body.name)


@router.patch("/v1/saved/collections/{collection_id}", response_model=CollectionOut)
async def rename_collection(collection_id: uuid.UUID, body: CollectionIn, actor: CurrentActor, session: DbSession):
    return await service.rename_collection(session, actor, collection_id, body.name)


@router.delete("/v1/saved/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(collection_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.delete_collection(session, actor, collection_id)


@router.post("/v1/saved/collections/{collection_id}/items", response_model=CollectionOut)
async def add_to_collection(collection_id: uuid.UUID, body: CollectionItemsIn, actor: CurrentActor, session: DbSession):
    """Adds professionals to a collection (and saves them, if not saved yet)."""
    return await service.add_to_collection(session, actor, collection_id, body.professionalIds)


@router.delete("/v1/saved/collections/{collection_id}/items/{professional_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_collection(collection_id: uuid.UUID, professional_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.remove_from_collection(session, actor, collection_id, professional_id)


@router.get("/v1/compare", response_model=list[CompareItem])
async def compare(session: DbSession, ids: str = Query(description="Comma-separated professional ids (max 3)")):
    """Side-by-side comparison of up to 3 published professionals."""
    try:
        parsed = [uuid.UUID(i.strip()) for i in ids.split(",") if i.strip()]
    except ValueError as exc:
        from zoikorum.shared.errors import ValidationFailed

        raise ValidationFailed("ids must be professional ids", code="INVALID_IDS") from exc
    return await service.compare(session, parsed)


@router.get("/v1/saved/searches", response_model=list[SavedSearchOut])
async def list_searches(actor: CurrentActor, session: DbSession):
    return await service.list_searches(session, actor)


@router.post("/v1/saved/searches", response_model=SavedSearchOut, status_code=status.HTTP_201_CREATED)
async def save_search(body: SavedSearchIn, actor: CurrentActor, session: DbSession):
    """Save the current filters; re-run later and see what is new since you last looked."""
    return await service.save_search(session, actor, body)


@router.post("/v1/saved/searches/{search_id}/viewed", response_model=SavedSearchOut)
async def search_viewed(search_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.mark_search_viewed(session, actor, search_id)


@router.delete("/v1/saved/searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search(search_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    await service.delete_search(session, actor, search_id)
