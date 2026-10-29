"""Firm domain commands: firm profile, members and their roles, invitations."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.admin import facade as admin_facade
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.escrow import facade as escrow_facade
from zoikorum.domains.firm import facade as firm_facade
from zoikorum.domains.firm.models import Firm, FirmInvitation, FirmMember, FirmOffering
from zoikorum.domains.firm.schemas import (FirmInvitationOut, FirmMemberOut, FirmOfferingIn, FirmOfferingOut, FirmOfferingPatch, FirmOut,
                                           FirmOverviewOut, FirmPatch, FirmProfessionalWork, MoneyTotal, FirmPageMember, FirmPageOut,
                                           OfferingMemberOut, RepresentativeOut)
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.marketplace import facade as marketplace_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.proposal import facade as proposal_facade
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.domains.verification import facade as verification_facade
from zoikorum.shared import clock
from zoikorum.shared import validation as rules
from zoikorum.shared.auth import Actor, AuthStrength, FirmRole
from zoikorum.shared.crypto import sha256_hex
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, PolicyBlocked, StepUpRequired, ValidationFailed, VersionConflict
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
    reps = await firm_facade.representatives(session, firm.id)
    return FirmOut(
        id=firm.id, legalName=firm.legal_name, tradingName=firm.trading_name, registrationNumber=firm.registration_number,
        hqCountry=firm.hq_country, sizeBand=firm.size_band, primaryCategory=firm.primary_category, website=firm.website,
        status=firm.status, myRoles=sorted(my_roles), memberCount=await _count(session, firm.id),
        hasAuthorizedRepresentative=bool(reps), hasVerifiedRepresentative=any(r.identity_verified for r in reps),
        representatives=[RepresentativeOut(identityId=r.identity_id, displayName=r.display_name, identityVerified=r.identity_verified)
                         for r in reps],
        version=firm.version, createdAt=firm.created_at,
    )


def _money(by_currency: dict[str, dict[str, int]]) -> list[MoneyTotal]:
    return [MoneyTotal(currency=c, heldMinor=v["held"], releasedMinor=v["released"]) for c, v in sorted(by_currency.items())]


async def overview(session: AsyncSession, actor: Actor, firm_id: uuid.UUID) -> FirmOverviewOut:
    """The firm's work across its member professionals, for Firm Admins. Counts and money totals only: buyers,
    contract terms and documents stay between each professional and their client."""
    await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    await _firm(session, firm_id)
    pros = await professional_facade.list_by_firm(session, firm_id)
    ids = [p.id for p in pros]
    open_requests = await proposal_facade.open_request_counts(session, ids)
    contracts = await contract_facade.contract_counts(session, ids)
    money = await escrow_facade.money_by_professional(session, ids)
    trust = await trust_facade.get_trust_many(session, ids)
    rows, totals = [], {}
    for p in pros:
        c = contracts.get(p.id, {"awaitingSignature": 0, "active": 0, "completed": 0})
        for currency, v in money.get(p.id, {}).items():
            t = totals.setdefault(currency, {"held": 0, "released": 0})
            t["held"] += v["held"]
            t["released"] += v["released"]
        rows.append(FirmProfessionalWork(
            professionalId=p.id, displayName=p.display_name, headline=p.headline, published=p.status == "PUBLISHED",
            tier=trust[p.id].tier if p.id in trust else "C", availability=p.availability, openRequests=open_requests.get(p.id, 0), awaitingSignature=c["awaitingSignature"], activeContracts=c["active"],
            completedContracts=c["completed"], money=_money(money.get(p.id, {}))))
    return FirmOverviewOut(
        professionals=rows, openRequests=sum(r.openRequests for r in rows), awaitingSignature=sum(r.awaitingSignature for r in rows),
        activeContracts=sum(r.activeContracts for r in rows), completedContracts=sum(r.completedContracts for r in rows),
        money=_money(totals))


def _valid_website(value: str | None) -> str | None:
    """Buyers only see a web address that passes today's rule; older saved values that do not are left out."""
    try:
        return rules.website_url(value) if value else None
    except ValueError:
        return None


async def public_firm(session: AsyncSession, firm_id: uuid.UUID) -> FirmPageOut:
    """The firm as buyers see it: who it is, what is verified, and its published professionals. Works without signing in."""
    firm = await _firm(session, firm_id)
    checks = await verification_facade.get_checks(session, "FIRM", firm.id)
    members = []
    pros = [p for p in await professional_facade.list_by_firm(session, firm.id) if p.status == "PUBLISHED"]
    trust = await trust_facade.get_trust_many(session, [p.id for p in pros])
    for p in pros:
        who = await identity_facade.get_identity(session, p.identity_id)
        restricted = set(await admin_facade.active_restrictions(session, "IDENTITY", p.identity_id)) & {"SUSPEND_ACCOUNT", "OFFBOARD"}
        if who is None or who.status != "ACTIVE" or restricted:
            continue
        members.append(FirmPageMember(professionalId=p.id, displayName=p.display_name, headline=p.headline,
                                        photoUrl=p.photo_url, tier=trust[p.id].tier if p.id in trust else "C"))
    summary = await firm_facade.get_firm(session, firm.id)
    return FirmPageOut(
        id=firm.id, name=firm.trading_name or firm.legal_name, legalName=firm.legal_name, hqCountry=firm.hq_country,
        sizeBand=firm.size_band, primaryCategory=firm.primary_category, website=_valid_website(firm.website),
        verified=firm.status == "VERIFIED", hasVerifiedRepresentative=bool(summary and summary.has_verified_representative),
        verifiedCredentials=sorted(c.label for c in checks if c.status == "VERIFIED" and c.verification_type != "FIRM_REGISTRATION"),
        professionals=members, offerings=await published_offerings(session, firm.id))


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
    await session.flush()
    await recheck_offerings(session, firm_id)


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
    who = await identity_facade.get_identity(session, actor.identity_id)
    if who is None or not who.email_confirmed:
        return []  # confirm your email first: an unconfirmed sign-up must not see invitations meant for that address
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


# ---- Firm-level offerings ---------------------------------------------------
# A firm publishes services delivered by its own members. Invariant: an offering in a regulated specialization is
# published only by a verified firm with a verified authorized representative, and at least one delivering member is a
# verified, licensed professional (identity verified, credentials validated, tier A (Green light), licensed somewhere, and the
# specialization on their profile). Checked at publish and on every change, and again when the firm's people change.

def licensed_member(pro, trust, specialization: str) -> bool:
    """A delivering member who counts for regulated work."""
    dims = trust.dimensions if trust else {}
    return bool(pro.status != "SUSPENDED" and trust and trust.tier == "A" and dims.get("identity") == "VERIFIED"
                and dims.get("credentials") == "VALIDATED" and pro.licensed_jurisdictions and specialization in pro.specializations)


async def _members_of(session: AsyncSession, firm_id: uuid.UUID) -> dict:
    """The firm's professionals whose people are still active members (a removed member stops counting at once)."""
    active = set((await session.scalars(select(FirmMember.identity_id).where(
        FirmMember.firm_id == firm_id, FirmMember.status == "ACTIVE"))).all())
    return {p.id: p for p in await professional_facade.list_by_firm(session, firm_id) if p.identity_id in active}


async def _offering_out(session: AsyncSession, o: FirmOffering, members: dict | None = None) -> FirmOfferingOut:
    members = members if members is not None else await _members_of(session, o.firm_id)
    ids = [uuid.UUID(i) for i in o.delivered_by]
    trust = await trust_facade.get_trust_many(session, [i for i in ids if i in members])
    spec = (await marketplace_facade.get_specializations(session, [o.specialization])).get(o.specialization)
    return FirmOfferingOut(
        id=o.id, firmId=o.firm_id, title=o.title, summary=o.summary, specialization=o.specialization,
        specializationName=spec.name if spec else None, regulated=o.regulated, engagementTypes=list(o.engagement_types),
        pricingModel=o.pricing_model, startingPriceMinor=o.starting_price_minor, currency=o.currency,
        deliveredBy=[OfferingMemberOut(professionalId=i, displayName=members[i].display_name,
                                       tier=trust[i].tier if i in trust else "C",
                                       licensed=licensed_member(members[i], trust.get(i), o.specialization))
                     for i in ids if i in members],
        status=o.status, publishedAt=o.published_at, unpublishedReason=o.unpublished_reason, version=o.version,
        createdAt=o.created_at)


async def _offering(session: AsyncSession, firm_id: uuid.UUID, offering_id: uuid.UUID, lock: bool = False) -> FirmOffering:
    o = await session.get(FirmOffering, offering_id, with_for_update=lock)
    if o is None or o.firm_id != firm_id:
        raise NotFound("Offering not found")
    return o


async def _check_offering(session: AsyncSession, firm_id: uuid.UUID, specialization: str, delivered_by: list[uuid.UUID]) -> bool:
    """A real specialization, delivered by professionals of this firm. Returns whether the specialization is regulated."""
    await marketplace_facade.validate_specializations(session, [specialization])
    members = await _members_of(session, firm_id)
    if any(i not in members for i in delivered_by):
        raise ValidationFailed("Only professionals who practise under this firm can deliver its offerings", code="NOT_A_FIRM_MEMBER")
    return bool((await marketplace_facade.get_specializations(session, [specialization]))[specialization].regulated)


REP_BLOCKER = "An authorized representative must verify their identity."


def publish_error_code(regulated: bool, blockers: list[str]) -> str:
    """Error code for a refused publish. When the missing verified representative is the only gap on a regulated offering
    it gets its own code; otherwise the licensed-member code (its message lists every reason)."""
    if not regulated:
        return "OFFERING_NOT_PUBLISHABLE"
    return "REGULATED_OFFERING_NEEDS_VERIFIED_REPRESENTATIVE" if blockers == [REP_BLOCKER] else "REGULATED_OFFERING_NEEDS_LICENSED_MEMBER"


async def offering_blockers(session: AsyncSession, firm: Firm, o: FirmOffering) -> list[str]:
    """Why this offering cannot be (or stay) published; empty when it can."""
    if firm.status == "SUSPENDED":
        return ["The firm is suspended."]
    members = await _members_of(session, firm.id)
    ids = [uuid.UUID(i) for i in o.delivered_by if uuid.UUID(i) in members]
    reasons = [] if ids else ["Name at least one member professional who delivers it."]
    if not o.regulated:
        return reasons
    summary = await firm_facade.get_firm(session, firm.id)
    if firm.status != "VERIFIED":
        reasons.append("The firm's registration must be verified before it offers regulated work.")
    if not (summary and summary.has_verified_representative):
        reasons.append(REP_BLOCKER)
    trust = await trust_facade.get_trust_many(session, ids)
    if not any(licensed_member(members[i], trust.get(i), o.specialization) for i in ids):
        reasons.append("At least one delivering member must be a verified, licensed professional (Green: fully verified, credentials "
                       "validated, licensed, with this specialization on their profile).")
    return reasons


async def list_offerings(session: AsyncSession, actor: Actor, firm_id: uuid.UUID) -> list[FirmOfferingOut]:
    await _require_member(session, actor, firm_id)
    rows = (await session.scalars(select(FirmOffering).where(FirmOffering.firm_id == firm_id).order_by(FirmOffering.created_at))).all()
    members = await _members_of(session, firm_id)
    return [await _offering_out(session, o, members) for o in rows]


async def create_offering(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, body: FirmOfferingIn) -> FirmOfferingOut:
    await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    await _firm(session, firm_id)
    regulated = await _check_offering(session, firm_id, body.specialization, body.deliveredBy)
    o = FirmOffering(firm_id=firm_id, title=body.title.strip(), summary=body.summary.strip(), specialization=body.specialization,
                     engagement_types=sorted(set(body.engagementTypes)), pricing_model=body.pricingModel,
                     starting_price_minor=body.startingPriceMinor, currency=body.currency,
                     delivered_by=[str(i) for i in dict.fromkeys(body.deliveredBy)], regulated=regulated, status="DRAFT",
                     created_by=actor.identity_id)
    session.add(o)
    await session.flush()
    return await _offering_out(session, o)


async def update_offering(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, offering_id: uuid.UUID,
                          body: FirmOfferingPatch) -> FirmOfferingOut:
    await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    firm = await _firm(session, firm_id)
    o = await _offering(session, firm_id, offering_id, lock=True)
    specialization = body.specialization or o.specialization
    delivered = body.deliveredBy if body.deliveredBy is not None else [uuid.UUID(i) for i in o.delivered_by]
    o.regulated = await _check_offering(session, firm_id, specialization, delivered)
    for field, col in (("title", "title"), ("summary", "summary"), ("pricingModel", "pricing_model"),
                       ("startingPriceMinor", "starting_price_minor"), ("currency", "currency")):
        value = getattr(body, field)
        if value is not None:
            setattr(o, col, value.strip() if field in ("title", "summary") else value)
    if body.engagementTypes is not None:
        o.engagement_types = sorted(set(body.engagementTypes))
    o.specialization, o.delivered_by = specialization, [str(i) for i in dict.fromkeys(delivered)]
    if o.status == "PUBLISHED" and (blockers := await offering_blockers(session, firm, o)):
        raise PolicyBlocked("This change would break the published offering: " + " ".join(blockers), code="OFFERING_NOT_PUBLISHABLE",
                            extra={"reasons": blockers})
    await session.flush()
    return await _offering_out(session, o)


async def publish_offering(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, offering_id: uuid.UUID) -> FirmOfferingOut:
    await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    firm = await _firm(session, firm_id, lock=True)
    o = await _offering(session, firm_id, offering_id, lock=True)
    if o.status == "PUBLISHED":
        return await _offering_out(session, o)
    o.regulated = await _check_offering(session, firm_id, o.specialization, [uuid.UUID(i) for i in o.delivered_by])
    blockers = await offering_blockers(session, firm, o)
    if blockers:
        raise PolicyBlocked(" ".join(blockers), extra={"reasons": blockers},
                            code=publish_error_code(o.regulated, blockers))
    o.status, o.published_at, o.published_by, o.unpublished_reason = "PUBLISHED", clock.now(), actor.identity_id, None
    _evt(session, E.FIRM_OFFERING_PUBLISHED, firm, offeringId=o.id, title=o.title, specialization=o.specialization,
         regulated=o.regulated, deliveredBy=list(o.delivered_by), publishedBy=actor.identity_id)
    await session.flush()
    return await _offering_out(session, o)


async def _take_down(session: AsyncSession, firm: Firm, o: FirmOffering, reason: str | None, by: uuid.UUID | None) -> None:
    o.status, o.unpublished_reason = "UNPUBLISHED", (reason or "").strip()[:300] or None
    _evt(session, E.FIRM_OFFERING_UNPUBLISHED, firm, offeringId=o.id, reason=o.unpublished_reason, by=by)


async def unpublish_offering(session: AsyncSession, actor: Actor, firm_id: uuid.UUID, offering_id: uuid.UUID,
                             reason: str | None) -> FirmOfferingOut:
    await _require_member(session, actor, firm_id, FirmRole.FIRM_ADMIN)
    firm = await _firm(session, firm_id)
    o = await _offering(session, firm_id, offering_id, lock=True)
    if o.status == "PUBLISHED":
        await _take_down(session, firm, o, reason, actor.identity_id)
        await session.flush()
    return await _offering_out(session, o)


async def recheck_offerings(session: AsyncSession, firm_id: uuid.UUID) -> None:
    """Keep the invariant over time: a published offering whose firm or people no longer qualify is taken down."""
    firm = await session.get(Firm, firm_id)
    if firm is None:
        return
    for o in (await session.scalars(select(FirmOffering).where(
            FirmOffering.firm_id == firm_id, FirmOffering.status == "PUBLISHED").with_for_update())).all():
        if blockers := await offering_blockers(session, firm, o):
            await _take_down(session, firm, o, "Unpublished automatically: " + " ".join(blockers), None)


async def published_offerings(session: AsyncSession, firm_id: uuid.UUID) -> list[FirmOfferingOut]:
    rows = (await session.scalars(select(FirmOffering).where(FirmOffering.firm_id == firm_id, FirmOffering.status == "PUBLISHED")
                                  .order_by(FirmOffering.published_at))).all()
    members = await _members_of(session, firm_id)
    return [await _offering_out(session, o, members) for o in rows]
