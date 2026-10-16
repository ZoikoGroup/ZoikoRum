"""Marketplace alerts: saved professionals who become available, and daily new matches for saved searches."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.marketplace import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe
from zoikorum.shared.relay import on_timer


@subscribe(E.AVAILABILITY_UPDATED, consumer="marketplace.saved_available")
@subscribe(E.CAPACITY_CHANGED, consumer="marketplace.saved_available")
async def on_availability(session: AsyncSession, event: EventEnvelope) -> None:
    await service.professional_availability_changed(session, event.payload)


@on_timer(service.ALERT_TIMER)
async def on_saved_search_alerts(session: AsyncSession, key: str, payload: dict) -> None:
    await service.saved_search_alerts(session)
