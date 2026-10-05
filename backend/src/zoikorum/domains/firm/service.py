"""Firm domain commands: firm profile, members and their roles, invitations."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.firm.models import Firm, FirmInvitation, FirmMember
from zoikorum.domains.firm.schemas import FirmInvitationOut, FirmMemberOut, FirmOut, FirmPatch
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, AuthStrength, FirmRole
from zoikorum.shared.crypto import sha256_hex
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, StepUpRequired, VersionConflict
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

INVITE_TTL = timedelta(days=7)


def _evt(session: AsyncSession, event_type: str, firm: Firm, **payload) -> None:
    record_event(session, event_type, aggregate_type="Firm", aggregate_id=firm.id, tenant_id=firm.id,
                 payload={"firmId": firm.id, **payload})


async def create_for_signup(session: AsyncSession, identity_id: uuid.UUID, legal_name: str | None) -> None:
    """Consumer of IDENTITY_CREATED for Firm sign-ups. Idempotent per creator."""
    if await session.scalar(select(Firm.id).where(Firm.created_by == identity_id)):
        return
    who = await identity_facade.get_identity(session, identity_id)
    if who is None:
        return
    firm = Firm(legal_name=(legal_name or who.display_name).strip(), hq_country=who.country, created_by=identity_id)
    session.add(firm)
    await session.flush()
    roles = [FirmRole.FIRM_ADMIN]
    session.add(FirmMember(firm_id=firm.id, identity_id=identity_id, email=who.email, display_name=who.display_name, roles=roles))
    _evt(session, E.FIRM_REGISTERED, firm, identityId=identity_id, legalName=firm.legal_name)
    _evt(session, E.FIRM_MEMBER_JOINED, firm, identityId=identity_id, roles=roles)


async def set_registration_verified(session: AsyncSession, firm_id: uuid.UUID, verified: bool) -> None:
    """Consumer of firm-registration verification outcomes. Idempotent; suspension wins."""
    firm = await session.get(Firm, firm_id, with_for_update=True)
    if firm is None or firm.status == "SUSPENDED":
        return
    target = "VERIFIED" if verified else "PENDING_VERIFICATION"
    if firm.status == target:
        return
    firm.status = target
    if verified:
        _evt(session, E.FIRM_VERIFIED, firm)
    else:
        _evt(session, E.FIRM_PROFILE_UPDATED, firm, changes={"status": target}, updatedBy=None)


async def _firm(session: AsyncSession, firm_id: uuid.UUID, lock: bool = False) -> Firm:
    firm = await session.get(Firm, firm_id, with_for_update=lock)
    if firm is None or firm.status == "SUSPENDED":
        raise NotFound("Firm not found")
    return firm


async def _member(session: AsyncSession, firm_id: uuid.UUID, identity_id: uuid.UUID) -> FirmMember | None:
    return await session.scalar(
        select(FirmMember).where(FirmMember.firm_id == firm_id, FirmMember.identity_id == identity_id, FirmMember.status == "ACTIVE")
    )


async def _require_member(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, *roles: str) -> FirmMember:
    m = await _member(session, firm_id, actor.identity_id)
    if m is None:
        raise NotFound("Firm not found")
    if roles and not set(roles).intersection(m.roles):
        raise Forbidden("Only Firm Admins can do this", code="FIRM_ROLE_REQUIRED")
    return m


def _require_mfa_session(actor: Actor) -> None:
    if actor.auth_strength not in AuthStrength.ELEVATED:
        raise StepUpRequired("Confirm with your authenticator code to change firm access")


async def _count(session: AsyncSession, firm_id: uuid.UUID, role: str | None = None) -> int:
    stmt = select(func.count()).select_from(FirmMember).where(FirmMember.firm_id == firm_id, FirmMember.status == "ACTIVE")
    if role:
        stmt = stmt.where(FirmMember.roles.contains([role]))
    return await session.scalar(stmt) or 0


async def _out(session: AsyncSession, firm: Firm, my_roles: list[str]) -> FirmOut:
    return FirmOut(
        id=firm.id, legalName=firm.legal_name, tradingName=firm.trading_name, registrationNumber=firm.registration_number,
        hqCountry=firm.hq_country, sizeBand=firm.size_band, primaryCategory=firm.primary_category, website=firm.website,
        status=firm.status, myRoles=sorted(my_roles), memberCount=await _count(session, firm.id),
        hasAuthorizedRepresentative=await _count(session, firm.id, FirmRole.AUTHORIZED_REPRESENTATIVE) > 0,
        version=firm.version, createdAt=firm.created_at,
    )


async def my_firms(session: AsyncSession, actor: Actor) -> list[FirmOut]:
    rows = (
        await session.execute(
            select(Firm, FirmMember).join(FirmMember, FirmMember.firm_id == Firm.id)
            .where(FirmMember.identity_id == actor.identity_id, FirmMember.status == "ACTIVE")
            .order_by(Firm.created_at)
        )
    ).all()
    return [await _out(session, f, m.roles) for f, m in rows]


async def get_firm(session: AsyncSession, actor: Actor, firm_id: uuid.UUID) -> FirmOut:
    m = await _require_member(session, actor, firm_id)
    return await _out(session, await _firm(session, firm_id), m.roles)


async def update_firm(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, patch: FirmPatch, if_match: int | None) -> FirmOut:
    """Firm profile basics (Onboarding s.7). Optimistic concurrency via If-Match: <version>."""
    m = await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    firm = await _firm(session, firm_id, lock=True)
    if if_match is not None and if_match != firm.version:
        raise VersionConflict("The firm profile was changed by someone else. Reload and try again.")
    fields = {"legalName": "legal_name", "tradingName": "trading_name", "registrationNumber": "registration_number",
              "hqCountry": "hq_country", "sizeBand": "size_band", "primaryCategory": "primary_category", "website": "website"}
    changes = {}
    for api_name, col in fields.items():
        value = getattr(patch, api_name)
        if value is not None:
            value = (value.strip() or None) if isinstance(value, str) else value
            if value is None and col in ("legal_name", "hq_country"):
                continue  # required fields cannot be blanked
            if value != getattr(firm, col):
                setattr(firm, col, value)
                changes[api_name] = value
    if changes:
        if "legalName" in changes or "registrationNumber" in changes:
            # Identity-defining facts changed: verification must be redone.
            firm.status = "PENDING_VERIFICATION"
        _evt(session, E.FIRM_PROFILE_UPDATED, firm, changes=changes, updatedBy=actor.identity_id)
        await session.flush()
    return await _out(session, firm, m.roles)


def _member_out(m: FirmMember) -> FirmMemberOut:
    return FirmMemberOut(identityId=m.identity_id, email=m.email, displayName=m.display_name, roles=sorted(m.roles), joinedAt=m.created_at)


async def list_members(session: AsyncSession, actor: Actor, firm_id: uuid.UUID) -> list[FirmMemberOut]:
    await _require_member(session, actor, firm_id)
    rows = (await session.scalars(
        select(FirmMember).where(FirmMember.firm_id == firm_id, FirmMember.status == "ACTIVE").order_by(FirmMember.display_name)
    )).all()
    return [_member_out(m) for m in rows]


async def update_member_roles(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, identity_id: uuid.UUID, roles: list[str]) -> FirmMemberOut:
    await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    _require_mfa_session(actor)
    firm = await _firm(session, firm_id, lock=True)
    m = await _member(session, firm_id, identity_id)
    if m is None:
        raise NotFound("Member not found")
    new = sorted(set(roles))
    if FirmRole.FIRM_ADMIN in m.roles and FirmRole.FIRM_ADMIN not in new and await _count(session, firm_id, FirmRole.FIRM_ADMIN) <= 1:
        raise Conflict("A firm must keep at least one Firm Admin", code="LAST_ADMIN")
    if new != sorted(m.roles):
        m.roles = new
        _evt(session, E.FIRM_MEMBER_ROLES_CHANGED, firm, identityId=identity_id, roles=new, changedBy=actor.identity_id)
    return _member_out(m)


async def remove_member(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, identity_id: uuid.UUID) -> None:
    if identity_id != actor.identity_id:
        await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
        _require_mfa_session(actor)
    firm = await _firm(session, firm_id, lock=True)
    m = await _member(session, firm_id, identity_id)
    if m is None:
        raise NotFound("Member not found")
    if FirmRole.FIRM_ADMIN in m.roles and await _count(session, firm_id, FirmRole.FIRM_ADMIN) <= 1:
        raise Conflict("A firm must keep at least one Firm Admin", code="LAST_ADMIN")
    m.status = "REMOVED"
    _evt(session, E.FIRM_MEMBER_REMOVED, firm, identityId=identity_id, removedBy=actor.identity_id)


# ---- Invitations -----------------------------------------------------------

def _invite_url(token: str) -> str | None:
    s = get_settings()
    return None if s.env == "production" else f"{s.frontend_url}/invite?kind=firm&token={token}"


async def _inv_out(session: AsyncSession, inv: FirmInvitation, token: str | None = None) -> FirmInvitationOut:
    firm = await session.get(Firm, inv.firm_id)
    return FirmInvitationOut(
        id=inv.id, firmId=inv.firm_id, firmName=firm.legal_name if firm else "", email=inv.email, roles=sorted(inv.roles),
        status="EXPIRED" if inv.status == "PENDING" and inv.expires_at <= clock.now() else inv.status,
        expiresAt=inv.expires_at, createdAt=inv.created_at, devInviteUrl=_invite_url(token) if token else None,
    )


async def invite(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, email: str, roles: list[str]) -> FirmInvitationOut:
    await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    _require_mfa_session(actor)
    firm = await _firm(session, firm_id, lock=True)
    email = email.strip().lower()
    if await session.scalar(select(FirmMember.id).where(FirmMember.firm_id == firm_id, FirmMember.email == email, FirmMember.status == "ACTIVE")):
        raise Conflict(f"{email} is already a member of {firm.legal_name}", code="ALREADY_MEMBER")
    for old in (await session.scalars(select(FirmInvitation).where(
        FirmInvitation.firm_id == firm_id, FirmInvitation.email == email, FirmInvitation.status == "PENDING"
    ))).all():
        old.status = "REVOKED"
    token = secrets.token_urlsafe(32)
    inv = FirmInvitation(firm_id=firm_id, email=email, roles=sorted(set(roles)), token_hash=sha256_hex(token),
                         expires_at=clock.now() + INVITE_TTL, invited_by=actor.identity_id)
    session.add(inv)
    await session.flush()
    _evt(session, E.FIRM_MEMBER_INVITED, firm, invitationId=inv.id, email=email, roles=inv.roles, invitedBy=actor.identity_id)
    return await _inv_out(session, inv, token)


async def list_invitations(session: AsyncSession, actor: Actor, firm_id: uuid.UUID) -> list[FirmInvitationOut]:
    await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    rows = (await session.scalars(select(FirmInvitation).where(
        FirmInvitation.firm_id == firm_id, FirmInvitation.status == "PENDING").order_by(FirmInvitation.created_at.desc()))).all()
    return [await _inv_out(session, i) for i in rows]


async def revoke_invitation(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
    await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    inv = await session.get(FirmInvitation, invitation_id, with_for_update=True)
    if inv is None or inv.firm_id != firm_id:
        raise NotFound("Invitation not found")
    if inv.status == "PENDING":
        inv.status = "REVOKED"
        inv.responded_at = clock.now()
        _evt(session, E.FIRM_INVITATION_REVOKED, await _firm(session, firm_id), invitationId=inv.id, email=inv.email)


async def my_invitations(session: AsyncSession, actor: Actor) -> list[FirmInvitationOut]:
    rows = (await session.scalars(select(FirmInvitation).where(
        FirmInvitation.email == (actor.email or "").lower(), FirmInvitation.status == "PENDING",
        FirmInvitation.expires_at > clock.now()))).all()
    return [await _inv_out(session, i) for i in rows]


async def _load_for_response(session: AsyncSession, actor: Actor, *, token: str | None, invitation_id: uuid.UUID | None) -> FirmInvitation:
    if token:
        inv = await session.scalar(select(FirmInvitation).where(FirmInvitation.token_hash == sha256_hex(token)).with_for_update())
    else:
        inv = await session.get(FirmInvitation, invitation_id, with_for_update=True)
    if inv is None:
        raise NotFound("Invitation not found")
    who = await identity_facade.get_identity(session, actor.identity_id)
    if who is None or who.email.lower() != inv.email:
        raise Forbidden(f"This invitation was sent to {inv.email}. Sign in with that email to accept it.",
                        code="INVITATION_EMAIL_MISMATCH")
    if not token and not who.email_confirmed:
        raise Forbidden("Confirm your email address before accepting invitations", code="EMAIL_NOT_CONFIRMED")
    if inv.status != "PENDING":
        raise Conflict(f"This invitation is {inv.status.lower()}", code="INVITATION_NOT_PENDING")
    if inv.expires_at <= clock.now():
        raise Conflict("This invitation has expired. Ask the firm admin to send a new one.", code="INVITATION_EXPIRED")
    return inv


async def accept_invitation(session: AsyncSession, actor: Actor, *, token: str | None = None, invitation_id: uuid.UUID | None = None) -> FirmOut:
    inv = await _load_for_response(session, actor, token=token, invitation_id=invitation_id)
    firm = await _firm(session, inv.firm_id, lock=True)
    who = await identity_facade.get_identity(session, actor.identity_id)
    m = await session.scalar(select(FirmMember).where(FirmMember.firm_id == firm.id, FirmMember.identity_id == actor.identity_id))
    if m is None:
        m = FirmMember(firm_id=firm.id, identity_id=actor.identity_id, email=who.email, display_name=who.display_name, roles=inv.roles)
        session.add(m)
    else:
        m.status, m.roles = "ACTIVE", inv.roles
    inv.status = "ACCEPTED"
    inv.responded_at = clock.now()
    _evt(session, E.FIRM_MEMBER_JOINED, firm, identityId=actor.identity_id, roles=inv.roles, invitationId=inv.id)
    await session.flush()
    return await _out(session, firm, m.roles)


async def decline_invitation(session: AsyncSession, actor: Actor, invitation_id: uuid.UUID) -> None:
    inv = await _load_for_response(session, actor, token=None, invitation_id=invitation_id)
    inv.status = "DECLINED"
    inv.responded_at = clock.now()
