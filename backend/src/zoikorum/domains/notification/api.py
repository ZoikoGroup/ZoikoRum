from __future__ import annotations

from fastapi import APIRouter

from zoikorum.domains.notification import service
from zoikorum.domains.notification.schemas import PreferencesIO
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession

router = APIRouter(prefix="/v1/notification-preferences", tags=["notifications"])


@router.get("", response_model=PreferencesIO)
async def get_preferences(actor: CurrentActor, session: DbSession):
    return await service.get_preferences(session, actor)


@router.put("", response_model=PreferencesIO)
async def set_preferences(body: PreferencesIO, actor: CurrentActor, session: DbSession):
    """Settings > Notifications. Security messages stay mandatory."""
    return await service.set_preferences(session, actor, body)
