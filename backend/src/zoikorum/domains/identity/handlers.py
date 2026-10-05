"""Identity reacts to other domains' facts to keep token claims current.

Links are a projection; the owning domains (professional, buyer, firm) stay
authoritative. Clients pick up new claims on their next token refresh.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe


def _uuid(v) -> uuid.UUID:
    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


@subscribe(E.PROFESSIONAL_REGISTERED, consumer="identity.link_professional")
async def on_professional_registered(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    await service.upsert_link(session, _uuid(p["identityId"]), "PROFESSIONAL", _uuid(p["professionalId"]), [], "PROFESSIONAL")


@subscribe(E.ORG_MEMBER_ADDED, consumer="identity.link_org_member")
@subscribe(E.BUYER_ROLE_ASSIGNED, consumer="identity.link_org_member")
async def on_org_member(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    await service.upsert_link(session, _uuid(p["identityId"]), "ORG_MEMBER", _uuid(p["organizationId"]),
                              p.get("roles", []), p.get("orgType"))


@subscribe(E.ORG_MEMBER_REMOVED, consumer="identity.unlink_org_member")
async def on_org_member_removed(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    await service.remove_link(session, _uuid(p["identityId"]), "ORG_MEMBER", _uuid(p["organizationId"]))


@subscribe(E.FIRM_MEMBER_JOINED, consumer="identity.link_firm_member")
@subscribe(E.FIRM_MEMBER_ROLES_CHANGED, consumer="identity.link_firm_member")
async def on_firm_member(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    await service.upsert_link(session, _uuid(p["identityId"]), "FIRM_MEMBER", _uuid(p["firmId"]), p.get("roles", []), "FIRM")


@subscribe(E.FIRM_MEMBER_REMOVED, consumer="identity.unlink_firm_member")
async def on_firm_member_removed(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    await service.remove_link(session, _uuid(p["identityId"]), "FIRM_MEMBER", _uuid(p["firmId"]))


@subscribe(E.ENFORCEMENT_ACTION_APPLIED, consumer="identity.apply_enforcement")
async def on_enforcement(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    if p.get("subjectType") == "IDENTITY" and p.get("action") in ("SUSPEND_ACCOUNT", "OFFBOARD"):
        await service.set_status(session, _uuid(p["subjectId"]), "SUSPENDED", p.get("reasonCode", "ENFORCEMENT"))


@subscribe(E.ENFORCEMENT_ACTION_REVERSED, consumer="identity.reverse_enforcement")
async def on_enforcement_reversed(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    if p.get("subjectType") == "IDENTITY" and p.get("action") == "SUSPEND_ACCOUNT":
        await service.set_status(session, _uuid(p["subjectId"]), "ACTIVE", "ENFORCEMENT_REVERSED")
