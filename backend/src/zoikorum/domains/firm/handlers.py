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
