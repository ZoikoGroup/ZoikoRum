"""Keep the search projection current: any fact that changes what buyers see rebuilds that document."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.search import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe

_EVENTS = (
    E.PROFESSIONAL_REGISTERED, E.PROFILE_UPDATED, E.PROFILE_PUBLISHED, E.PROFILE_UNPUBLISHED, E.PROFILE_SUSPENDED,
    E.PROFILE_REINSTATED, E.SERVICE_OFFERING_CREATED, E.SERVICE_OFFERING_UPDATED, E.SERVICE_OFFERING_STATUS_CHANGED,
    E.AVAILABILITY_UPDATED, E.CAPACITY_CHANGED, E.JURISDICTIONS_UPDATED, E.TRUST_SCORE_RECOMPUTED, E.TRUST_TIER_CHANGED,
    E.VERIFICATION_COMPLETED, E.VERIFICATION_FAILED, E.VERIFICATION_EXPIRED, E.VERIFICATION_REVOKED,
    E.ENFORCEMENT_ACTION_APPLIED, E.ENFORCEMENT_ACTION_REVERSED,
)


def _professional_id(payload: dict) -> uuid.UUID | None:
    if payload.get("professionalId"):
        return uuid.UUID(str(payload["professionalId"]))
    if payload.get("subjectType") == "PROFESSIONAL" and payload.get("subjectId"):
        return uuid.UUID(str(payload["subjectId"]))
    return None


async def on_professional_fact(session: AsyncSession, event: EventEnvelope) -> None:
    pid = _professional_id(event.payload)
    if pid:
        await service.rebuild(session, pid, event.occurredAt)


for _event_type in _EVENTS:
    subscribe(_event_type, consumer="search.professional_document")(on_professional_fact)
