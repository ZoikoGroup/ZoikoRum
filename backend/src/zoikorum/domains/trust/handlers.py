from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.trust import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe


@subscribe(E.PROFESSIONAL_REGISTERED, consumer="trust.open_profile")
async def on_registered(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_professional_registered(session, event)


@subscribe(E.VERIFICATION_STARTED, consumer="trust.verification")
@subscribe(E.VERIFICATION_NEEDS_INFO, consumer="trust.verification")
@subscribe(E.VERIFICATION_COMPLETED, consumer="trust.verification")
@subscribe(E.VERIFICATION_FAILED, consumer="trust.verification")
@subscribe(E.VERIFICATION_EXPIRED, consumer="trust.verification")
@subscribe(E.VERIFICATION_REVOKED, consumer="trust.verification")
async def on_verification(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_verification(session, event)


@subscribe(E.PROFILE_UPDATED, consumer="trust.profile_changed")
@subscribe(E.JURISDICTIONS_UPDATED, consumer="trust.profile_changed")
async def on_profile_changed(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_profile_changed(session, event)


@subscribe(E.ENFORCEMENT_ACTION_APPLIED, consumer="trust.enforcement")
@subscribe(E.ENFORCEMENT_ACTION_REVERSED, consumer="trust.enforcement")
async def on_enforcement(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_enforcement(session, event)


@subscribe(E.RISK_FLAG_RAISED, consumer="trust.risk_flag")
async def on_risk_flag(session: AsyncSession, event: EventEnvelope) -> None:
    await service.on_risk_flag(session, event)
