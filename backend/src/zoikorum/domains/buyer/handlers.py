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


@subscribe(E.FEDERATION_PROVISIONED, consumer="buyer.sync_federated_membership")
async def on_federation_provisioned(session: AsyncSession, event: EventEnvelope) -> None:
    from sqlalchemy import select
    from zoikorum.domains.identity import facade as identity
    from zoikorum.domains.buyer.models import OrgMember, Organization
    from zoikorum.shared.auth import OrgRole
    from zoikorum.shared.events import record_event
    p = event.payload
    identity_id, org_id = uuid.UUID(p["identityId"]), uuid.UUID(p["organizationId"])
    # Read current authoritative provisioning state; late events cannot reactivate a user.
    binding = await identity.federated_membership(session, identity_id, org_id)
    org = await session.get(Organization, org_id)
    if not binding or not org or org.org_type != "ENTERPRISE":
        return
    row = await session.scalar(select(OrgMember).where(OrgMember.organization_id == org_id,
        OrgMember.identity_id == identity_id).with_for_update())
    if not row:
        row = OrgMember(organization_id=org_id, identity_id=identity_id, email=binding["email"],
            display_name=binding["displayName"], roles=[OrgRole.REQUESTER])
        session.add(row)
    row.status = "ACTIVE" if binding["active"] else "REMOVED"
    row.email, row.display_name = binding["email"], binding["displayName"]
    await session.flush()
    record_event(session, E.ORG_MEMBER_ADDED if binding["active"] else E.ORG_MEMBER_REMOVED,
        aggregate_type="Organization", aggregate_id=org_id, tenant_id=org_id,
        payload={"identityId": identity_id, "organizationId": org_id, "roles": row.roles, "orgType": org.org_type})
