"""Professional reacts to verification outcomes for its credential claims, and to firm membership changes."""

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


@subscribe(E.FIRM_MEMBER_JOINED, consumer="professional.firm_link_on_join")
async def on_firm_member_joined(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    await service.firm_member_joined(session, uuid.UUID(str(p["firmId"])), uuid.UUID(str(p["identityId"])))


@subscribe(E.FIRM_MEMBER_REMOVED, consumer="professional.firm_unlink_on_removal")
async def on_firm_member_removed(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    await service.firm_member_removed(session, uuid.UUID(str(p["firmId"])), uuid.UUID(str(p["identityId"])))
