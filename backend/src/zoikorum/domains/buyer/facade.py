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

from zoikorum.shared.event_catalog import E

from zoikorum.domains.buyer.models import BusinessUnit, CostCenter, LegalEntity, OrgMember, Organization
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


async def list_business_unit_ids(session: AsyncSession, org_id: uuid.UUID) -> list[uuid.UUID]:
    return list((await session.scalars(select(BusinessUnit.id).where(
        BusinessUnit.organization_id == org_id))).all())


async def contracting_entity(session: AsyncSession, org_id: uuid.UUID, entity_id: uuid.UUID | None) -> dict | None:
    """The legal entity a request goes through: the one chosen (it must be this organisation's and active), otherwise
    the default; None when the organisation has none. A plain snapshot: contracts and invoices keep these details."""
    from zoikorum.shared.errors import ValidationFailed

    if entity_id is not None:
        e = await session.get(LegalEntity, entity_id)
        if e is None or e.organization_id != org_id or e.status != "ACTIVE":
            raise ValidationFailed("Choose one of your organisation's active legal entities", code="INVALID_LEGAL_ENTITY")
    else:
        e = await session.scalar(select(LegalEntity).where(
            LegalEntity.organization_id == org_id, LegalEntity.status == "ACTIVE", LegalEntity.is_default.is_(True)))
    if e is None:
        return None
    return {"id": str(e.id), "legalName": e.legal_name, "registrationNumber": e.registration_number, "country": e.country,
            "registeredAddress": e.registered_address, "taxId": e.tax_id}


async def member_roles_by_identity(session: AsyncSession, org_id: uuid.UUID) -> dict[uuid.UUID, set[str]]:
    """Active members of an organisation and their roles."""
    from zoikorum.domains.buyer.models import OrgMember

    rows = (await session.execute(select(OrgMember.identity_id, OrgMember.roles).where(
        OrgMember.organization_id == org_id, OrgMember.status == "ACTIVE"))).all()
    return {i: set(r) for i, r in rows}


async def setup_facts(session: AsyncSession, org_id: uuid.UUID) -> dict:
    """What an enterprise admin has set up so far (procurement setup wizard): organisation basics, members by role,
    business units, cost centres (and how many carry a quarterly budget), legal entities."""
    from sqlalchemy import func

    o = await session.get(Organization, org_id)
    if o is None:
        return {}
    roles: dict[str, int] = {}
    members = await member_roles_by_identity(session, org_id)
    for held in members.values():
        for r in held:
            roles[r] = roles.get(r, 0) + 1
    centres, budgeted = (await session.execute(select(func.count(), func.count(CostCenter.quarterly_budget_minor)).where(
        CostCenter.organization_id == org_id))).one()
    return {"orgType": o.org_type, "basicsComplete": bool(o.industry and o.time_zone),
            "members": len(members), "roles": roles,
            "businessUnits": await session.scalar(select(func.count()).select_from(BusinessUnit).where(BusinessUnit.organization_id == org_id)) or 0,
            "costCenters": centres or 0, "budgetedCostCenters": budgeted or 0,
            "legalEntities": await session.scalar(select(func.count()).select_from(LegalEntity).where(
                LegalEntity.organization_id == org_id, LegalEntity.status == "ACTIVE")) or 0}


async def business_unit_names(session: AsyncSession, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict((await session.execute(select(BusinessUnit.id, BusinessUnit.name).where(BusinessUnit.organization_id == org_id))).all())


async def set_api_key_tier(session: AsyncSession, actor, key_id: uuid.UUID, tier: str) -> dict:
    from zoikorum.domains.buyer import api_keys
    return await api_keys.set_tier(session, actor, key_id, tier)


async def api_key_principal(session: AsyncSession, token: str, path: str, method: str):
    from zoikorum.domains.buyer import api_keys
    return await api_keys.principal(session, token, path, method)


async def api_key_budget(session: AsyncSession, token: str):
    from zoikorum.domains.buyer import api_keys
    return await api_keys.budget_of(session, token)


async def ensure_member(session: AsyncSession, org_id: uuid.UUID, identity_id: uuid.UUID, email: str, name: str, roles: list[str]) -> None:
    """Single sign-on / SCIM: make the person an active member with these roles (added or re-activated)."""
    from zoikorum.domains.buyer.models import OrgMember, Organization
    from zoikorum.domains.buyer.service import _evt

    org = await session.get(Organization, org_id)
    m = await session.scalar(select(OrgMember).where(OrgMember.organization_id == org_id, OrgMember.identity_id == identity_id).with_for_update())
    if m is None:
        session.add(OrgMember(organization_id=org_id, identity_id=identity_id, email=email, display_name=name, roles=list(roles)))
        _evt(session, E.ORG_MEMBER_ADDED, org, identityId=identity_id, roles=list(roles), via="SSO")
    elif m.status != "ACTIVE" or sorted(m.roles) != sorted(roles):
        was_active = m.status == "ACTIVE"
        m.status, m.roles = "ACTIVE", list(roles)
        if not was_active:
            _evt(session, E.ORG_MEMBER_ADDED, org, identityId=identity_id, roles=list(roles), via="SSO")
    await session.flush()


async def deactivate_member(session: AsyncSession, org_id: uuid.UUID, identity_id: uuid.UUID) -> None:
    """SCIM: end the membership (the person's own account and history stay). The last Organisation Admin is kept."""
    from zoikorum.domains.buyer.models import OrgMember, Organization
    from zoikorum.domains.buyer.service import _evt
    from zoikorum.shared.errors import Conflict

    m = await session.scalar(select(OrgMember).where(OrgMember.organization_id == org_id, OrgMember.identity_id == identity_id).with_for_update())
    if m is None or m.status != "ACTIVE":
        return
    if "ORG_ADMIN" in m.roles:
        admins = (await session.scalars(select(OrgMember.id).where(OrgMember.organization_id == org_id, OrgMember.status == "ACTIVE",
                                                                   OrgMember.roles.contains(["ORG_ADMIN"])))).all()
        if len(admins) <= 1:
            raise Conflict("The last Organisation Admin cannot be removed by provisioning", code="LAST_ADMIN")
    m.status = "REMOVED"
    _evt(session, E.ORG_MEMBER_REMOVED, await session.get(Organization, org_id), identityId=identity_id, removedBy=None, via="SCIM")
    await session.flush()


# ---- Staff console search (admin/search.py) --------------------------------------------------------------------------

async def staff_search_organizations(session: AsyncSession, term: str, exact_id: uuid.UUID | None, limit: int) -> list[dict]:
    """Buyer organisations and enterprises whose name contains ``term`` (or whose id is ``exact_id``), names A-Z:
    [{"id", "name", "kind" (BUYER | ENTERPRISE), "status", "country"}]."""
    from sqlalchemy import func, or_

    like = "%" + term.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    match = [func.lower(Organization.name).like(like, escape="\\")]
    if exact_id:
        match.append(Organization.id == exact_id)
    rows = (await session.scalars(select(Organization).where(or_(*match)).order_by(Organization.name, Organization.id).limit(limit))).all()
    return [{"id": o.id, "name": o.name, "kind": "ENTERPRISE" if o.org_type == "ENTERPRISE" else "BUYER", "status": o.status,
             "country": o.country} for o in rows]
