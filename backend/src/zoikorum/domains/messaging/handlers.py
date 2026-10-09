"""Materialize conversation threads and react to engagement dispute lifecycle events."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.messaging import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe


@subscribe(E.PROPOSAL_REQUESTED, consumer="messaging.create_request_thread")
async def on_request_created(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_request_created(session, event)


@subscribe(E.CONTRACT_ACTIVATED, consumer="messaging.create_engagement_thread")
async def on_contract_activated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_contract_activated(session, event)


@subscribe(E.DISPUTE_INITIATED, consumer="messaging.lock_for_dispute")
async def on_dispute_initiated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_dispute_initiated(session, event)


@subscribe(E.DISPUTE_CLOSED, consumer="messaging.unlock_after_dispute")
async def on_dispute_closed(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_dispute_closed(session, event)


LIFECYCLE = {
    E.PROPOSAL_SUBMITTED: "A proposal was submitted.",
    E.PROPOSAL_REVISION_REQUESTED: "Changes to the proposal were requested.",
    E.PROPOSAL_REVISED: "The proposal was revised.",
    E.PROPOSAL_ACCEPTED: "The proposal was accepted. The agreement will be generated.",
    E.PROPOSAL_REJECTED: "The proposal was declined.",
    E.PROPOSAL_REQUEST_CANCELLED: "The request was cancelled.",
    E.PROPOSAL_REQUEST_DECLINED: "The request was declined.",
    E.CONTRACT_GENERATED: "The agreement is ready for signature.",
    E.CONTRACT_SIGNED: "A party signed the agreement.",
    E.CONTRACT_COMPLETED: "The engagement is complete.",
    E.CONTRACT_TERMINATED: "The engagement was terminated.",
    E.CONTRACT_AMENDED: "An agreed contract amendment was applied.",
    E.MILESTONE_SUBMITTED: "Milestone work was submitted for review.",
    E.MILESTONE_ACCEPTED: "Milestone work was accepted.",
    E.MILESTONE_REVISION_REQUESTED: "Revisions to milestone work were requested.",
    E.ESCROW_FUNDED: "Milestone funding was confirmed.",
    E.ESCROW_RELEASED: "Protected funds were released.",
}


async def on_lifecycle(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_lifecycle(session, event, LIFECYCLE[event.eventType])


for event_type in LIFECYCLE:
    subscribe(event_type, consumer="messaging.lifecycle_record")(on_lifecycle)
