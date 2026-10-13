"""Professional reacts to verification outcomes for its credential claims, firm membership changes, and engagements starting or ending (capacity)."""

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


@subscribe(E.CONTRACT_ACTIVATED, consumer="professional.engagement_started")
async def on_contract_activated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.engagement_count_changed(session, uuid.UUID(str(event.payload["professionalId"])), +1)


@subscribe(E.CONTRACT_COMPLETED, consumer="professional.engagement_ended")
@subscribe(E.CONTRACT_TERMINATED, consumer="professional.engagement_ended")
async def on_contract_ended(session: AsyncSession, event: EventEnvelope) -> None:
    await service.engagement_count_changed(session, uuid.UUID(str(event.payload["professionalId"])), -1)



@subscribe(E.TAXONOMY_SUGGESTION_RESOLVED, consumer="professional.add_suggested_specialization")
async def on_suggestion_resolved(session: AsyncSession, event: EventEnvelope) -> None:
    await service.suggestion_resolved(session, event.payload)
