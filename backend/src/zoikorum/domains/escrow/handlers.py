"""Escrow opens with an active contract, holds captured payments, releases on acceptance, freezes and settles disputes."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.escrow import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe


@subscribe(E.CONTRACT_ACTIVATED, consumer="escrow.open_account")
async def on_contract_activated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.open_account(session, event.payload)


@subscribe(E.PAYMENT_CAPTURED, consumer="escrow.hold_captured_funds")
async def on_payment_captured(session: AsyncSession, event: EventEnvelope) -> None:
    await service.payment_captured(session, event.payload)


@subscribe(E.PAYMENT_FAILED, consumer="escrow.funding_failed")
async def on_payment_failed(session: AsyncSession, event: EventEnvelope) -> None:
    await service.payment_failed(session, event.payload)


@subscribe(E.PAYMENT_CHARGED_BACK, consumer="escrow.chargeback")
async def on_payment_charged_back(session: AsyncSession, event: EventEnvelope) -> None:
    await service.payment_charged_back(session, event.payload)


@subscribe(E.MILESTONE_ACCEPTED, consumer="escrow.release_decision")
async def on_milestone_accepted(session: AsyncSession, event: EventEnvelope) -> None:
    await service.milestone_accepted(session, event.payload)


@subscribe(E.DISPUTE_INITIATED, consumer="escrow.dispute_hold")
async def on_dispute_initiated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.dispute_initiated(session, event.payload)


@subscribe(E.DISPUTE_RESOLVED, consumer="escrow.execute_dispute_decision")
async def on_dispute_resolved(session: AsyncSession, event: EventEnvelope) -> None:
    await service.dispute_resolved(session, event.payload)


@subscribe(E.CONTRACT_TERMINATED, consumer="escrow.refund_on_termination")
async def on_contract_terminated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.contract_terminated(session, event.payload)
