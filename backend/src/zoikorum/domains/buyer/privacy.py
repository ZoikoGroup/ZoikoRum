"""Organisation memberships (shared/privacy.py). The sole administrator of a team must hand over first."""

from __future__ import annotations

import uuid

from sqlalchemy import any_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer.models import OrgMember, Organization
from zoikorum.shared import privacy
from zoikorum.shared.auth import OrgRole


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


privacy.register("buyer", export=export, blockers=blockers)
