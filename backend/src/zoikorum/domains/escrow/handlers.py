"""Escrow opens with an active contract, holds captured payments, and releases on milestone acceptance."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.escrow import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe


@subscribe(E.CONTRACT_ACTIVATED, consumer="escrow.open_account")
async def on_contract_activated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.open_account(session, event.payload)


@subscribe(E.CONTRACT_AMENDED, consumer="escrow.apply_contract_amendment")
async def on_contract_amended(session: AsyncSession, event: EventEnvelope) -> None:
    await service.contract_amended(session, event.payload)


@subscribe(E.PAYMENT_CAPTURED, consumer="escrow.hold_captured_funds")
async def on_payment_captured(session: AsyncSession, event: EventEnvelope) -> None:
    await service.payment_captured(session, event.payload)


@subscribe(E.PAYMENT_FAILED, consumer="escrow.funding_failed")
async def on_payment_failed(session: AsyncSession, event: EventEnvelope) -> None:
    await service.payment_failed(session, event.payload)


@subscribe(E.MILESTONE_ACCEPTED, consumer="escrow.release_decision")
async def on_milestone_accepted(session: AsyncSession, event: EventEnvelope) -> None:
    await service.milestone_accepted(session, event.payload)
