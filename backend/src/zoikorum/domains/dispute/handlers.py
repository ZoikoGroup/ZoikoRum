"""Dispute phases move on durable timers; a case closes once escrow has executed the decision."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.dispute import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe
from zoikorum.shared.relay import on_timer


@subscribe(E.ESCROW_RESOLUTION_EXECUTED, consumer="dispute.close_after_execution")
async def on_resolution_executed(session: AsyncSession, event: EventEnvelope) -> None:
    await service.resolution_executed(session, event.payload)


@on_timer(service.TIMER_EVIDENCE)
async def on_evidence_window(session: AsyncSession, key: str, payload: dict) -> None:
    await service.evidence_window_closed(session, payload)


@on_timer(service.TIMER_DIRECT)
async def on_direct_window(session: AsyncSession, key: str, payload: dict) -> None:
    await service.direct_window_closed(session, payload)
