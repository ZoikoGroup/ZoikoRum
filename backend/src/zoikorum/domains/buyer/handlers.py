from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe


@subscribe(E.IDENTITY_CREATED, consumer="buyer.create_organization_for_signup")
async def on_identity_created(session: AsyncSession, event: EventEnvelope) -> None:
    """Buyer and Enterprise sign-ups get their organization (Individual / Enterprise)."""
    p = event.payload
    await service.create_for_signup(session, uuid.UUID(p["identityId"]), p.get("accountType", ""), p.get("organizationName"))
