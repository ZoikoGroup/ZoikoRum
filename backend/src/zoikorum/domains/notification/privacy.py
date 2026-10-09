"""Notifications and preferences (shared/privacy.py). Both are deleted."""

from __future__ import annotations

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.notification.models import Notification, Preference
from zoikorum.shared import privacy


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    return {"preferences": await privacy.rows(session, Preference, Preference.identity_id == identity_id),
            "notifications": await privacy.rows(session, Notification, Notification.identity_id == identity_id)}


async def erase(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    removed = (await session.execute(delete(Notification).where(Notification.identity_id == identity_id))).rowcount
    await session.execute(delete(Preference).where(Preference.identity_id == identity_id))
    return {"notificationsDeleted": removed}


privacy.register("notification", export=export, erase=erase)
