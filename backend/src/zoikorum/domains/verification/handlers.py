from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.verification import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe
from zoikorum.shared.relay import on_timer


@subscribe(E.CREDENTIAL_SUBMITTED, consumer="verification.open_credential_case")
async def on_credential_submitted(session: AsyncSession, event: EventEnvelope) -> None:
    await service.open_credential_case(session, event.payload)


@subscribe(E.CREDENTIAL_WITHDRAWN, consumer="verification.credential_withdrawn")
async def on_credential_withdrawn(session: AsyncSession, event: EventEnvelope) -> None:
    await service.credential_withdrawn(session, event.payload)


@subscribe(E.PROFILE_UPDATED, consumer="verification.profile_changed")
async def on_profile_updated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.profile_changed(session, event.payload, event.occurredAt)


@subscribe(E.FIRM_PROFILE_UPDATED, consumer="verification.firm_details_changed")
async def on_firm_profile_updated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.firm_details_changed(session, event.payload)


@subscribe(E.PROFESSIONAL_REGISTERED, consumer="verification.restrictions_screening")
async def on_professional_registered(session: AsyncSession, event: EventEnvelope) -> None:
    await service.open_restrictions_screening(session, event.payload)


@subscribe(E.VERIFICATION_EVIDENCE_SUBMITTED, consumer="verification.document_check")
async def on_evidence_submitted(session: AsyncSession, event: EventEnvelope) -> None:
    await service.check_evidence(session, event.payload)


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
