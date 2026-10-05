"""Buyer domain commands: organizations, team invitations, roles and approval authority.

Authorization uses this domain's own membership table (authoritative), not token claims,
so role changes take effect immediately.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.buyer.models import BusinessUnit, CostCenter, Invitation, OrgMember, Organization
from zoikorum.domains.buyer.schemas import (
    BusinessUnitOut,
    CostCenterOut,
    InvitationOut,
    MemberOut,
    OrganizationOut,
)
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, AuthStrength, OrgRole
from zoikorum.shared.crypto import sha256_hex
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, StepUpRequired, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event
from zoikorum.shared.money import Money, MoneyDTO

INVITE_TTL = timedelta(days=7)
# Creator of an enterprise org. Exception Authority is deliberately NOT included: the doc
# requires exceptions to be approved by a distinct, named role (role separation).
CREATOR_ROLES = [OrgRole.ORG_ADMIN, OrgRole.REQUESTER, OrgRole.APPROVER, OrgRole.BUDGET_OWNER]


def _evt(session: AsyncSession, event_type: str, org: Organization, **payload) -> None:
    record_event(session, event_type, aggregate_type="Organization", aggregate_id=org.id, tenant_id=org.id,
                 payload={"organizationId": org.id, "orgType": org.org_type, **payload})


def _money(minor: int | None, ccy: str | None) -> MoneyDTO | None:
    return MoneyDTO(amountMinor=minor, currency=ccy) if minor is not None and ccy else None


# ---------------------------------------------------------------------------
# Organization lifecycle
# ---------------------------------------------------------------------------

async def create_for_signup(session: AsyncSession, identity_id: uuid.UUID, account_type: str, org_name: str | None) -> None:
    """Consumer of IDENTITY_CREATED. Idempotent per (creator, org type)."""
    org_type = {"BUYER": "INDIVIDUAL", "ENTERPRISE": "ENTERPRISE"}.get(account_type)
    if org_type is None:
        return
    exists = await session.scalar(
        select(Organization.id).where(Organization.created_by == identity_id, Organization.org_type == org_type)
    )
    if exists:
        return
    who = await identity_facade.get_identity(session, identity_id)
    if who is None:
        return
    org = Organization(
        name=(org_name or who.display_name).strip(),
        org_type=org_type,
        country=who.country,
        business_context="INDIVIDUAL" if org_type == "INDIVIDUAL" else "ENTERPRISE",
        created_by=identity_id,
    )
    session.add(org)
    await session.flush()
    # An individual buyer holds every role in their own organization.
    roles = sorted(OrgRole.ALL) if org_type == "INDIVIDUAL" else CREATOR_ROLES
    member = OrgMember(organization_id=org.id, identity_id=identity_id, email=who.email,
                       display_name=who.display_name, roles=roles)
    session.add(member)
    _evt(session, E.ORGANIZATION_CREATED, org, name=org.name, country=org.country, createdBy=identity_id)
    if org_type == "INDIVIDUAL":
        record_event(session, E.BUYER_REGISTERED, aggregate_type="Organization", aggregate_id=org.id, tenant_id=org.id,
                     payload={"identityId": identity_id, "organizationId": org.id})
    _evt(session, E.ORG_MEMBER_ADDED, org, identityId=identity_id, roles=roles)


async def _org(session: AsyncSession, org_id: uuid.UUID, lock: bool = False) -> Organization:
    org = await session.get(Organization, org_id, with_for_update=lock)
    if org is None or org.status != "ACTIVE":
        raise NotFound("Organization not found")
    return org


async def _member(session: AsyncSession, org_id: uuid.UUID, identity_id: uuid.UUID) -> OrgMember | None:
    return await session.scalar(
        select(OrgMember).where(
            OrgMember.organization_id == org_id, OrgMember.identity_id == identity_id, OrgMember.status == "ACTIVE"
        )
    )


async def _require_member(session: AsyncSession, actor: Actor, org_id: uuid.UUID, *roles: str) -> OrgMember:
    m = await _member(session, org_id, actor.identity_id)
    if m is None:
        raise NotFound("Organization not found")  # don't reveal orgs you are not part of
    if roles and not set(roles).intersection(m.roles):
        names = " or ".join(r.replace("_", " ").title() for r in roles)
        raise Forbidden(f"Only {names} members can do this", code="ORG_ROLE_REQUIRED")
    return m


def _require_mfa_session(actor: Actor) -> None:
    # Team and authority changes are high-impact: require an MFA-backed session.
    if actor.auth_strength not in AuthStrength.ELEVATED:
        raise StepUpRequired("Confirm with your authenticator code to change team access")


async def _out(session: AsyncSession, org: Organization, my_roles: list[str]) -> OrganizationOut:
    count = await session.scalar(
        select(func.count()).select_from(OrgMember).where(OrgMember.organization_id == org.id, OrgMember.status == "ACTIVE")
    )
    return OrganizationOut(id=org.id, name=org.name, orgType=org.org_type, country=org.country, status=org.status,
                           businessContext=org.business_context, myRoles=sorted(my_roles), memberCount=count or 0,
                           createdAt=org.created_at)


async def my_organizations(session: AsyncSession, actor: Actor) -> list[OrganizationOut]:
    rows = (
        await session.execute(
            select(Organization, OrgMember)
            .join(OrgMember, OrgMember.organization_id == Organization.id)
            .where(OrgMember.identity_id == actor.identity_id, OrgMember.status == "ACTIVE", Organization.status == "ACTIVE")
            .order_by(Organization.created_at)
        )
    ).all()
    return [await _out(session, org, m.roles) for org, m in rows]


async def get_organization(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> OrganizationOut:
    m = await _require_member(session, actor, org_id)
    return await _out(session, await _org(session, org_id), m.roles)


async def update_organization(session: AsyncSession, actor: Actor, org_id: uuid.UUID, name: str | None, ctx: str | None) -> OrganizationOut:
    m = await _require_member(session, actor, org_id, OrgRole.ORG_ADMIN)
    org = await _org(session, org_id, lock=True)
    changes = {}
    if name and name.strip() != org.name:
        org.name = changes["name"] = name.strip()
    if ctx and ctx != org.business_context:
        org.business_context = changes["businessContext"] = ctx
    if changes:
        _evt(session, E.ORGANIZATION_UPDATED, org, changes=changes, updatedBy=actor.identity_id)
    return await _out(session, org, m.roles)


# ---------------------------------------------------------------------------
# Members, roles, approval authority
# ---------------------------------------------------------------------------

def _member_out(m: OrgMember) -> MemberOut:
    return MemberOut(identityId=m.identity_id, email=m.email, displayName=m.display_name, roles=sorted(m.roles),
                     spendLimit=_money(m.spend_limit_minor, m.spend_limit_currency),
                     businessUnitId=m.business_unit_id, joinedAt=m.created_at)


async def list_members(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> list[MemberOut]:
    await _require_member(session, actor, org_id)
    rows = (
        await session.scalars(
            select(OrgMember)
            .where(OrgMember.organization_id == org_id, OrgMember.status == "ACTIVE")
            .order_by(OrgMember.display_name)
            .limit(1000)
        )
    ).all()
    return [_member_out(m) for m in rows]


async def _admin_count(session: AsyncSession, org_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count()).select_from(OrgMember).where(
            OrgMember.organization_id == org_id, OrgMember.status == "ACTIVE", OrgMember.roles.contains([OrgRole.ORG_ADMIN])
        )
    ) or 0


async def _check_business_unit(session: AsyncSession, org_id: uuid.UUID, bu_id: uuid.UUID | None) -> None:
    if bu_id is None:
        return
    bu = await session.get(BusinessUnit, bu_id)
    if bu is None or bu.organization_id != org_id:
        raise ValidationFailed("Business unit does not belong to this organization")


async def update_member(
    session: AsyncSession, actor: Actor, org_id: uuid.UUID, identity_id: uuid.UUID,
    roles: list[str] | None, spend_limit: MoneyDTO | None, clear_spend_limit: bool, business_unit_id: uuid.UUID | None,
) -> MemberOut:
    await _require_member(session, actor, org_id, OrgRole.ORG_ADMIN)
    _require_mfa_session(actor)
    org = await _org(session, org_id, lock=True)  # serialises admin-count checks
    if org.org_type == "INDIVIDUAL":
        raise Conflict("Individual buyer accounts have a single member", code="INDIVIDUAL_ORG")
    m = await _member(session, org_id, identity_id)
    if m is None:
        raise NotFound("Member not found")

    if roles is not None:
        new = sorted(set(roles))
        if OrgRole.ORG_ADMIN in m.roles and OrgRole.ORG_ADMIN not in new and await _admin_count(session, org_id) <= 1:
            raise Conflict("An organization must keep at least one Org Admin", code="LAST_ADMIN")
        if new != sorted(m.roles):
            m.roles = new
            _evt(session, E.BUYER_ROLE_ASSIGNED, org, identityId=identity_id, roles=new, assignedBy=actor.identity_id)

    if clear_spend_limit or spend_limit is not None:
        limit = spend_limit.to_money() if spend_limit else None
        m.spend_limit_minor = limit.minor if limit else None
        m.spend_limit_currency = limit.currency if limit else None
        _evt(session, E.SPEND_LIMIT_UPDATED, org, identityId=identity_id,
             spendLimit=limit.to_dict() if limit else None, updatedBy=actor.identity_id)

    if business_unit_id is not None and business_unit_id != m.business_unit_id:
        await _check_business_unit(session, org_id, business_unit_id)
        m.business_unit_id = business_unit_id
    return _member_out(m)


async def remove_member(session: AsyncSession, actor: Actor, org_id: uuid.UUID, identity_id: uuid.UUID) -> None:
    leaving_self = identity_id == actor.identity_id
    if not leaving_self:
        await _require_member(session, actor, org_id, OrgRole.ORG_ADMIN)
        _require_mfa_session(actor)
    org = await _org(session, org_id, lock=True)
    if org.org_type == "INDIVIDUAL":
        raise Conflict("Individual buyer accounts have a single member", code="INDIVIDUAL_ORG")
    m = await _member(session, org_id, identity_id)
    if m is None:
        raise NotFound("Member not found")
    if OrgRole.ORG_ADMIN in m.roles and await _admin_count(session, org_id) <= 1:
        raise Conflict("An organization must keep at least one Org Admin", code="LAST_ADMIN")
    m.status = "REMOVED"
    _evt(session, E.ORG_MEMBER_REMOVED, org, identityId=identity_id, removedBy=actor.identity_id)


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

def _invite_url(token: str) -> str | None:
    s = get_settings()
    if s.env == "production":
        return None  # sent by email only
    return f"{s.frontend_url}/invite?kind=org&token={token}"


async def _invitation_out(session: AsyncSession, inv: Invitation, token: str | None = None) -> InvitationOut:
    org = await session.get(Organization, inv.organization_id)
    return InvitationOut(
        id=inv.id, organizationId=inv.organization_id, organizationName=org.name if org else "", email=inv.email,
        roles=sorted(inv.roles), spendLimit=_money(inv.spend_limit_minor, inv.spend_limit_currency),
        status="EXPIRED" if inv.status == "PENDING" and inv.expires_at <= clock.now() else inv.status,
        expiresAt=inv.expires_at, createdAt=inv.created_at, devInviteUrl=_invite_url(token) if token else None,
    )


async def invite(
    session: AsyncSession, actor: Actor, org_id: uuid.UUID, email: str, roles: list[str],
    spend_limit: MoneyDTO | None, business_unit_id: uuid.UUID | None,
) -> InvitationOut:
    await _require_member(session, actor, org_id, OrgRole.ORG_ADMIN)
    _require_mfa_session(actor)
    org = await _org(session, org_id, lock=True)
    if org.org_type == "INDIVIDUAL":
        raise Conflict("Individual buyer accounts cannot invite a team. Create an Enterprise account instead.",
                       code="INDIVIDUAL_ORG")
    email = email.strip().lower()
    existing = await session.scalar(
        select(OrgMember).where(OrgMember.organization_id == org_id, OrgMember.email == email, OrgMember.status == "ACTIVE")
    )
    if existing:
        raise Conflict(f"{email} is already a member of {org.name}", code="ALREADY_MEMBER")
    await _check_business_unit(session, org_id, business_unit_id)
    # Re-inviting replaces any earlier pending invitation for the same email.
    for old in (await session.scalars(
        select(Invitation).where(Invitation.organization_id == org_id, Invitation.email == email, Invitation.status == "PENDING")
    )).all():
        old.status = "REVOKED"

    token = secrets.token_urlsafe(32)
    limit = spend_limit.to_money() if spend_limit else None
    inv = Invitation(
        organization_id=org_id, email=email, roles=sorted(set(roles)),
        spend_limit_minor=limit.minor if limit else None, spend_limit_currency=limit.currency if limit else None,
        business_unit_id=business_unit_id, token_hash=sha256_hex(token),
        expires_at=clock.now() + INVITE_TTL, invited_by=actor.identity_id,
    )
    session.add(inv)
    await session.flush()
    _evt(session, E.ORG_MEMBER_INVITED, org, invitationId=inv.id, email=email, roles=inv.roles,
         invitedBy=actor.identity_id, expiresAt=inv.expires_at)
    return await _invitation_out(session, inv, token)


async def list_invitations(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> list[InvitationOut]:
    await _require_member(session, actor, org_id, OrgRole.ORG_ADMIN)
    rows = (
        await session.scalars(
            select(Invitation)
            .where(Invitation.organization_id == org_id, Invitation.status == "PENDING")
            .order_by(Invitation.created_at.desc())
            .limit(500)
        )
    ).all()
    return [await _invitation_out(session, i) for i in rows]


async def revoke_invitation(session: AsyncSession, actor: Actor, org_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
    await _require_member(session, actor, org_id, OrgRole.ORG_ADMIN)
    inv = await session.get(Invitation, invitation_id, with_for_update=True)
    if inv is None or inv.organization_id != org_id:
        raise NotFound("Invitation not found")
    if inv.status == "PENDING":
        inv.status = "REVOKED"
        inv.responded_at = clock.now()
        _evt(session, E.ORG_INVITATION_REVOKED, await _org(session, org_id), invitationId=inv.id,
             email=inv.email, revokedBy=actor.identity_id)


async def my_invitations(session: AsyncSession, actor: Actor) -> list[InvitationOut]:
    rows = (
        await session.scalars(
            select(Invitation)
            .where(Invitation.email == (actor.email or "").lower(), Invitation.status == "PENDING",
                   Invitation.expires_at > clock.now())
            .order_by(Invitation.created_at.desc())
        )
    ).all()
    return [await _invitation_out(session, i) for i in rows]


async def _load_for_response(session: AsyncSession, actor: Actor, *, token: str | None, invitation_id: uuid.UUID | None) -> Invitation:
    if token:
        inv = await session.scalar(select(Invitation).where(Invitation.token_hash == sha256_hex(token)).with_for_update())
    else:
        inv = await session.get(Invitation, invitation_id, with_for_update=True)
    if inv is None:
        raise NotFound("Invitation not found")
    who = await identity_facade.get_identity(session, actor.identity_id)
    if who is None or who.email.lower() != inv.email:
        raise Forbidden(f"This invitation was sent to {inv.email}. Sign in with that email to accept it.",
                        code="INVITATION_EMAIL_MISMATCH")
    # Accepting from the in-app list (no token) proves nothing about the mailbox: require a confirmed email.
    if not token and not who.email_confirmed:
        raise Forbidden("Confirm your email address before accepting invitations", code="EMAIL_NOT_CONFIRMED")
    if inv.status != "PENDING":
        raise Conflict(f"This invitation is {inv.status.lower()}", code="INVITATION_NOT_PENDING")
    if inv.expires_at <= clock.now():
        raise Conflict("This invitation has expired. Ask the organization admin to send a new one.",
                       code="INVITATION_EXPIRED")
    return inv


async def accept_invitation(
    session: AsyncSession, actor: Actor, *, token: str | None = None, invitation_id: uuid.UUID | None = None
) -> OrganizationOut:
    inv = await _load_for_response(session, actor, token=token, invitation_id=invitation_id)
    org = await _org(session, inv.organization_id, lock=True)
    who = await identity_facade.get_identity(session, actor.identity_id)
    m = await session.scalar(
        select(OrgMember).where(OrgMember.organization_id == org.id, OrgMember.identity_id == actor.identity_id)
    )
    if m is None:
        m = OrgMember(organization_id=org.id, identity_id=actor.identity_id, email=who.email,
                      display_name=who.display_name, roles=inv.roles)
        session.add(m)
    else:  # re-joining after removal
        m.status, m.roles = "ACTIVE", inv.roles
    m.spend_limit_minor, m.spend_limit_currency = inv.spend_limit_minor, inv.spend_limit_currency
    m.business_unit_id = inv.business_unit_id
    inv.status = "ACCEPTED"
    inv.responded_at = clock.now()
    _evt(session, E.ORG_MEMBER_ADDED, org, identityId=actor.identity_id, roles=inv.roles, invitationId=inv.id)
    await session.flush()
    return await _out(session, org, m.roles)


async def decline_invitation(session: AsyncSession, actor: Actor, invitation_id: uuid.UUID) -> None:
    inv = await _load_for_response(session, actor, token=None, invitation_id=invitation_id)
    inv.status = "DECLINED"
    inv.responded_at = clock.now()


# ---------------------------------------------------------------------------
# Structure: business units and cost centers
# ---------------------------------------------------------------------------

async def create_business_unit(session: AsyncSession, actor: Actor, org_id: uuid.UUID, name: str, parent_id: uuid.UUID | None) -> BusinessUnitOut:
    await _require_member(session, actor, org_id, OrgRole.ORG_ADMIN)
    org = await _org(session, org_id)
    await _check_business_unit(session, org_id, parent_id)
    if await session.scalar(select(BusinessUnit.id).where(BusinessUnit.organization_id == org_id, BusinessUnit.name == name.strip())):
        raise Conflict("A business unit with this name already exists", code="DUPLICATE_NAME")
    bu = BusinessUnit(organization_id=org_id, name=name.strip(), parent_id=parent_id)
    session.add(bu)
    await session.flush()
    _evt(session, E.BUSINESS_UNIT_CREATED, org, businessUnitId=bu.id, name=bu.name, parentId=parent_id)
    return BusinessUnitOut(id=bu.id, name=bu.name, parentId=bu.parent_id)


async def list_business_units(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> list[BusinessUnitOut]:
    await _require_member(session, actor, org_id)
    rows = (await session.scalars(select(BusinessUnit).where(BusinessUnit.organization_id == org_id).order_by(BusinessUnit.name))).all()
    return [BusinessUnitOut(id=b.id, name=b.name, parentId=b.parent_id) for b in rows]


def _cc_out(c: CostCenter) -> CostCenterOut:
    return CostCenterOut(id=c.id, name=c.name, code=c.code, businessUnitId=c.business_unit_id,
                         quarterlyBudget=_money(c.quarterly_budget_minor, c.currency))


async def create_cost_center(
    session: AsyncSession, actor: Actor, org_id: uuid.UUID, name: str, code: str,
    business_unit_id: uuid.UUID | None, budget: MoneyDTO | None,
) -> CostCenterOut:
    await _require_member(session, actor, org_id, OrgRole.ORG_ADMIN, OrgRole.BUDGET_OWNER)
    org = await _org(session, org_id)
    await _check_business_unit(session, org_id, business_unit_id)
    if await session.scalar(select(CostCenter.id).where(CostCenter.organization_id == org_id, CostCenter.code == code)):
        raise Conflict("A cost center with this code already exists", code="DUPLICATE_CODE")
    b: Money | None = budget.to_money() if budget else None
    cc = CostCenter(organization_id=org_id, business_unit_id=business_unit_id, name=name.strip(), code=code,
                    quarterly_budget_minor=b.minor if b else None, currency=b.currency if b else None)
    session.add(cc)
    await session.flush()
    _evt(session, E.COST_CENTER_CREATED, org, costCenterId=cc.id, code=code, name=cc.name,
         quarterlyBudget=b.to_dict() if b else None)
    return _cc_out(cc)


async def list_cost_centers(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> list[CostCenterOut]:
    await _require_member(session, actor, org_id)
    rows = (await session.scalars(select(CostCenter).where(CostCenter.organization_id == org_id).order_by(CostCenter.code))).all()
    return [_cc_out(c) for c in rows]
