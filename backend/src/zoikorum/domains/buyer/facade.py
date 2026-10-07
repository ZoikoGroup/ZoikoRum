"""Buyer facade - read-only interface other domains use.

Every buyer acts through an organization. An individual buyer gets an
INDIVIDUAL organization where they hold every org role.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer.models import CostCenter, OrgMember, Organization
from zoikorum.shared.money import Money


@dataclass(frozen=True)
class OrganizationSummary:
    id: uuid.UUID
    name: str
    org_type: str  # INDIVIDUAL | BUSINESS | ENTERPRISE
    country: str
    status: str  # ACTIVE | SUSPENDED
    business_context: str | None  # STARTUP|SME|MID_MARKET|ENTERPRISE|INDIVIDUAL


@dataclass(frozen=True)
class CostCenterSummary:
    id: uuid.UUID
    organization_id: uuid.UUID
    business_unit_id: uuid.UUID | None
    name: str
    quarterly_budget: Money | None


async def _active_member(session: AsyncSession, org_id: uuid.UUID, identity_id: uuid.UUID) -> OrgMember | None:
    return await session.scalar(
        select(OrgMember).where(
            OrgMember.organization_id == org_id, OrgMember.identity_id == identity_id, OrgMember.status == "ACTIVE"
        )
    )


async def get_organization(session: AsyncSession, org_id: uuid.UUID) -> OrganizationSummary | None:
    o = await session.get(Organization, org_id)
    if o is None:
        return None
    return OrganizationSummary(o.id, o.name, o.org_type, o.country, o.status, o.business_context)


async def get_member_roles(session: AsyncSession, org_id: uuid.UUID, identity_id: uuid.UUID) -> frozenset[str]:
    """Empty set when not a member."""
    m = await _active_member(session, org_id, identity_id)
    return frozenset(m.roles) if m else frozenset()


async def get_member_spend_limit(session: AsyncSession, org_id: uuid.UUID, identity_id: uuid.UUID) -> Money | None:
    """Approval authority. None => no limit configured (unlimited for ORG_ADMIN, zero otherwise)."""
    m = await _active_member(session, org_id, identity_id)
    if m is None or m.spend_limit_minor is None or not m.spend_limit_currency:
        return None
    return Money(m.spend_limit_minor, m.spend_limit_currency)


async def list_member_identities(
    session: AsyncSession, org_id: uuid.UUID, roles: Iterable[str] | None = None
) -> list[uuid.UUID]:
    stmt = select(OrgMember).where(OrgMember.organization_id == org_id, OrgMember.status == "ACTIVE")
    wanted = set(roles or [])
    return [m.identity_id for m in (await session.scalars(stmt)).all() if not wanted or wanted.intersection(m.roles)]


async def get_cost_center(session: AsyncSession, cost_center_id: uuid.UUID) -> CostCenterSummary | None:
    c = await session.get(CostCenter, cost_center_id)
    if c is None:
        return None
    budget = Money(c.quarterly_budget_minor, c.currency) if c.quarterly_budget_minor is not None and c.currency else None
    return CostCenterSummary(c.id, c.organization_id, c.business_unit_id, c.name, budget)


async def list_identity_organizations(session: AsyncSession, identity_id: uuid.UUID) -> list[uuid.UUID]:
    """Live memberships, including invitations accepted since the token was issued."""
    return list((await session.scalars(select(OrgMember.organization_id).where(
        OrgMember.identity_id == identity_id, OrgMember.status == "ACTIVE"))).all())
