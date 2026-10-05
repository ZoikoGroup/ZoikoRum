"""Professional reacts to verification outcomes for its credential claims."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.professional import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe

_CLAIM_STATUS = {
    E.VERIFICATION_COMPLETED: "VERIFIED",
    E.VERIFICATION_FAILED: "FAILED",
    E.VERIFICATION_EXPIRED: "EXPIRED",
    E.VERIFICATION_REVOKED: "REVOKED",
}


@subscribe(E.VERIFICATION_COMPLETED, consumer="professional.credential_status")
@subscribe(E.VERIFICATION_FAILED, consumer="professional.credential_status")
@subscribe(E.VERIFICATION_EXPIRED, consumer="professional.credential_status")
@subscribe(E.VERIFICATION_REVOKED, consumer="professional.credential_status")
async def on_verification_outcome(session: AsyncSession, event: EventEnvelope) -> None:
    claim_id = event.payload.get("credentialClaimId")
    if claim_id:
        await service.set_claim_status(session, uuid.UUID(str(claim_id)), _CLAIM_STATUS[event.eventType])
