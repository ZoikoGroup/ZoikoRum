"""What other domains may read from the analytics projection."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.analytics.models import EventFact
from zoikorum.shared.event_catalog import E


async def profile_views(session: AsyncSession, professional_id: uuid.UUID, since: datetime) -> int:
    """Views of a public profile by others since a date: one per signed-in viewer per day, each signed-out view once."""
    viewer = EventFact.payload["viewerId"].astext
    key = func.coalesce(viewer, cast(EventFact.source_event_id, String)) + "|" + cast(func.date(EventFact.occurred_at), String)
    q = select(func.count(func.distinct(key)))
    return await session.scalar(q.where(EventFact.event_type == E.PROFILE_VIEWED, EventFact.professional_id == professional_id,
                                        EventFact.occurred_at >= since)) or 0
