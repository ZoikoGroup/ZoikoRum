from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.notification.models import Preference
from zoikorum.domains.notification.schemas import PreferencesIO
from zoikorum.shared.auth import Actor
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event


def _out(p: Preference | None) -> PreferencesIO:
    return PreferencesIO() if p is None else PreferencesIO(email=p.email, inApp=p.in_app, sms=p.sms, marketing=p.marketing)


async def get_preferences(session: AsyncSession, actor: Actor) -> PreferencesIO:
    return _out(await session.scalar(select(Preference).where(Preference.identity_id == actor.identity_id)))


async def set_preferences(session: AsyncSession, actor: Actor, body: PreferencesIO) -> PreferencesIO:
    p = await session.scalar(select(Preference).where(Preference.identity_id == actor.identity_id).with_for_update())
    if p is None:
        p = Preference(id=uuid.uuid4(), identity_id=actor.identity_id)
        session.add(p)
    p.email, p.in_app, p.sms, p.marketing = body.email, body.inApp, body.sms, body.marketing
    await session.flush()
    record_event(session, E.NOTIFICATION_PREFERENCES_UPDATED, aggregate_type="NotificationPreferences", aggregate_id=p.id,
                 payload={"identityId": actor.identity_id, "email": p.email, "inApp": p.in_app, "sms": p.sms,
                          "marketing": p.marketing})
    return _out(p)
