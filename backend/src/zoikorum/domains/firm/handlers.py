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
