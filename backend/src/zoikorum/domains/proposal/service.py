"""Proposal domain: buyer requests -> professional proposals -> buyer decision (RFP wireframe, BUILD_SPEC s.proposal).

Zoikorum is not a job board (Homepage wireframe): a buyer sends a structured request to professionals they chose
(one, or up to three to compare), and each answers with a structured proposal or declines with a reason.

Until the policy domain exists, the platform baseline applies (BUILD_SPEC s.policy): restricted professionals cannot
be engaged, and Tier C professionals cannot submit or have a proposal accepted. An accepting member's own spend limit
is respected; organisation approval workflows arrive with the policy domain.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.proposal.models import Proposal, ProposalRequest
from zoikorum.domains.proposal.schemas import (
    Budget, CancelIn, DeclineIn, Delta, ProfessionalBrief, ProposalAttachmentsIn, ProposalBrief, ProposalIn, ProposalOut, RejectIn,
    RequestIn, RequestOut, RequestSummaryOut, RevisionIn,
)
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, OrgRole
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, PolicyBlocked, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.http import page_of, paginate
from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.relay import cancel_timer, schedule_timer
from zoikorum.shared.state_machine import StateMachine
from zoikorum.shared.uploads import file_out, find_file, read_file, store_uploads

REQUEST_STATES = StateMachine("ProposalRequest", {
    "DRAFT": {"OPEN", "CANCELLED"},
    "OPEN": {"PROPOSAL_RECEIVED", "DECLINED", "CANCELLED", "CLOSED"},
    "PROPOSAL_RECEIVED": {"CLOSED", "CANCELLED"},
    "CLOSED": set(),
    "DECLINED": set(),
    "CANCELLED": set(),
})
PROPOSAL_STATES = StateMachine("Proposal", {
    "DRAFT": {"SUBMITTED", "WITHDRAWN", "REJECTED"},
    "SUBMITTED": {"UNDER_REVIEW", "REVISION_REQUESTED", "PENDING_APPROVAL", "ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED"},
    "UNDER_REVIEW": {"REVISION_REQUESTED", "PENDING_APPROVAL", "ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED"},
    "REVISION_REQUESTED": {"SUBMITTED", "REJECTED", "WITHDRAWN", "EXPIRED"},
    "PENDING_APPROVAL": {"ACCEPTED", "REJECTED", "EXPIRED"},
    "ACCEPTED": set(),
    "REJECTED": set(),
    "WITHDRAWN": set(),
    "EXPIRED": set(),
})
OPEN_REQUEST = ("DRAFT", "OPEN", "PROPOSAL_RECEIVED")
LIVE_PROPOSAL = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "PENDING_APPROVAL")
DECIDERS = (OrgRole.REQUESTER, OrgRole.APPROVER)
POLICY_LABEL = "platform-default@1"
TIMER_EXPIRY = "proposal.expiry"
DURATION_DAYS = {"ONE_TWO_WEEKS": (7, 14), "THREE_SIX_WEEKS": (15, 42), "TWO_THREE_MONTHS": (43, 92),
                 "THREE_SIX_MONTHS": (93, 183), "ONGOING": (1, 100_000)}
DURATION_LABEL = {"ONE_TWO_WEEKS": "1–2 weeks", "THREE_SIX_WEEKS": "3–6 weeks", "TWO_THREE_MONTHS": "2–3 months",
                  "THREE_SIX_MONTHS": "3–6 months", "ONGOING": "Ongoing"}


# ---- Helpers -----------------------------------------------------------------

def _today() -> date:
    return clock.now().date()


def _money(minor: int, currency: str) -> str:
    return f"{currency} {minor / 100:,.0f}" if minor % 100 == 0 else f"{currency} {minor / 100:,.2f}"


def _req_evt(session: AsyncSession, event_type: str, r: ProposalRequest, **extra) -> None:
    record_event(session, event_type, aggregate_type="ProposalRequest", aggregate_id=r.id, tenant_id=r.organization_id,
                 payload={"requestId": r.id, "groupId": r.group_id, "organizationId": r.organization_id,
                          "buyerIdentityId": r.buyer_identity_id, "professionalId": r.professional_id, **extra})


def _prop_evt(session: AsyncSession, event_type: str, p: Proposal, **extra) -> None:
    record_event(session, event_type, aggregate_type="Proposal", aggregate_id=p.id, tenant_id=p.organization_id,
                 payload={"proposalId": p.id, "requestId": p.request_id, "organizationId": p.organization_id,
                          "professionalId": p.professional_id, **extra}, policy_version=POLICY_LABEL)


async def _request(session: AsyncSession, request_id: uuid.UUID, lock: bool = False) -> ProposalRequest:
    r = await session.get(ProposalRequest, request_id, with_for_update=lock)
    if r is None:
        raise NotFound("Request not found")
    return r


async def _proposal(session: AsyncSession, proposal_id: uuid.UUID, lock: bool = False) -> Proposal:
    p = await session.get(Proposal, proposal_id, with_for_update=lock)
    if p is None:
        raise NotFound("Proposal not found")
    return p


async def _my_professional_id(session: AsyncSession, actor: Actor) -> uuid.UUID | None:
    pro = await professional_facade.get_professional_by_identity(session, actor.identity_id)
    return pro.id if pro else None


async def _buyer_roles(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> frozenset[str]:
    """Live membership from the buyer domain, so a token issued before the organisation existed still works."""
    return await buyer_facade.get_member_roles(session, org_id, actor.identity_id)


async def _viewer(session: AsyncSession, actor: Actor, r: ProposalRequest) -> str:
    if await _buyer_roles(session, actor, r.organization_id):
        return "BUYER"
    if r.status != "DRAFT" and r.professional_id == await _my_professional_id(session, actor):
        return "PROFESSIONAL"
    raise NotFound("Request not found")


async def _require_buyer(session: AsyncSession, actor: Actor, org_id: uuid.UUID, *roles: str) -> frozenset[str]:
    have = await _buyer_roles(session, actor, org_id)
    if not have:
        raise NotFound("Request not found")
    if roles and not have.intersection(roles):
        names = " or ".join(r.replace("_", " ").title() for r in roles)
        raise Forbidden(f"This needs the {names} role in your organisation", code="ROLE_REQUIRED")
    return have


async def _require_owner(session: AsyncSession, actor: Actor, professional_id: uuid.UUID) -> None:
    if await _my_professional_id(session, actor) != professional_id:
        raise NotFound("Not found")


def _restricted(trust: trust_facade.TrustSnapshot) -> bool:
    return trust.dimensions.get("restrictions") == "FLAGGED"


def _check_requestable(pro: professional_facade.ProfessionalSummary, trust: trust_facade.TrustSnapshot) -> None:
    if pro.status != "PUBLISHED":
        raise PolicyBlocked(f"{pro.display_name} is not accepting requests right now", code="PROFESSIONAL_NOT_AVAILABLE")
    if _restricted(trust):
        raise PolicyBlocked(f"{pro.display_name} cannot be engaged while a restriction is under review",
                            code="POLICY_BLOCKED_RESTRICTIONS")


def _check_tier(trust: trust_facade.TrustSnapshot, who: str) -> None:
    if _restricted(trust):
        raise PolicyBlocked(f"{who} cannot be engaged while a restriction is under review", code="POLICY_BLOCKED_RESTRICTIONS")
    if trust.tier == "C":
        raise PolicyBlocked(f"{who} must reach Trust Tier B (verified identity) before a proposal can be sent or accepted",
                            code="POLICY_BLOCKED_MINIMUM_TRUST_TIER")


def _conflict(served: set[str], org) -> bool:
    """Professional not eligible for the buyer's region (RFP s.16): flagged early, blocked at agreement.
    A professional with no served countries listed is treated as unrestricted."""
    return bool(served) and org is not None and org.country.upper() not in {s.upper() for s in served}


def _budget(r: ProposalRequest) -> Budget | None:
    if r.budget_max_minor is None or r.budget_currency is None:
        return None
    return Budget(minMinor=r.budget_min_minor, maxMinor=r.budget_max_minor, currency=r.budget_currency)


def _total(p: Proposal) -> MoneyDTO:
    return MoneyDTO(amountMinor=p.total_minor, currency=p.currency)


def _expired(p: Proposal) -> bool:
    return p.status == "EXPIRED" or (p.status in LIVE_PROPOSAL and p.valid_until is not None and p.valid_until < _today())


async def _briefs(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, ProfessionalBrief]:
    pros = await professional_facade.get_professionals(session, ids)
    trusts = await trust_facade.get_trust_many(session, ids)
    out = {}
    for pid in ids:
        p = pros.get(pid)
        out[pid] = ProfessionalBrief(id=pid, displayName=p.display_name if p else "Professional", headline=p.headline if p else None,
                                     photoUrl=p.photo_url if p else None, tier=trusts[pid].tier, country=p.country if p else None)
    return out


async def _requests_out(session: AsyncSession, actor: Actor, rows: list[ProposalRequest], viewer: str | None = None) -> list[RequestOut]:
    if not rows:
        return []
    briefs = await _briefs(session, list({r.professional_id for r in rows}))
    buyers = await identity_facade.get_identities(session, list({r.buyer_identity_id for r in rows}))
    orgs = {oid: await buyer_facade.get_organization(session, oid) for oid in {r.organization_id for r in rows}}
    served = {pid: set(p.jurisdictions_served) for pid, p in
              (await professional_facade.get_professionals(session, list({r.professional_id for r in rows}))).items()}
    props = {p.request_id: p for p in (await session.scalars(
        select(Proposal).where(Proposal.request_id.in_([r.id for r in rows])))).all()}
    sizes = dict((await session.execute(
        select(ProposalRequest.group_id, func.count()).where(ProposalRequest.group_id.in_({r.group_id for r in rows}))
        .group_by(ProposalRequest.group_id))).all())
    my_pro = await _my_professional_id(session, actor)
    out = []
    for r in rows:
        role = viewer or ("PROFESSIONAL" if r.professional_id == my_pro and r.buyer_identity_id != actor.identity_id else "BUYER")
        hidden = role == "PROFESSIONAL" and r.nda_required and r.nda_accepted_at is None
        p = props.get(r.id)
        if p and role == "BUYER" and p.status == "DRAFT":
            p = None  # buyers never see a professional's unsent draft
        out.append(RequestOut(
            id=r.id, groupId=r.group_id, organizationId=r.organization_id,
            organizationName=orgs[r.organization_id].name if orgs.get(r.organization_id) else None,
            buyerIdentityId=r.buyer_identity_id, buyerName=buyers[r.buyer_identity_id].display_name if r.buyer_identity_id in buyers else None,
            professional=briefs[r.professional_id], offeringId=r.offering_id, service=r.service, specialization=r.specialization,
            engagementType=r.engagement_type, businessContext=r.business_context, detailsHidden=hidden,
            objective=None if hidden else r.objective, details=None if hidden else r.details,
            location=None if hidden else r.location, attachments=[] if hidden else [file_out(a) for a in r.attachments],
            desiredStartDate=r.desired_start_date, estimatedDuration=r.estimated_duration, budget=_budget(r),
            deliveryMode=r.delivery_mode, ndaRequired=r.nda_required, ndaAccepted=r.nda_accepted_at is not None,
            status=r.status, sentAt=r.sent_at, closedAt=r.closed_at, reasonCode=r.reason_code, reasonNote=r.reason_note,
            proposal=ProposalBrief(id=p.id, status="EXPIRED" if _expired(p) else p.status, total=_total(p),
                                   submittedAt=p.submitted_at, validUntil=p.valid_until) if p else None,
            groupSize=sizes.get(r.group_id, 1), deliverables=[] if hidden else r.deliverables, dependencies=[] if hidden else r.dependencies,
            pricingPreferences=r.pricing_preferences, paymentCadence=r.payment_cadence,
            jurisdictionConflict=_conflict(served.get(r.professional_id, set()), orgs.get(r.organization_id)),
            viewerRole=role, createdAt=r.created_at, version=r.version,
        ))
    return out


def _deltas(r: ProposalRequest, p: Proposal) -> list[Delta]:
    out: list[Delta] = []
    b = _budget(r)
    if b and p.milestones:
        requested = (f"{_money(b.minMinor, b.currency)} – {_money(b.maxMinor, b.currency)}" if b.minMinor
                     else f"Up to {_money(b.maxMinor, b.currency)}")
        if b.currency != p.currency:
            status = "CHANGED"
        elif p.total_minor > b.maxMinor:
            status = "ABOVE"
        elif b.minMinor and p.total_minor < b.minMinor:
            status = "BELOW"
        else:
            status = "WITHIN"
        out.append(Delta(field="price", label="Price vs budget", requested=requested, proposed=_money(p.total_minor, p.currency), status=status))
    if p.start_date:
        s = "MATCH" if p.start_date == r.desired_start_date else "EARLIER" if p.start_date < r.desired_start_date else "LATER"
        out.append(Delta(field="startDate", label="Start date", requested=r.desired_start_date.isoformat(), proposed=p.start_date.isoformat(), status=s))
    if p.start_date and p.end_date:
        days = (p.end_date - p.start_date).days + 1
        lo, hi = DURATION_DAYS[r.estimated_duration]
        s = "WITHIN" if lo <= days <= hi else "BELOW" if days < lo else "ABOVE"
        out.append(Delta(field="duration", label="Duration", requested=DURATION_LABEL[r.estimated_duration], proposed=f"{days} days", status=s))
    out.append(Delta(field="scope", label="Scope", requested="As requested",
                     proposed="Adjusted" + (f": {p.scope_notes}" if p.scope_notes else "") if p.scope_alignment == "ADJUSTED" else "Confirmed",
                     status="CHANGED" if p.scope_alignment == "ADJUSTED" else "MATCH"))
    return out


async def _proposals_out(session: AsyncSession, rows: list[Proposal]) -> list[ProposalOut]:
    if not rows:
        return []
    briefs = await _briefs(session, list({p.professional_id for p in rows}))
    reqs = {r.id: r for r in (await session.scalars(select(ProposalRequest).where(ProposalRequest.id.in_([p.request_id for p in rows])))).all()}
    return [ProposalOut(
        id=p.id, requestId=p.request_id, groupId=reqs[p.request_id].group_id, organizationId=p.organization_id,
        professional=briefs[p.professional_id], status="EXPIRED" if _expired(p) else p.status, summary=p.summary,
        scopeAlignment=p.scope_alignment, scopeNotes=p.scope_notes, deliverables=p.deliverables, milestones=p.milestones,
        pricingModel=p.pricing_model, currency=p.currency, total=_total(p), startDate=p.start_date, endDate=p.end_date, assumptions=p.assumptions,
        exclusions=p.exclusions, validUntil=p.valid_until, expired=_expired(p), revisionRequests=p.revision_requests,
        revisionCount=p.revision_count, submittedAt=p.submitted_at, decidedAt=p.decided_at, reasonCode=p.reason_code,
        reasonNote=p.reason_note, termsHash=p.terms_hash, deltas=_deltas(reqs[p.request_id], p),
        attachments=[file_out(a) for a in p.attachments or []],
        createdAt=p.created_at, updatedAt=p.updated_at, version=p.version,
    ) for p in rows]


def _close_request(r: ProposalRequest, status: str, reason: str) -> None:
    REQUEST_STATES.assert_can(r.status, status)
    r.status = status
    r.closed_at = clock.now()
    r.reason_code = reason


async def _end_proposal(session: AsyncSession, p: Proposal, status: str, reason: str | None, actor: Actor | None,
                        note: str | None = None) -> None:
    PROPOSAL_STATES.assert_can(p.status, status)
    p.status = status
    p.decided_at = clock.now()
    p.decided_by = actor.identity_id if actor else None
    p.reason_code = reason
    p.reason_note = note
    await cancel_timer(session, TIMER_EXPIRY, str(p.id))
    event = {"REJECTED": E.PROPOSAL_REJECTED, "WITHDRAWN": E.PROPOSAL_WITHDRAWN, "EXPIRED": E.PROPOSAL_EXPIRED}.get(status)
    if event:
        _prop_evt(session, event, p, reasonCode=reason)


# ---- Buyer: requests -------------------------------------------------------------

async def create_requests(session: AsyncSession, actor: Actor, body: RequestIn) -> list[RequestOut]:
    await _require_buyer(session, actor, body.organizationId, OrgRole.REQUESTER)
    org = await buyer_facade.get_organization(session, body.organizationId)
    if org is None or org.status != "ACTIVE":
        raise Forbidden("This organisation cannot send requests", code="ORGANIZATION_INACTIVE")
    if not body.draft and not body.acknowledged:
        raise ValidationFailed("Confirm that you understand Zoikorum facilitates the engagement but does not provide the "
                               "professional services", code="ACKNOWLEDGEMENT_REQUIRED")
    if body.desiredStartDate < _today():
        raise ValidationFailed("The desired start date cannot be in the past", code="START_DATE_IN_PAST")

    pros = await professional_facade.get_professionals(session, body.professionalIds)
    trusts = await trust_facade.get_trust_many(session, body.professionalIds)
    mine = await _my_professional_id(session, actor)
    for pid in body.professionalIds:
        if pid not in pros:
            raise NotFound("Professional not found")
        if pid == mine:
            raise ValidationFailed("You cannot request a proposal from yourself", code="SELF_REQUEST")
        _check_requestable(pros[pid], trusts[pid])
    if body.offeringId:
        off = await professional_facade.get_offering(session, body.offeringId)
        if off is None or off.professional_id != body.professionalIds[0] or off.status != "ACTIVE":
            raise ValidationFailed("That service is not available from this professional", code="INVALID_OFFERING")

    now, group = clock.now(), uuid.uuid4()
    attachments = store_uploads(f"proposals/{group}", body.attachments)  # one copy shared by the group
    rows = []
    for pid in body.professionalIds:
        r = ProposalRequest(
            organization_id=body.organizationId, buyer_identity_id=actor.identity_id, professional_id=pid,
            offering_id=body.offeringId, group_id=group, service=body.service.strip(), specialization=body.specialization,
            engagement_type=body.engagementType, business_context=body.businessContext or org.business_context,
            objective=body.objective.strip(), details=body.details.strip(), desired_start_date=body.desiredStartDate,
            estimated_duration=body.estimatedDuration,
            budget_min_minor=body.budget.minMinor if body.budget else None,
            budget_max_minor=body.budget.maxMinor if body.budget else None,
            budget_currency=body.budget.currency if body.budget else None,
            delivery_mode=body.deliveryMode, location=(body.location or "").strip() or None, nda_required=body.ndaRequired,
            attachments=attachments,
            deliverables=body.deliverables, dependencies=list(body.dependencies), pricing_preferences=list(body.pricingPreferences),
            payment_cadence=body.paymentCadence,
            status="DRAFT" if body.draft else "OPEN", sent_at=None if body.draft else now,
        )
        session.add(r)
        rows.append(r)
    await session.flush()
    if not body.draft:
        for r in rows:
            _req_evt(session, E.PROPOSAL_REQUESTED, r, offeringId=r.offering_id, engagementType=r.engagement_type,
                     ndaRequired=r.nda_required)
    return await _requests_out(session, actor, rows, viewer="BUYER")


async def send_drafts(session: AsyncSession, actor: Actor, request_id: uuid.UUID, acknowledged: bool) -> list[RequestOut]:
    """Send every draft in the request's group (one requirement, up to three professionals)."""
    first = await _request(session, request_id)
    await _require_buyer(session, actor, first.organization_id, OrgRole.REQUESTER)
    if not acknowledged:
        raise ValidationFailed("Confirm the acknowledgement before sending", code="ACKNOWLEDGEMENT_REQUIRED")
    rows = (await session.scalars(select(ProposalRequest).where(
        ProposalRequest.group_id == first.group_id, ProposalRequest.status == "DRAFT").with_for_update())).all()
    if not rows:
        raise Conflict("This request has already been sent", code="NOT_A_DRAFT")
    if first.desired_start_date < _today():
        raise ValidationFailed("The desired start date is now in the past; cancel this draft and create a new request",
                               code="START_DATE_IN_PAST")
    pros = await professional_facade.get_professionals(session, [r.professional_id for r in rows])
    trusts = await trust_facade.get_trust_many(session, [r.professional_id for r in rows])
    for r in rows:
        if r.professional_id not in pros:
            raise NotFound("Professional not found")
        _check_requestable(pros[r.professional_id], trusts[r.professional_id])
    now = clock.now()
    for r in rows:
        REQUEST_STATES.assert_can(r.status, "OPEN")
        r.status, r.sent_at = "OPEN", now
        _req_evt(session, E.PROPOSAL_REQUESTED, r, offeringId=r.offering_id, engagementType=r.engagement_type,
                 ndaRequired=r.nda_required)
    await session.flush()
    return await _requests_out(session, actor, list(rows), viewer="BUYER")


async def cancel_request(session: AsyncSession, actor: Actor, request_id: uuid.UUID, body: CancelIn) -> RequestOut:
    r = await _request(session, request_id, lock=True)
    await _require_buyer(session, actor, r.organization_id, OrgRole.REQUESTER, OrgRole.ORG_ADMIN)
    if r.status not in OPEN_REQUEST:
        raise Conflict("This request is already closed", code="REQUEST_CLOSED")
    p = await session.scalar(select(Proposal).where(Proposal.request_id == r.id).with_for_update())
    if p and p.status in ("DRAFT", *LIVE_PROPOSAL):
        await _end_proposal(session, p, "REJECTED", "REQUEST_CANCELLED", actor, body.note)
    was_sent = r.status != "DRAFT"
    _close_request(r, "CANCELLED", body.reasonCode)
    r.reason_note = body.note
    if was_sent:
        _req_evt(session, E.PROPOSAL_REQUEST_CANCELLED, r, reasonCode=body.reasonCode)
    await session.flush()
    return (await _requests_out(session, actor, [r], viewer="BUYER"))[0]


# ---- Shared reads ----------------------------------------------------------------------

async def get_request(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> RequestOut:
    r = await _request(session, request_id)
    return (await _requests_out(session, actor, [r], viewer=await _viewer(session, actor, r)))[0]


async def attachment_file(session: AsyncSession, actor: Actor, request_id: uuid.UUID, sha256: str) -> tuple[bytes, str | None, str]:
    """A request attachment, for the buyer's organisation and the invited professional (after the NDA if one is required)."""
    r = await _request(session, request_id)
    role = await _viewer(session, actor, r)
    if role == "PROFESSIONAL" and r.nda_required and r.nda_accepted_at is None:
        raise Forbidden("Accept the NDA to open the attachments", code="NDA_NOT_ACCEPTED")
    rec = find_file(r.attachments, sha256)
    data = read_file(rec)
    record_audit(session, "proposal.request.attachment.viewed", object_type="ProposalRequest", object_id=r.id,
                 tenant_id=r.organization_id, evidence_hash=rec["sha256"], details={"viewer": role})
    return data, rec.get("contentType"), rec["name"]


def _status_filter(stmt, model, status: str | None):
    if status:
        stmt = stmt.where(model.status.in_([s.strip().upper() for s in status.split(",") if s.strip()]))
    return stmt


async def _scope(session: AsyncSession, actor: Actor, role: str):
    """WHERE clause for the caller's requests, or None when they have none."""
    if role == "buyer":
        return or_(ProposalRequest.organization_id.in_(actor.org_ids), ProposalRequest.buyer_identity_id == actor.identity_id)
    pid = await _my_professional_id(session, actor)
    if pid is None:
        return None
    return (ProposalRequest.professional_id == pid) & (ProposalRequest.status != "DRAFT")


async def list_requests(session: AsyncSession, actor: Actor, role: str, status: str | None, cursor: str | None,
                        limit: int | None) -> dict:
    where = await _scope(session, actor, role)
    if where is None:
        return {"items": [], "nextCursor": None}
    stmt, lim = paginate(_status_filter(select(ProposalRequest).where(where), ProposalRequest, status), ProposalRequest, cursor, limit)
    rows = list((await session.scalars(stmt)).all())
    items = await _requests_out(session, actor, rows[:lim], viewer="BUYER" if role == "buyer" else "PROFESSIONAL")
    by_id = {i.id: i for i in items}
    return page_of(rows, lim, lambda r: by_id[r.id])


async def summary(session: AsyncSession, actor: Actor, role: str) -> RequestSummaryOut:
    where = await _scope(session, actor, role)
    if where is None:
        return RequestSummaryOut(role=role, requests={}, proposals={})
    reqs = dict((await session.execute(select(ProposalRequest.status, func.count()).where(where).group_by(ProposalRequest.status))).all())
    prop_q = select(Proposal.status, func.count()).join(ProposalRequest, ProposalRequest.id == Proposal.request_id).where(where)
    if role == "buyer":
        prop_q = prop_q.where(Proposal.status != "DRAFT")
    props = dict((await session.execute(prop_q.group_by(Proposal.status))).all())
    return RequestSummaryOut(role=role, requests=reqs, proposals=props)


# ---- Professional: respond ----------------------------------------------------------------

async def accept_nda(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> RequestOut:
    r = await _request(session, request_id, lock=True)
    if await _viewer(session, actor, r) != "PROFESSIONAL":
        raise NotFound("Request not found")
    if not r.nda_required:
        raise Conflict("This request does not require an NDA", code="NDA_NOT_REQUIRED")
    if r.nda_accepted_at is None:
        r.nda_accepted_at = clock.now()
        record_audit(session, "proposal.request.nda_accepted", object_type="ProposalRequest", object_id=r.id,
                     tenant_id=r.organization_id, details={"professionalId": str(r.professional_id)})
    await session.flush()
    return (await _requests_out(session, actor, [r], viewer="PROFESSIONAL"))[0]


async def decline_request(session: AsyncSession, actor: Actor, request_id: uuid.UUID, body: DeclineIn) -> RequestOut:
    r = await _request(session, request_id, lock=True)
    if await _viewer(session, actor, r) != "PROFESSIONAL":
        raise NotFound("Request not found")
    if r.status != "OPEN":
        raise Conflict("Only a request that is waiting for your proposal can be declined", code="REQUEST_NOT_OPEN")
    p = await session.scalar(select(Proposal).where(Proposal.request_id == r.id).with_for_update())
    if p and p.status == "DRAFT":
        await _end_proposal(session, p, "WITHDRAWN", "REQUEST_DECLINED", actor)
    _close_request(r, "DECLINED", body.reasonCode)
    r.reason_note = body.note
    _req_evt(session, E.PROPOSAL_REQUEST_DECLINED, r, reasonCode=body.reasonCode)
    await session.flush()
    return (await _requests_out(session, actor, [r], viewer="PROFESSIONAL"))[0]


def _apply(p: Proposal, body: ProposalIn) -> None:
    p.summary = body.summary.strip()
    p.scope_alignment = body.scopeAlignment
    p.scope_notes = (body.scopeNotes or "").strip() or None
    p.deliverables = [d.model_dump() for d in body.deliverables]
    p.milestones = [m.model_dump(mode="json") for m in body.milestones]
    p.pricing_model = body.pricingModel
    p.currency = body.currency
    p.total_minor = sum(m.amountMinor for m in body.milestones)
    p.start_date, p.end_date, p.valid_until = body.startDate, body.endDate, body.validUntil
    p.assumptions = [a.strip() for a in body.assumptions]
    p.exclusions = [x.strip() for x in body.exclusions]


async def create_proposal(session: AsyncSession, actor: Actor, request_id: uuid.UUID, body: ProposalIn) -> ProposalOut:
    r = await _request(session, request_id, lock=True)
    if await _viewer(session, actor, r) != "PROFESSIONAL":
        raise NotFound("Request not found")
    if r.status != "OPEN":
        raise Conflict("This request is no longer open", code="REQUEST_NOT_OPEN")
    if r.nda_required and r.nda_accepted_at is None:
        raise Forbidden("Accept the NDA to see the request details before you write a proposal", code="NDA_NOT_ACCEPTED")
    if await session.scalar(select(Proposal.id).where(Proposal.request_id == r.id)):
        raise Conflict("You already have a proposal for this request; edit it instead", code="PROPOSAL_EXISTS")
    p = Proposal(request_id=r.id, organization_id=r.organization_id, buyer_identity_id=r.buyer_identity_id,
                 professional_id=r.professional_id, status="DRAFT", currency=body.currency)
    _apply(p, body)
    session.add(p)
    await session.flush()
    return (await _proposals_out(session, [p]))[0]


async def update_proposal(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID, body: ProposalIn) -> ProposalOut:
    p = await _proposal(session, proposal_id, lock=True)
    await _require_owner(session, actor, p.professional_id)
    if p.status not in ("DRAFT", "REVISION_REQUESTED"):
        raise Conflict("Only a draft, or a proposal the buyer asked you to revise, can be edited", code="PROPOSAL_LOCKED")
    _apply(p, body)
    await session.flush()
    return (await _proposals_out(session, [p]))[0]


def _completeness(p: Proposal) -> list[str]:
    missing = []
    if not p.summary:
        missing.append("a short summary for the buyer")
    if not p.deliverables:
        missing.append("at least one deliverable")
    if not p.milestones or p.total_minor <= 0:
        missing.append("milestones with a price")
    used = {k for m in p.milestones for k in m["deliverableKeys"]}
    if p.deliverables and any(d["key"] not in used for d in p.deliverables):
        missing.append("a milestone for every deliverable")
    if not (p.start_date and p.end_date):
        missing.append("start and completion dates")
    if not p.valid_until or p.valid_until < _today():
        missing.append("a validity date that is today or later")
    return missing


async def submit_proposal(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID) -> ProposalOut:
    p = await _proposal(session, proposal_id, lock=True)
    await _require_owner(session, actor, p.professional_id)
    r = await _request(session, p.request_id, lock=True)
    if r.status not in ("OPEN", "PROPOSAL_RECEIVED"):
        raise Conflict("This request is no longer open", code="REQUEST_NOT_OPEN")
    missing = _completeness(p)
    if missing:
        raise ValidationFailed("Before sending, add " + "; ".join(missing), code="PROPOSAL_INCOMPLETE", extra={"missing": missing})
    _check_tier(await trust_facade.get_trust(session, p.professional_id), "You")
    revised = p.status == "REVISION_REQUESTED"
    PROPOSAL_STATES.assert_can(p.status, "SUBMITTED")
    p.status, p.submitted_at = "SUBMITTED", clock.now()
    if r.status == "OPEN":
        REQUEST_STATES.assert_can(r.status, "PROPOSAL_RECEIVED")
        r.status = "PROPOSAL_RECEIVED"
    fire_at = datetime.combine(p.valid_until + timedelta(days=1), time.min, tzinfo=timezone.utc)
    await schedule_timer(session, TIMER_EXPIRY, str(p.id), fire_at, {"proposalId": str(p.id)})
    _prop_evt(session, E.PROPOSAL_REVISED if revised else E.PROPOSAL_SUBMITTED, p, totalMinor=p.total_minor,
              currency=p.currency, validUntil=p.valid_until)
    await session.flush()
    return (await _proposals_out(session, [p]))[0]


async def withdraw_proposal(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID) -> ProposalOut:
    p = await _proposal(session, proposal_id, lock=True)
    await _require_owner(session, actor, p.professional_id)
    if p.status not in LIVE_PROPOSAL:
        raise Conflict("Only a sent proposal can be withdrawn; decline the request instead", code="PROPOSAL_NOT_SENT")
    r = await _request(session, p.request_id, lock=True)
    await _end_proposal(session, p, "WITHDRAWN", "WITHDRAWN_BY_PROFESSIONAL", actor)
    _close_request(r, "CLOSED", "PROPOSAL_WITHDRAWN")
    await session.flush()
    return (await _proposals_out(session, [p]))[0]


# ---- Buyer: review and decide -------------------------------------------------------------------

async def get_proposal(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID) -> ProposalOut:
    p = await _proposal(session, proposal_id)
    if p.professional_id != await _my_professional_id(session, actor):
        if p.status == "DRAFT" or not await _buyer_roles(session, actor, p.organization_id):
            raise NotFound("Proposal not found")
    return (await _proposals_out(session, [p]))[0]


async def request_proposals(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> list[ProposalOut]:
    """Buyer: every sent proposal for this requirement (all professionals in the group), for side-by-side comparison.
    Professional: their own proposal for this request."""
    r = await _request(session, request_id)
    if await _viewer(session, actor, r) == "PROFESSIONAL":
        rows = (await session.scalars(select(Proposal).where(Proposal.request_id == r.id))).all()
    else:
        rows = (await session.scalars(
            select(Proposal).join(ProposalRequest, ProposalRequest.id == Proposal.request_id)
            .where(ProposalRequest.group_id == r.group_id, Proposal.status != "DRAFT")
            .order_by(Proposal.submitted_at))).all()
    return await _proposals_out(session, list(rows))


async def _buyer_proposal(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID) -> tuple[Proposal, frozenset[str]]:
    p = await _proposal(session, proposal_id, lock=True)
    if p.status == "DRAFT":
        raise NotFound("Proposal not found")
    roles = await _require_buyer(session, actor, p.organization_id, *DECIDERS)
    return p, roles


async def request_revision(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID, body: RevisionIn) -> ProposalOut:
    p, _ = await _buyer_proposal(session, actor, proposal_id)
    if _expired(p):
        raise Conflict("This proposal has expired", code="PROPOSAL_EXPIRED")
    PROPOSAL_STATES.assert_can(p.status, "REVISION_REQUESTED")
    p.status = "REVISION_REQUESTED"
    p.revision_requests = [*p.revision_requests, {"at": clock.now().isoformat(), "by": str(actor.identity_id),
                                                  "changes": [c.model_dump() for c in body.changes], "note": body.note}]
    p.revision_count += 1
    _prop_evt(session, E.PROPOSAL_REVISION_REQUESTED, p, changes=[c.model_dump() for c in body.changes])
    await session.flush()
    return (await _proposals_out(session, [p]))[0]


async def reject_proposal(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID, body: RejectIn) -> ProposalOut:
    p, _ = await _buyer_proposal(session, actor, proposal_id)
    if p.status not in LIVE_PROPOSAL:
        raise Conflict("This proposal is already decided", code="PROPOSAL_DECIDED")
    r = await _request(session, p.request_id, lock=True)
    await _end_proposal(session, p, "REJECTED", body.reasonCode, actor, body.note)
    _close_request(r, "CLOSED", "PROPOSAL_REJECTED")
    await session.flush()
    return (await _proposals_out(session, [p]))[0]


def _terms(r: ProposalRequest, p: Proposal) -> dict:
    return {
        "objective": r.objective,
        "scope": r.details + (f"\n\nProfessional's scope notes: {p.scope_notes}" if p.scope_notes else ""),
        "deliverables": p.deliverables,
        "milestones": [{"sequence": i + 1, "title": m["title"], "description": m.get("description", ""),
                        "amountMinor": m["amountMinor"], "dueDate": m.get("dueDate"), "deliverableKeys": m["deliverableKeys"]}
                       for i, m in enumerate(p.milestones)],
        "assumptions": p.assumptions,
        "exclusions": p.exclusions,
        "startDate": p.start_date.isoformat() if p.start_date else None,
        "endDate": p.end_date.isoformat() if p.end_date else None,
        "governingLaw": None,
        "clauses": [],
    }


async def accept_proposal(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID) -> ProposalOut:
    p, _ = await _buyer_proposal(session, actor, proposal_id)
    if p.status == "REVISION_REQUESTED":
        raise Conflict("You asked for changes; wait for the revised proposal before accepting", code="REVISION_PENDING")
    if p.status not in ("SUBMITTED", "UNDER_REVIEW"):
        raise Conflict("This proposal is already decided", code="PROPOSAL_DECIDED")
    if _expired(p):
        raise Conflict("This proposal has expired and can no longer be accepted", code="PROPOSAL_EXPIRED")
    _check_tier(await trust_facade.get_trust(session, p.professional_id), "This professional")
    org = await buyer_facade.get_organization(session, p.organization_id)
    pro = await professional_facade.get_professional(session, p.professional_id)
    if pro is not None and _conflict(set(pro.jurisdictions_served), org):
        raise PolicyBlocked(f"{pro.display_name} does not serve {org.country}; the engagement cannot be agreed. "
                            "Choose a professional who serves your country.", code="JURISDICTION_CONFLICT")
    limit = await buyer_facade.get_member_spend_limit(session, p.organization_id, actor.identity_id)
    if limit is not None and limit.currency == p.currency and p.total_minor > limit.minor:
        raise PolicyBlocked(f"{_money(p.total_minor, p.currency)} is above your approval limit of "
                            f"{_money(limit.minor, limit.currency)}; ask a colleague with a higher limit to accept",
                            code="SPEND_LIMIT_EXCEEDED")

    r = await _request(session, p.request_id, lock=True)
    terms = _terms(r, p)
    p.terms_hash = hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    PROPOSAL_STATES.assert_can(p.status, "ACCEPTED")
    p.status, p.decided_at, p.decided_by = "ACCEPTED", clock.now(), actor.identity_id
    await cancel_timer(session, TIMER_EXPIRY, str(p.id))
    _close_request(r, "CLOSED", "PROPOSAL_ACCEPTED")
    _prop_evt(session, E.PROPOSAL_ACCEPTED, p, buyerIdentityId=p.buyer_identity_id, engagementType=r.engagement_type,
              currency=p.currency, totalMinor=p.total_minor, policyVersionId=None, policyVersionLabel=POLICY_LABEL,
              termsHash=p.terms_hash, terms=terms, service=r.service, ndaRequired=r.nda_required,
              pricingModel=p.pricing_model, summary=p.summary)

    # Accepting one proposal closes the same requirement sent to other professionals.
    siblings = (await session.scalars(select(ProposalRequest).where(
        ProposalRequest.group_id == r.group_id, ProposalRequest.id != r.id,
        ProposalRequest.status.in_(OPEN_REQUEST)).with_for_update())).all()
    for s in siblings:
        sp = await session.scalar(select(Proposal).where(Proposal.request_id == s.id).with_for_update())
        if sp and sp.status in ("DRAFT", *LIVE_PROPOSAL):
            await _end_proposal(session, sp, "REJECTED", "ANOTHER_PROPOSAL_ACCEPTED", actor)
        _close_request(s, "CANCELLED" if s.status == "DRAFT" else "CLOSED", "ANOTHER_PROPOSAL_ACCEPTED")
    await session.flush()
    return (await _proposals_out(session, [p]))[0]


# ---- Timers --------------------------------------------------------------------------------

async def expire(session: AsyncSession, payload: dict) -> None:
    p = await session.get(Proposal, uuid.UUID(payload["proposalId"]), with_for_update=True)
    if p is None or p.status not in LIVE_PROPOSAL or (p.valid_until and p.valid_until >= _today()):
        return
    r = await session.get(ProposalRequest, p.request_id, with_for_update=True)
    await _end_proposal(session, p, "EXPIRED", "VALIDITY_ENDED", None)
    if r is not None and r.status in OPEN_REQUEST:
        _close_request(r, "CLOSED", "PROPOSAL_EXPIRED")



# ---- Proposal attachments (RFP flow s.8: optional portfolio items or supporting documents) -------------------------

MAX_PROPOSAL_ATTACHMENTS = 3


async def add_proposal_attachments(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID, body: ProposalAttachmentsIn) -> ProposalOut:
    p = await _proposal(session, proposal_id, lock=True)
    await _require_owner(session, actor, p.professional_id)
    if p.status not in ("DRAFT", "REVISION_REQUESTED"):
        raise Conflict("Files can be changed while the proposal is a draft or being revised", code="PROPOSAL_LOCKED")
    existing = list(p.attachments or [])
    new = [f for f in body.files if f.sha256 not in {a["sha256"] for a in existing}]
    if len(existing) + len(new) > MAX_PROPOSAL_ATTACHMENTS:
        raise ValidationFailed(f"Attach at most {MAX_PROPOSAL_ATTACHMENTS} files to a proposal", code="TOO_MANY_ATTACHMENTS")
    p.attachments = existing + store_uploads(f"proposals/{p.request_id}/proposal-{p.id}", new)
    await session.flush()
    return (await _proposals_out(session, [p]))[0]


async def remove_proposal_attachment(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID, sha256: str) -> ProposalOut:
    p = await _proposal(session, proposal_id, lock=True)
    await _require_owner(session, actor, p.professional_id)
    if p.status not in ("DRAFT", "REVISION_REQUESTED"):
        raise Conflict("Files can be changed while the proposal is a draft or being revised", code="PROPOSAL_LOCKED")
    p.attachments = [a for a in p.attachments or [] if a["sha256"] != sha256]
    await session.flush()
    return (await _proposals_out(session, [p]))[0]


async def proposal_attachment_file(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID, sha256: str) -> tuple[bytes, str | None, str]:
    """The professional who wrote it, or the buyer's organisation once it has been sent. Every opening is audited."""
    p = await _proposal(session, proposal_id)
    if p.professional_id != await _my_professional_id(session, actor):
        if p.status == "DRAFT" or not await _buyer_roles(session, actor, p.organization_id):
            raise NotFound("Proposal not found")
    rec = find_file(p.attachments or [], sha256)
    data = read_file(rec)
    record_audit(session, "proposal.attachment.viewed", object_type="Proposal", object_id=p.id, tenant_id=p.organization_id,
                 evidence_hash=rec["sha256"])
    return data, rec.get("contentType"), rec["name"]
