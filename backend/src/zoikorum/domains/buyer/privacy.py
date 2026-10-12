"""Organisation memberships (shared/privacy.py). The sole administrator of a team must hand over first."""

from __future__ import annotations

import uuid

from sqlalchemy import any_, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer.models import Invitation, OrgMember, Organization
from zoikorum.shared import privacy
from zoikorum.shared.auth import OrgRole
from zoikorum.shared.ddl import ERASED_NAME


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    return {"organisationMemberships": await privacy.rows(session, OrgMember, OrgMember.identity_id == identity_id)}


async def blockers(session: AsyncSession, identity_id: uuid.UUID) -> list[str]:
    reasons = []
    admin = literal(OrgRole.ORG_ADMIN) == any_(OrgMember.roles)
    mine = (await session.execute(select(Organization.id, Organization.name).join(OrgMember, OrgMember.organization_id == Organization.id)
                                  .where(OrgMember.identity_id == identity_id, OrgMember.status == "ACTIVE", admin,
                                         Organization.status == "ACTIVE"))).all()
    for org_id, name in mine:
        others = select(func.count()).select_from(OrgMember).where(
            OrgMember.organization_id == org_id, OrgMember.status == "ACTIVE", OrgMember.identity_id != identity_id)
        other_admins = await session.scalar(others.where(admin))
        if not other_admins and await session.scalar(others):
            reasons.append(f"You are the only administrator of {name}. Make another member an administrator first.")
    return reasons


async def erase(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    """The person leaves every organisation: colleagues no longer see their name or email in team lists, they no longer
    count as an administrator, and invitations still waiting for their email address are withdrawn."""
    from zoikorum.domains.identity import facade as identity_facade

    who = await identity_facade.get_identity(session, identity_id)  # identity is erased last, so it is still readable
    removed = (await session.execute(update(OrgMember).where(OrgMember.identity_id == identity_id).values(
        status="REMOVED", email="", display_name=ERASED_NAME))).rowcount
    withdrawn = 0
    if who is not None:
        withdrawn = (await session.execute(update(Invitation).where(
            func.lower(Invitation.email) == who.email.lower(), Invitation.status == "PENDING").values(status="REVOKED"))).rowcount
    return {"membershipsEnded": removed, "invitationsWithdrawn": withdrawn}


privacy.register("buyer", export=export, erase=erase, blockers=blockers,
                 retained="Engagements and invoices of the organisation stay with the organisation; your name on them is "
                          "replaced where the law allows.")
