"""Payments charges escrow funding requests and pays out escrow releases (with a buyer invoice)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.payments import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe


@subscribe(E.ESCROW_FUNDING_REQUESTED, consumer="payments.charge_funding")
async def on_funding_requested(session: AsyncSession, event: EventEnvelope) -> None:
    await service.charge_for_funding(session, event.payload)


@subscribe(E.ESCROW_RELEASED, consumer="payments.payout_and_invoice")
async def on_released(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_released(session, event.payload)
