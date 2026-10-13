from __future__ import annotations

import uuid

from fastapi import APIRouter

from zoikorum.domains.trust import service
from zoikorum.domains.trust.schemas import TrustHistoryOut, TrustOut
from zoikorum.shared.auth import CurrentActor, OptionalActor
from zoikorum.shared.db import DbSession

router = APIRouter(prefix="/v1/trust", tags=["trust"])


@router.get("/professionals/{professional_id}", response_model=TrustOut)
async def trust(professional_id: uuid.UUID, actor: OptionalActor, session: DbSession):
    """Public trust snapshot: tier, verification dimensions and why."""
    return await service.get_trust(session, actor, professional_id)


@router.get("/professionals/{professional_id}/history", response_model=TrustHistoryOut)
async def history(professional_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    """Owner or Trust & Safety: tier changes and the signals behind them."""
    return await service.history(session, actor, professional_id)
