from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.firm import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe


@subscribe(E.IDENTITY_CREATED, consumer="firm.create_firm_for_signup")
async def on_identity_created(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    if p.get("accountType") == "FIRM":
        await service.create_for_signup(session, uuid.UUID(p["identityId"]), p.get("organizationName"))


@subscribe(E.VERIFICATION_COMPLETED, consumer="firm.registration_verified")
async def on_verification_completed(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    if p.get("subjectType") == "FIRM" and p.get("verificationType") == "FIRM_REGISTRATION":
        await service.set_registration_verified(session, uuid.UUID(str(p["subjectId"])), True)


@subscribe(E.VERIFICATION_EXPIRED, consumer="firm.registration_lapsed")
@subscribe(E.VERIFICATION_REVOKED, consumer="firm.registration_lapsed")
async def on_verification_lapsed(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    if p.get("subjectType") == "FIRM" and p.get("verificationType") == "FIRM_REGISTRATION":
        await service.set_registration_verified(session, uuid.UUID(str(p["subjectId"])), False)
        await service.recheck_offerings(session, uuid.UUID(str(p["subjectId"])))


@subscribe(E.TRUST_TIER_CHANGED, consumer="firm.recheck_offerings_on_tier")
async def on_tier_changed(session: AsyncSession, event: EventEnvelope) -> None:
    """A delivering member's trust light changed: published regulated offerings must still have a licensed member."""
    from zoikorum.domains.professional import facade as professional_facade

    pro = await professional_facade.get_professional(session, uuid.UUID(str(event.payload["professionalId"])))
    if pro is not None and pro.firm_id is not None:
        await service.recheck_offerings(session, pro.firm_id)
