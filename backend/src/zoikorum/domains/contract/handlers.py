"""Contract reacts to accepted proposals (generate the agreement) and to escrow funding (start the funded milestones)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.contract import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe
from zoikorum.shared.relay import on_timer


@subscribe(E.PROPOSAL_ACCEPTED, consumer="contract.generate")
async def on_proposal_accepted(session: AsyncSession, event: EventEnvelope) -> None:
    await service.generate_from_proposal(session, event.payload)


@subscribe(E.ESCROW_FUNDED, consumer="contract.start_funded_milestones")
async def on_escrow_funded(session: AsyncSession, event: EventEnvelope) -> None:
    await service.escrow_funded(session, event.payload)


@on_timer(service.TIMER_SIGNATURE)
async def on_signature_deadline(session: AsyncSession, key: str, payload: dict) -> None:
    await service.signature_deadline_passed(session, payload)
