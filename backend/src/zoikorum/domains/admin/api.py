from __future__ import annotations

from fastapi import APIRouter

from zoikorum.domains.admin import service
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession

router = APIRouter(tags=["admin"])


@router.get("/v1/admin/overview")
async def overview(actor: CurrentActor, session: DbSession) -> dict:
    """Staff: platform counts (accounts, professional profiles, open verification checks)."""
    return await service.overview(session, actor)
