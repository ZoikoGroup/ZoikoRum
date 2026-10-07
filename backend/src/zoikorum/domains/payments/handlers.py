"""Payments charges escrow funding requests, pays out releases (with a buyer invoice), returns refunds and reconciles daily."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.payments import reconciliation, service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe
from zoikorum.shared.relay import on_timer


@subscribe(E.ESCROW_FUNDING_REQUESTED, consumer="payments.charge_funding")
async def on_funding_requested(session: AsyncSession, event: EventEnvelope) -> None:
    await service.charge_for_funding(session, event.payload)


@subscribe(E.ESCROW_RELEASED, consumer="payments.payout_and_invoice")
async def on_released(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_released(session, event.payload)


@subscribe(E.ESCROW_REFUNDED, consumer="payments.refund")
async def on_refunded(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_refunded(session, event.payload)


@on_timer(reconciliation.TIMER)
async def on_daily_reconciliation(session: AsyncSession, key: str, payload: dict) -> None:
    await reconciliation.scheduled(session)
