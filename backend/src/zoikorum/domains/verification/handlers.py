from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.verification import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe
from zoikorum.shared.relay import on_timer


@subscribe(E.CREDENTIAL_SUBMITTED, consumer="verification.open_credential_case")
async def on_credential_submitted(session: AsyncSession, event: EventEnvelope) -> None:
    await service.open_credential_case(session, event.payload)


@subscribe(E.PROFESSIONAL_REGISTERED, consumer="verification.restrictions_screening")
async def on_professional_registered(session: AsyncSession, event: EventEnvelope) -> None:
    await service.open_restrictions_screening(session, event.payload)


@on_timer(service.TIMER_REMINDER)
async def on_expiry_reminder(session: AsyncSession, key: str, payload: dict) -> None:
    await service.remind_expiring(session, payload)


@on_timer(service.TIMER_EXPIRY)
async def on_expiry(session: AsyncSession, key: str, payload: dict) -> None:
    await service.expire(session, payload)
@subscribe(E.ENFORCEMENT_ACTION_APPLIED, consumer="verification.enforcement")
async def enforcement_reset(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    if p.get("subjectType") == "PROFESSIONAL" and p.get("action") in ("CREDENTIAL_ENFORCEMENT", "VERIFICATION_RESET"):
        await service.enforcement_reset(session, p)
