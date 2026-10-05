from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from zoikorum.domains.marketplace import service
from zoikorum.domains.marketplace.schemas import SavedOut, SaveIn, SpecializationAdminOut, SpecializationIn, SpecializationPatch
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession

router = APIRouter(tags=["marketplace"])


@router.get("/v1/taxonomy")
async def taxonomy(session: DbSession) -> dict:
    """Public: the full capability taxonomy (category -> groups -> specializations)."""
    return {"categories": await service.tree(session)}


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
