"""Dispute domain (Step 9, Dispute Resolution doc, BUILD_SPEC s.dispute).

Neutral, structured, evidence-first: funds freeze on submission (escrow consumes DISPUTE_INITIATED), both parties add
fingerprinted evidence, then structured proposals (release / refund per milestone). Unresolved cases go to a mediator,
whose recommendation binds only if both parties accept; otherwise a platform decision needs the mediator AND a second
approver with the Legal role (no single role initiates and finalises). AI never decides. Independent appeals
preserve the original settlement; policy-pinned automatic intake freezes eligible funded work.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.admin import facade as admin_facade
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.escrow import facade as escrow_facade
from zoikorum.domains.dispute.models import DisputeAppeal, DisputeCase, EvidenceItem, ResolutionProposal, TimelineEntry
from zoikorum.domains.dispute.schemas import (
    AllocationIn, AllocationOut, ArbitrationAwardIn, ArbitrationReferIn, AssignIn, DisputeIn, DisputeOut, EvidenceIn, EvidenceOut, MilestoneRef, ProposalOut,
    RecommendationIn, ResolutionIn, TimelineOut,
)
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.policy import facade as policy_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock, fx
from zoikorum.shared.auth import Actor, OrgRole, PlatformRole
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, PolicyBlocked, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.http import next_cursor, paginate
from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.relay import cancel_timer, schedule_timer
from zoikorum.shared.state_machine import StateMachine
from zoikorum.shared.uploads import file_out, find_file, read_file, store_uploads

CASE_STATES = StateMachine("DisputeCase", {
    "EVIDENCE_COLLECTION": {"DIRECT_RESOLUTION", "MEDIATION", "DECIDED"},
    "DIRECT_RESOLUTION": {"MEDIATION", "DECIDED"},
    "MEDIATION": {"DECIDED"},
    "DECIDED": {"ENFORCED"},
    "ENFORCED": {"CLOSED"},
    "CLOSED": set(),
})
OPEN = ("EVIDENCE_COLLECTION", "DIRECT_RESOLUTION", "MEDIATION")
DISPUTABLE = ("IN_PROGRESS", "SUBMITTED", "REVISION_REQUESTED")  # funded and not yet accepted
SKIP_DIRECT = ("PROFESSIONAL_CONDUCT", "COMPLIANCE_BREACH")  # conduct/compliance bypass negotiation (doc s.4)
OPERATORS = (PlatformRole.MEDIATOR, PlatformRole.LEGAL, PlatformRole.PLATFORM_ADMIN)
TIMER_EVIDENCE = "dispute.evidence_window"
TIMER_DIRECT = "dispute.direct_resolution_window"
TIMER_RECOMMENDATION = "dispute.recommendation_answer"  # an unanswered recommendation counts as declined
CATEGORY_LABEL = {"SCOPE_DELIVERABLES": "Scope & deliverables", "QUALITY_ACCEPTANCE": "Quality / acceptance", "TIMELINE_DELAY": "Timeline & delays",
                  "PAYMENT_RELEASE": "Payment & release", "PROFESSIONAL_CONDUCT": "Professional conduct", "COMPLIANCE_BREACH": "Compliance / policy breach",
                  "JURISDICTION_LEGAL": "Jurisdictional or legal"}
OUTCOME_LABEL = {"REWORK": "rework", "PARTIAL_RELEASE": "partial release", "FULL_RELEASE": "full release", "PARTIAL_REFUND": "partial refund",
                 "FULL_REFUND": "full refund", "TIMELINE_EXTENSION": "timeline extension", "TERMINATION": "engagement termination"}


def _money(minor: int, ccy: str) -> str:
    return f"{ccy} {minor / 100:,.2f}"


add_business_days = clock.add_business_days


def _evt(session: AsyncSession, event_type: str, c: DisputeCase, **payload) -> None:
    record_event(session, event_type, aggregate_type="DisputeCase", aggregate_id=c.id, tenant_id=c.organization_id,
                 payload={"disputeId": c.id, "contractId": c.contract_id, "organizationId": c.organization_id,
                          "professionalId": c.professional_id, **payload})


def _log(session: AsyncSession, c: DisputeCase, kind: str, actor: str, text: str, ref: str | None = None) -> None:
    session.add(TimelineEntry(case_id=c.id, kind=kind, actor=actor, text=text[:500], ref=ref))


async def _case(session: AsyncSession, case_id: uuid.UUID, lock: bool = False) -> DisputeCase:
    c = await session.get(DisputeCase, case_id, with_for_update=lock)
    if c is None:
        raise NotFound("Dispute not found")
    return c


async def _party_of(session: AsyncSession, actor: Actor, org_id: uuid.UUID, professional_id: uuid.UUID) -> str | None:
    if await buyer_facade.get_member_roles(session, org_id, actor.identity_id):
        return "BUYER"
    pro = await professional_facade.get_professional(session, professional_id)
    if pro is not None and pro.identity_id == actor.identity_id:
        return "PROFESSIONAL"
    return None


BUYER_DECIDERS = (OrgRole.REQUESTER, OrgRole.APPROVER)  # the same people who may accept work or sign for the organisation


async def _require_buyer_authority(session: AsyncSession, actor: Actor, c, release_minor: int = 0, *, settle: bool = True) -> None:
    """Acting for the buyer organisation in a dispute is held to the same rules as accepting work: the Requester or
    Approver role, and - when it settles money - a fresh two-step confirmation and the person's spend limit."""
    roles = await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id)
    if not roles.intersection(BUYER_DECIDERS):
        raise Forbidden("Acting on a dispute for your organisation needs the Requester or Approver role", code="ROLE_REQUIRED")
    if not settle:
        return
    rules = await _rules(session, c)
    if rules.dispute_legal_review_above_minor is not None and c.disputed_minor > rules.dispute_legal_review_above_minor \
            and OrgRole.LEGAL_REVIEWER not in roles:
        raise Forbidden("Your organisation's policy needs its Legal Reviewer to settle a dispute of this size",
                        code="LEGAL_REVIEW_REQUIRED")
    actor.require_step_up()
    limit = await buyer_facade.get_member_spend_limit(session, c.organization_id, actor.identity_id)
    if release_minor and limit is not None and not fx.within_limit(release_minor, c.currency, limit.minor, limit.currency):
        raise PolicyBlocked("Releasing this amount is above your approval limit; ask a colleague with a higher limit",
                            code="SPEND_LIMIT_EXCEEDED")


def _release(allocations: list[dict]) -> int:
    return sum(int(a.get("releaseMinor") or 0) for a in allocations)


async def _viewer(session: AsyncSession, actor: Actor, c: DisputeCase) -> str:
    party = await _party_of(session, actor, c.organization_id, c.professional_id)
    if party:
        return party
    if actor.has_platform_role(*OPERATORS):
        actor.require_platform_role(*OPERATORS)
        return "MEDIATOR" if c.mediator_identity_id == actor.identity_id else "OPERATOR"
    raise NotFound("Dispute not found")


async def _require_party(session: AsyncSession, actor: Actor, c: DisputeCase) -> str:
    v = await _viewer(session, actor, c)
    if v not in ("BUYER", "PROFESSIONAL"):
        raise Forbidden("Only the parties to the dispute can do this")
    return v


async def _actor_label(session: AsyncSession, actor: Actor, role: str) -> str:
    who = await identity_facade.get_identity(session, actor.identity_id)
    name = who.display_name if who else "Someone"
    return {"BUYER": f"Buyer ({name})", "PROFESSIONAL": f"Professional ({name})", "MEDIATOR": f"Mediator ({name})"}.get(role, f"{role.title()} ({name})")


async def _contract(session: AsyncSession, contract_id: uuid.UUID) -> contract_facade.ContractSummary:
    k = await contract_facade.get_contract(session, contract_id)
    if k is None:
        raise NotFound("Contract not found")
    return k


# ---- Allocations ----------------------------------------------------------------------------------

async def _allocations(session: AsyncSession, c: DisputeCase, outcome: str, raw: list[AllocationIn],
                       extend_days: int | None = None) -> list[dict]:
    """Validates a structured outcome. Money outcomes split each disputed milestone fully into release + refund."""
    k = await _contract(session, c.contract_id)
    ms = {m.id: m for m in k.milestones if str(m.id) in c.milestone_ids}
    if outcome in ("REWORK", "TIMELINE_EXTENSION"):
        if any(a.releaseMinor or a.refundMinor for a in raw):
            raise ValidationFailed("Rework and timeline extension keep the money held; do not split it", code="ALLOCATION_NOT_ALLOWED")
        mo = "REWORK" if outcome == "REWORK" else "EXTEND"
        if outcome == "TIMELINE_EXTENSION" and not extend_days:
            raise ValidationFailed("Say how many days later the work is due", code="EXTENSION_DAYS_REQUIRED")
        return [{"milestoneId": str(mid), "releaseMinor": 0, "refundMinor": 0, "milestoneOutcome": mo,
                 **({"extendDays": extend_days} if outcome == "TIMELINE_EXTENSION" else {})} for mid in ms]
    if not raw and outcome in ("FULL_RELEASE", "FULL_REFUND", "TERMINATION"):
        release = outcome == "FULL_RELEASE"
        raw = [AllocationIn(milestoneId=mid, releaseMinor=m.amount_minor if release else 0, refundMinor=0 if release else m.amount_minor)
               for mid, m in ms.items()]
    given = {a.milestoneId: a for a in raw}
    if set(given) != set(ms):
        raise ValidationFailed("Split every disputed milestone, and only those", code="ALLOCATION_MILESTONES")
    out = []
    for mid, m in ms.items():
        a = given[mid]
        if a.releaseMinor + a.refundMinor != m.amount_minor:
            raise ValidationFailed(f"M{m.sequence}: release plus refund must equal {_money(m.amount_minor, m.currency)}", code="ALLOCATION_MISMATCH")
        out.append({"milestoneId": str(mid), "releaseMinor": a.releaseMinor, "refundMinor": a.refundMinor,
                    "milestoneOutcome": "ACCEPT" if a.releaseMinor > 0 else "CANCEL"})
    if outcome == "FULL_RELEASE" and any(x["refundMinor"] for x in out):
        raise ValidationFailed("A full release refunds nothing", code="ALLOCATION_MISMATCH")
    if outcome == "FULL_REFUND" and any(x["releaseMinor"] for x in out):
        raise ValidationFailed("A full refund releases nothing", code="ALLOCATION_MISMATCH")
    return out


async def _allocations_out(session: AsyncSession, c: DisputeCase, allocations: list[dict]) -> list[AllocationOut]:
    k = await _contract(session, c.contract_id)
    ms = {str(m.id): m for m in k.milestones}
    return [AllocationOut(milestoneId=uuid.UUID(a["milestoneId"]), sequence=ms[a["milestoneId"]].sequence, title=ms[a["milestoneId"]].title,
                          release=MoneyDTO(amountMinor=a["releaseMinor"], currency=c.currency),
                          refund=MoneyDTO(amountMinor=a["refundMinor"], currency=c.currency), milestoneOutcome=a["milestoneOutcome"])
            for a in allocations if a["milestoneId"] in ms]


# ---- Reads ---------------------------------------------------------------------------------------------

def _next_step(c: DisputeCase, viewer: str) -> str:
    if c.status == "EVIDENCE_COLLECTION":
        mine = viewer in c.evidence_complete
        return ("You marked your evidence complete; waiting for the other party or the deadline." if mine else
                f"Add your evidence by {c.evidence_deadline:%d %b %Y %H:%M} UTC, then mark it complete.") if viewer in ("BUYER", "PROFESSIONAL") \
            else "Parties are submitting evidence."
    if c.status == "DIRECT_RESOLUTION":
        return f"Make or answer a structured proposal before {c.direct_deadline:%d %b %Y} — otherwise the case goes to a mediator."
    if c.status == "MEDIATION":
        if c.arbitration:
            return (f"Referred to external arbitration ({c.arbitration['forum']}). The money stays frozen until the platform's Legal "
                    "team records the arbitrator's award.")
        if not c.mediator_identity_id:
            return "Waiting for a mediator to be assigned."
        if c.pending_decision:
            return "A platform decision is waiting for approval by a second reviewer (Legal)."
        if c.recommendation:
            return "The mediator has issued a recommendation. It is binding only if both parties accept it."
        return "The mediator is reviewing the evidence."
    if c.status == "DECIDED":
        return "Decision issued. The money is being moved as decided."
    return "Closed. The record is sealed."


async def _out(session: AsyncSession, actor: Actor, c: DisputeCase, viewer: str) -> DisputeOut:
    k = await _contract(session, c.contract_id)
    evidence = (await session.scalars(select(EvidenceItem).where(EvidenceItem.case_id == c.id).order_by(EvidenceItem.created_at))).all()
    proposals = (await session.scalars(select(ResolutionProposal).where(ResolutionProposal.case_id == c.id).order_by(ResolutionProposal.created_at))).all()
    timeline = (await session.scalars(select(TimelineEntry).where(TimelineEntry.case_id == c.id).order_by(TimelineEntry.created_at))).all()
    rules = await _rules(session, c)
    mediation_required = await _mediation_required(session, c, rules)
    return DisputeOut(
        mediationRequired=mediation_required, arbitration=c.arbitration,
        legalReviewRequired=rules.dispute_legal_review_above_minor is not None and c.disputed_minor > rules.dispute_legal_review_above_minor,
        id=c.id, reference=c.reference, contractId=c.contract_id, contractReference=c.contract_reference,
        milestones=[MilestoneRef(id=m.id, sequence=m.sequence, title=m.title, amount=MoneyDTO(amountMinor=m.amount_minor, currency=m.currency))
                    for m in k.milestones if str(m.id) in c.milestone_ids],
        category=c.category, summary=c.summary, desiredOutcome=c.desired_outcome, context=c.context, initiatorParty=c.initiator_party,
        status=c.status, disputed=MoneyDTO(amountMinor=c.disputed_minor, currency=c.currency), evidenceDeadline=c.evidence_deadline,
        evidenceComplete=list(c.evidence_complete), directDeadline=c.direct_deadline, mediatorAssigned=c.mediator_identity_id is not None,
        recommendation=c.recommendation, pendingDecision=c.pending_decision, decision=c.decision, decidedAt=c.decided_at, closedAt=c.closed_at,
        evidence=[EvidenceOut(id=e.id, party=e.party, evidenceType=e.evidence_type, description=e.description,
                              items=[file_out(i) for i in e.items], submittedAt=e.created_at) for e in evidence],
        proposals=[ProposalOut(id=p.id, party=p.party, outcome=p.outcome, allocations=await _allocations_out(session, c, p.allocations), note=p.note,
                               status=p.status, createdAt=p.created_at, respondedAt=p.responded_at, mine=p.party == viewer) for p in proposals],
        timeline=[TimelineOut(kind=t.kind, actor=t.actor, text=t.text, at=t.created_at, ref=t.ref) for t in timeline],
        prefersEarlyResolution=c.prefers_early_resolution, clarifications=list(c.clarifications),
        retainUntil=c.retain_until, retentionBasis=c.retention_basis, legalHold=c.legal_hold,
        canCooldown=viewer in ("BUYER", "PROFESSIONAL") and viewer not in c.cooldown_used_by and c.status in ("EVIDENCE_COLLECTION", "DIRECT_RESOLUTION"),
        viewerRole=viewer, canEscalate=c.status == "DIRECT_RESOLUTION" and viewer in ("BUYER", "PROFESSIONAL")
        and (mediation_required or any(p.status == "REJECTED" for p in proposals)),
        nextStep="The buyer organisation's policy needs a mediator for a dispute of this size: escalate to start mediation."
        if mediation_required and c.status == "DIRECT_RESOLUTION" else _next_step(c, viewer), createdAt=c.created_at,
    )


async def get_dispute(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> DisputeOut:
    c = await _case(session, case_id)
    return await _out(session, actor, c, await _viewer(session, actor, c))


async def list_disputes(session: AsyncSession, actor: Actor, role: str, contract_id: uuid.UUID | None,
                        cursor: str | None = None, limit: int | None = None) -> dict:
    stmt = select(DisputeCase)
    if contract_id:
        stmt = stmt.where(DisputeCase.contract_id == contract_id)
    if role == "buyer":
        stmt = stmt.where(or_(DisputeCase.organization_id.in_(actor.org_ids), DisputeCase.initiated_by == actor.identity_id))
    elif role == "professional":
        pro = await professional_facade.get_professional_by_identity(session, actor.identity_id)
        if pro is None:
            return {"items": [], "nextCursor": None}
        stmt = stmt.where(DisputeCase.professional_id == pro.id)
    else:
        actor.require_platform_role(*OPERATORS)
    stmt, lim = paginate(stmt, DisputeCase, cursor, limit)
    rows = (await session.scalars(stmt)).all()
    out = []
    for c in rows[:lim]:
        try:
            out.append(await _out(session, actor, c, await _viewer(session, actor, c)))
        except NotFound:
            continue  # stale token org list: skip cases the caller cannot see
    return {"items": out, "nextCursor": next_cursor(rows, lim)}


# ---- Intake ------------------------------------------------------------------------------------------------

async def open_dispute(session: AsyncSession, actor: Actor, body: DisputeIn) -> DisputeOut:
    from sqlalchemy import text
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"dispute:{body.contractId}"})
    k = await _contract(session, body.contractId)
    party = await _party_of(session, actor, k.organization_id, k.professional_id)
    if party is None:
        raise NotFound("Contract not found")
    if "DISPUTE_ACCESS_RESTRICTION" in await admin_facade.active_restrictions(session, "IDENTITY", actor.identity_id):
        raise Forbidden("Opening new disputes is restricted on your account for now (see Account safety). You can still "
                        "answer disputes opened against you.", code="DISPUTE_ACCESS_RESTRICTED")
    if party == "BUYER":
        await _require_buyer_authority(session, actor, k, settle=False)  # opening freezes money: decider roles only
    ms = {m.id: m for m in k.milestones}
    wanted = set(body.milestoneIds)
    if not wanted <= set(ms):
        raise NotFound("Milestone not found on this contract")
    # Accepted work whose payment is still held: inside the contract's challenge window it may be disputed for any reason
    # (a defect found after acceptance); after it, only about the payment itself (a release the buyer's approver refused).
    stuck = {i for i in wanted if ms[i].status == "ACCEPTED" and await escrow_facade.release_stuck(session, i)}
    window = int((await contract_facade.policy_controls(session, k.id)).get("challengeWindowDays") or 0)
    in_window = {i for i in stuck if window and ms[i].accepted_at and clock.now() < ms[i].accepted_at + timedelta(days=window)}
    if stuck - in_window and body.category != "PAYMENT_RELEASE":
        raise ValidationFailed("Accepted work whose payment is held can only be disputed as \"Payment & release\"",
                               code="PAYMENT_RELEASE_ONLY")
    if k.status not in ("ACTIVE", "DISPUTED") and not (stuck == wanted and k.status == "COMPLETED"):
        raise Conflict("Only an active engagement can be disputed", code="CONTRACT_NOT_ACTIVE")
    open_cases = (await session.scalars(select(DisputeCase).where(DisputeCase.contract_id == k.id, DisputeCase.status.in_(OPEN)))).all()
    if any(wanted & {uuid.UUID(m) for m in oc.milestone_ids} for oc in open_cases):
        raise Conflict("There is already an open dispute for this milestone; add evidence to it instead", code="DUPLICATE_DISPUTE")
    bad = [ms[i] for i in wanted if ms[i].status not in DISPUTABLE and i not in stuck]
    if bad:
        raise Conflict(f"M{bad[0].sequence} cannot be disputed ({bad[0].status.replace('_', ' ').lower()}). Only funded milestones that are "
                       "not yet accepted, or accepted work whose payment is still held, can be disputed.", code="MILESTONE_NOT_DISPUTABLE")

    now = clock.now()
    c = DisputeCase(prefers_early_resolution=body.prefersEarlyResolution, reference=f"ZK-DSP-{uuid.uuid4().hex[:8].upper()}", contract_id=k.id, contract_reference=k.reference or "—",
                    organization_id=k.organization_id, professional_id=k.professional_id, milestone_ids=[str(i) for i in sorted(wanted, key=str)],
                    category=body.category, summary=body.summary.strip(), desired_outcome=body.desiredOutcome, context=body.context.strip(),
                    initiated_by=actor.identity_id, initiator_party=party, status="EVIDENCE_COLLECTION", currency=k.currency,
                    disputed_minor=sum(ms[i].amount_minor for i in wanted),
                    evidence_deadline=now + timedelta(days=(await contract_facade.policy_controls(session, k.id)).get(
                        "disputeEvidenceDays", get_settings().dispute_evidence_days)), evidence_complete=[])
    session.add(c)
    await session.flush()
    label = await _actor_label(session, actor, party)
    _log(session, c, "OPENED", label, f"Dispute opened: {CATEGORY_LABEL[c.category]}. Desired outcome: {OUTCOME_LABEL[c.desired_outcome]}.")
    _log(session, c, "FROZEN", "System", f"{_money(c.disputed_minor, c.currency)} frozen in escrow. Acceptance and release are paused.")
    _evt(session, E.DISPUTE_INITIATED, c, milestoneIds=c.milestone_ids, category=c.category, desiredOutcome=c.desired_outcome,
         initiatedBy=actor.identity_id)
    _evt(session, E.DISPUTE_EVIDENCE_WINDOW_OPENED, c, deadline=c.evidence_deadline)
    await schedule_timer(session, TIMER_EVIDENCE, str(c.id), c.evidence_deadline, {"disputeId": str(c.id)})
    await session.flush()
    return await _out(session, actor, c, party)


# ---- Evidence ---------------------------------------------------------------------------------------------

async def evidence_file(session: AsyncSession, actor: Actor, case_id: uuid.UUID, sha256: str) -> tuple[bytes, str | None, str]:
    """An evidence file, for both parties and the mediator / legal team. Every opening is audited."""
    c = await _case(session, case_id)
    viewer = await _viewer(session, actor, c)
    rows = (await session.scalars(select(EvidenceItem).where(EvidenceItem.case_id == c.id))).all()
    rec = find_file([i for e in rows for i in e.items], sha256)
    data = read_file(rec)
    record_audit(session, "dispute.evidence.viewed", object_type="DisputeCase", object_id=c.id, tenant_id=c.organization_id,
                 evidence_hash=rec["sha256"], details={"viewer": viewer})
    return data, rec.get("contentType"), rec["name"]


async def add_evidence(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: EvidenceIn) -> DisputeOut:
    c = await _case(session, case_id, lock=True)
    party = await _require_party(session, actor, c)
    if c.status != "EVIDENCE_COLLECTION" or clock.now() > c.evidence_deadline:
        raise Conflict("The evidence window has closed", code="EVIDENCE_CLOSED")
    item = EvidenceItem(case_id=c.id, party=party, submitted_by=actor.identity_id, evidence_type=body.evidenceType,
                        description=body.description.strip(), items=store_uploads(f"disputes/{c.id}", body.items))
    session.add(item)
    await session.flush()
    _log(session, c, "EVIDENCE", await _actor_label(session, actor, party),
         f"Evidence added: {body.evidenceType.replace('_', ' ').lower()}" + (f" ({len(body.items)} file(s))" if body.items else ""),
         ref=f"evidence:{item.id}")
    _evt(session, E.DISPUTE_EVIDENCE_SUBMITTED, c, party=party, evidenceType=body.evidenceType, files=len(body.items))
    await session.flush()
    return await _out(session, actor, c, party)


async def evidence_complete(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> DisputeOut:
    c = await _case(session, case_id, lock=True)
    party = await _require_party(session, actor, c)
    if c.status != "EVIDENCE_COLLECTION":
        raise Conflict("The evidence window has closed", code="EVIDENCE_CLOSED")
    if party not in c.evidence_complete:
        c.evidence_complete = [*c.evidence_complete, party]
        _log(session, c, "EVIDENCE_DONE", await _actor_label(session, actor, party), "Marked their evidence as complete.")
    if set(c.evidence_complete) >= {"BUYER", "PROFESSIONAL"}:
        await cancel_timer(session, TIMER_EVIDENCE, str(c.id))
        await _after_evidence(session, c)
    await session.flush()
    return await _out(session, actor, c, party)


async def _after_evidence(session: AsyncSession, c: DisputeCase) -> None:
    if c.category in SKIP_DIRECT:
        await _to_mediation(session, c, "Conduct and compliance disputes go straight to a mediator.")
        return
    CASE_STATES.assert_can(c.status, "DIRECT_RESOLUTION")
    c.status = "DIRECT_RESOLUTION"
    controls = await contract_facade.policy_controls(session, c.contract_id)
    c.direct_deadline = add_business_days(clock.now(), controls.get("directResolutionBusinessDays", get_settings().dispute_direct_resolution_business_days))
    _log(session, c, "DIRECT", "System", f"Direct resolution window open until {c.direct_deadline:%d %b %Y}. Use structured proposals.")
    await schedule_timer(session, TIMER_DIRECT, str(c.id), c.direct_deadline, {"disputeId": str(c.id)})


async def _to_mediation(session: AsyncSession, c: DisputeCase, why: str) -> None:
    CASE_STATES.assert_can(c.status, "MEDIATION")
    c.status, c.escalated_at = "MEDIATION", clock.now()
    for p in (await session.scalars(select(ResolutionProposal).where(ResolutionProposal.case_id == c.id, ResolutionProposal.status == "OPEN"))).all():
        p.status = "SUPERSEDED"
    await cancel_timer(session, TIMER_DIRECT, str(c.id))
    _log(session, c, "MEDIATION", "System", f"Moved to mediation. {why}")
    _evt(session, E.DISPUTE_ESCALATED, c, reason=why)


async def evidence_window_closed(session: AsyncSession, payload: dict) -> None:
    c = await session.get(DisputeCase, uuid.UUID(payload["disputeId"]), with_for_update=True)
    if c is not None and c.status == "EVIDENCE_COLLECTION":
        _log(session, c, "EVIDENCE_CLOSED", "System", "Evidence window closed.")
        await _after_evidence(session, c)


async def direct_window_closed(session: AsyncSession, payload: dict) -> None:
    c = await session.get(DisputeCase, uuid.UUID(payload["disputeId"]), with_for_update=True)
    if c is not None and c.status == "DIRECT_RESOLUTION":
        await _to_mediation(session, c, "The direct resolution window ended without agreement.")


# ---- Direct resolution ------------------------------------------------------------------------------------

async def propose(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: ResolutionIn) -> DisputeOut:
    c = await _case(session, case_id, lock=True)
    party = await _require_party(session, actor, c)
    if c.status != "DIRECT_RESOLUTION":
        raise Conflict("Proposals are made during the direct resolution window", code="NOT_IN_DIRECT_RESOLUTION")
    if await _mediation_required(session, c):
        raise Conflict("The buyer organisation's policy needs a mediator for a dispute of this size. Escalate the case instead.",
                       code="MEDIATION_REQUIRED")
    allocations = await _allocations(session, c, body.outcome, body.allocations, body.extendDays)
    if party == "BUYER":
        await _require_buyer_authority(session, actor, c, _release(allocations))
    for p in (await session.scalars(select(ResolutionProposal).where(
            ResolutionProposal.case_id == c.id, ResolutionProposal.party == party, ResolutionProposal.status == "OPEN"))).all():
        p.status = "SUPERSEDED"
    p = ResolutionProposal(case_id=c.id, party=party, proposed_by=actor.identity_id, outcome=body.outcome, allocations=allocations,
                           note=body.note.strip(), status="OPEN")
    session.add(p)
    await session.flush()
    _log(session, c, "PROPOSAL", await _actor_label(session, actor, party), f"Proposed {OUTCOME_LABEL[body.outcome]}.")
    _evt(session, E.DISPUTE_RESOLUTION_PROPOSED, c, proposalId=p.id, party=party, outcome=p.outcome)
    return await _out(session, actor, c, party)


async def _proposal(session: AsyncSession, proposal_id: uuid.UUID) -> tuple[ResolutionProposal, DisputeCase]:
    p = await session.get(ResolutionProposal, proposal_id, with_for_update=True)
    if p is None:
        raise NotFound("Proposal not found")
    return p, await _case(session, p.case_id, lock=True)


async def respond(session: AsyncSession, actor: Actor, proposal_id: uuid.UUID, accept: bool) -> DisputeOut:
    p, c = await _proposal(session, proposal_id)
    party = await _require_party(session, actor, c)
    if p.party == party:
        raise Forbidden("The other party answers your proposal")
    if p.status != "OPEN" or c.status != "DIRECT_RESOLUTION":
        raise Conflict("This proposal is no longer open", code="PROPOSAL_CLOSED")
    if accept and await _mediation_required(session, c):
        raise Conflict("The buyer organisation's policy needs a mediator for a dispute of this size. Escalate the case instead.",
                       code="MEDIATION_REQUIRED")
    if accept and party == "BUYER":
        await _require_buyer_authority(session, actor, c, _release(p.allocations))
    p.status, p.responded_at = ("ACCEPTED" if accept else "REJECTED"), clock.now()
    label = await _actor_label(session, actor, party)
    if accept:
        _log(session, c, "AGREED", label, f"Accepted the proposal: {OUTCOME_LABEL[p.outcome]}.")
        _evt(session, E.DISPUTE_RESOLUTION_AGREED, c, proposalId=p.id)
        await _resolve(session, c, p.outcome, p.allocations, "DIRECT", actor.identity_id,
                       f"Both parties agreed directly on {OUTCOME_LABEL[p.outcome]}." + (f" Note: {p.note}" if p.note else ""), [])
    else:
        _log(session, c, "REJECTED", label, f"Declined the proposal ({OUTCOME_LABEL[p.outcome]}). Escalation to a mediator is now available.")
    await session.flush()
    return await _out(session, actor, c, party)


async def escalate(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> DisputeOut:
    c = await _case(session, case_id, lock=True)
    party = await _require_party(session, actor, c)
    if c.status != "DIRECT_RESOLUTION":
        raise Conflict("Only a case in direct resolution can be escalated", code="NOT_IN_DIRECT_RESOLUTION")
    if party == "BUYER":
        rules = await _rules(session, c)
        if rules.dispute_escalation_roles:
            roles = await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id)
            if not roles.intersection(rules.dispute_escalation_roles):
                raise Forbidden("Your organisation's policy names who may escalate a dispute: "
                                + ", ".join(r.replace("_", " ").title() for r in rules.dispute_escalation_roles), code="ESCALATION_ROLE_REQUIRED")
    if not await _mediation_required(session, c) and not await session.scalar(select(ResolutionProposal.id).where(ResolutionProposal.case_id == c.id, ResolutionProposal.status == "REJECTED")):
        raise Conflict("Escalation unlocks after a proposal has been declined, or when the window ends", code="ESCALATION_LOCKED")
    await _to_mediation(session, c, f"Escalated by the {party.lower()}.")
    await session.flush()
    return await _out(session, actor, c, party)


# ---- Mediation ---------------------------------------------------------------------------------------------

async def assign_mediator(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: AssignIn) -> DisputeOut:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN, PlatformRole.MEDIATOR)
    actor.require_step_up()
    c = await _case(session, case_id, lock=True)
    if c.status != "MEDIATION":
        raise Conflict("Mediators are assigned in mediation", code="NOT_IN_MEDIATION")
    who = await identity_facade.get_identity(session, body.mediatorIdentityId)
    if who is None:
        raise NotFound("Mediator not found")
    if await _party_of(session, Actor(identity_id=who.id, session_id=None, email=who.email), c.organization_id, c.professional_id):
        raise Forbidden("A party to the dispute cannot mediate it", code="CONFLICT_OF_INTEREST")
    if PlatformRole.MEDIATOR not in await identity_facade.live_platform_roles(session, who.id):
        raise ValidationFailed("Choose someone with the Mediator role and an active account", code="NOT_A_MEDIATOR")
    if c.pending_decision:
        raise Conflict("A platform decision is awaiting approval; the mediator cannot change now", code="DECISION_PENDING")
    c.mediator_identity_id = who.id
    _log(session, c, "MEDIATOR", "System", "A neutral mediator was assigned.")
    await session.flush()
    return await _out(session, actor, c, await _viewer(session, actor, c))


async def _require_mediator(session: AsyncSession, actor: Actor, c: DisputeCase) -> None:
    actor.require_platform_role(PlatformRole.MEDIATOR)
    if c.mediator_identity_id != actor.identity_id:
        raise Forbidden("Only the assigned mediator can do this")
    if c.status != "MEDIATION":
        raise Conflict("The case is not in mediation", code="NOT_IN_MEDIATION")
    if c.arbitration:
        raise Conflict("The case was referred to external arbitration; Legal records the award", code="REFERRED_TO_ARBITRATION")
    actor.require_step_up()


async def recommend(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: RecommendationIn) -> DisputeOut:
    c = await _case(session, case_id, lock=True)
    await _require_mediator(session, actor, c)
    allocations = await _allocations(session, c, body.outcome, body.allocations, body.extendDays)
    c.recommendation = {"outcome": body.outcome, "allocations": allocations, "summary": body.summary.strip(), "citations": body.citations,
                        "acceptedBy": [], "rejectedBy": [], "issuedAt": clock.now().isoformat()}
    _log(session, c, "RECOMMENDATION", "Mediator", f"Recommendation issued: {OUTCOME_LABEL[body.outcome]}. Binding only if both parties accept.")
    _evt(session, E.DISPUTE_RECOMMENDATION_ISSUED, c, outcome=body.outcome)
    # Mediation must not stall with the money frozen: a party who does not answer in time is treated as declining.
    answer_by = add_business_days(clock.now(), get_settings().dispute_direct_resolution_business_days)
    await schedule_timer(session, TIMER_RECOMMENDATION, f"{c.id}:{c.recommendation['issuedAt']}", answer_by,
                         {"disputeId": str(c.id), "issuedAt": c.recommendation["issuedAt"]})
    await session.flush()
    return await _out(session, actor, c, "MEDIATOR")


async def recommendation_lapsed(session: AsyncSession, payload: dict) -> None:
    """The answer window closed: whoever has not answered is treated as declining, so the mediator can propose a platform
    decision instead of the case (and the frozen money) waiting forever."""
    c = await _case(session, uuid.UUID(payload["disputeId"]), lock=True)
    r = dict(c.recommendation or {})
    if c.status != "MEDIATION" or r.get("issuedAt") != payload.get("issuedAt"):
        return  # decided, or a newer recommendation replaced this one
    silent = [p for p in ("BUYER", "PROFESSIONAL") if p not in r["acceptedBy"] and p not in r["rejectedBy"]]
    if not silent:
        return
    r["rejectedBy"] = [*r["rejectedBy"], *silent]
    c.recommendation = r
    _log(session, c, "RECOMMENDATION_LAPSED", "Zoikorum",
         f"No answer from the {' and '.join(p.lower() for p in silent)} in time: treated as declined. The mediator may propose a platform decision.")
    await session.flush()


async def answer_recommendation(session: AsyncSession, actor: Actor, case_id: uuid.UUID, accept: bool) -> DisputeOut:
    c = await _case(session, case_id, lock=True)
    party = await _require_party(session, actor, c)
    if c.status != "MEDIATION" or not c.recommendation:
        raise Conflict("There is no recommendation to answer", code="NO_RECOMMENDATION")
    r = dict(c.recommendation)
    if party in r["acceptedBy"] or party in r["rejectedBy"]:
        raise Conflict("You have already answered this recommendation", code="ALREADY_ANSWERED")
    if accept and party == "BUYER":
        await _require_buyer_authority(session, actor, c, _release(r["allocations"]))
    r["acceptedBy" if accept else "rejectedBy"] = [*r["acceptedBy" if accept else "rejectedBy"], party]
    c.recommendation = r
    _log(session, c, "RECOMMENDATION_ANSWER", await _actor_label(session, actor, party), "Accepted the recommendation." if accept
         else "Declined the recommendation. The mediator may propose a platform decision.")
    if set(r["acceptedBy"]) >= {"BUYER", "PROFESSIONAL"}:
        await _resolve(session, c, r["outcome"], r["allocations"], "MEDIATION", c.mediator_identity_id, r["summary"], r["citations"])
    await session.flush()
    return await _out(session, actor, c, party)


async def propose_decision(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: RecommendationIn) -> DisputeOut:
    c = await _case(session, case_id, lock=True)
    await _require_mediator(session, actor, c)
    if not c.recommendation or not c.recommendation.get("rejectedBy"):
        raise Conflict("A platform decision follows a recommendation that a party declined", code="RECOMMENDATION_FIRST")
    allocations = await _allocations(session, c, body.outcome, body.allocations, body.extendDays)
    c.pending_decision = {"outcome": body.outcome, "allocations": allocations, "summary": body.summary.strip(), "citations": body.citations,
                          "proposedBy": str(actor.identity_id), "proposedAt": clock.now().isoformat()}
    _log(session, c, "DECISION_PROPOSED", "Mediator", f"Platform decision proposed ({OUTCOME_LABEL[body.outcome]}); awaiting a second reviewer.")
    await session.flush()
    return await _out(session, actor, c, "MEDIATOR")


async def approve_decision(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> DisputeOut:
    """Second approver with the Legal role: no single person initiates and finalises a platform decision."""
    actor.require_platform_role(PlatformRole.LEGAL)
    actor.require_step_up()
    c = await _case(session, case_id, lock=True)
    if c.status != "MEDIATION" or not c.pending_decision:
        raise Conflict("There is no platform decision awaiting approval", code="NO_PENDING_DECISION")
    if c.pending_decision["proposedBy"] == str(actor.identity_id):
        raise Forbidden("The person who proposed a decision cannot also approve it", code="FOUR_EYES")
    if await _party_of(session, actor, c.organization_id, c.professional_id):
        raise Forbidden("A party to the dispute cannot approve its decision", code="CONFLICT_OF_INTEREST")
    d = c.pending_decision
    await _resolve(session, c, d["outcome"], d["allocations"], "PLATFORM", actor.identity_id, d["summary"], d["citations"])
    c.pending_decision = None
    await session.flush()
    return await _out(session, actor, c, await _viewer(session, actor, c))


# ---- Decision, enforcement, closure ---------------------------------------------------------------------------

async def _resolve(session: AsyncSession, c: DisputeCase, outcome: str, allocations: list[dict], path: str, decided_by: uuid.UUID | None,
                   summary: str, citations: list[str]) -> None:
    CASE_STATES.assert_can(c.status, "DECIDED")
    evidence = (await session.scalars(select(EvidenceItem.id).where(EvidenceItem.case_id == c.id))).all()
    released = sum(a["releaseMinor"] for a in allocations)
    refunded = sum(a["refundMinor"] for a in allocations)
    plain = summary or f"Outcome: {OUTCOME_LABEL[outcome]}."
    if released or refunded:
        plain += f" {_money(released, c.currency)} released to the professional, {_money(refunded, c.currency)} refunded to the buyer."
    c.status, c.decided_at = "DECIDED", clock.now()
    c.decision = {"plainSummary": plain, "outcome": outcome, "allocations": allocations, "decisionPath": path,
                  "decidedBy": str(decided_by) if decided_by else None, "evidenceReferences": [str(e) for e in evidence],
                  "policyCitations": citations or ["Zoikorum Dispute Resolution process", "Engagement agreement clauses 7-10"],
                  "appealEligible": path == "PLATFORM", "appealNote": "Platform decisions may be appealed within 14 days for new material evidence or procedural error.",
                  "originalReviewers": [str(x) for x in (c.mediator_identity_id, decided_by) if x]}
    await cancel_timer(session, TIMER_EVIDENCE, str(c.id))
    await cancel_timer(session, TIMER_DIRECT, str(c.id))
    outcomes = {a["milestoneOutcome"] for a in allocations}
    _log(session, c, "DECIDED", {"DIRECT": "Both parties", "MEDIATION": "Both parties (mediated)", "PLATFORM": "Platform (two reviewers)",
                                 "ARBITRATION": "External arbitrator (recorded by Legal)"}[path],
         f"Decision issued: {plain}")
    _evt(session, E.DISPUTE_RESOLVED, c, outcome=outcome, decidedBy=decided_by, decisionPath=path, allocations=allocations,
         milestoneOutcome=outcomes.pop() if len(outcomes) == 1 else "MIXED", currency=c.currency)
    await _check_bad_faith(session, c, outcome)


async def resolution_executed(session: AsyncSession, payload: dict) -> None:
    """Consumer of ESCROW_RESOLUTION_EXECUTED: enforced, then closed and sealed."""
    c = await session.get(DisputeCase, uuid.UUID(str(payload["disputeId"])), with_for_update=True)
    if c is None or c.status != "DECIDED":
        return
    now = clock.now()
    c.status = "ENFORCED"
    _log(session, c, "EXECUTED", "System", f"Funds executed: {_money(int(payload.get('releasedMinor', 0)), c.currency)} released, "
         f"{_money(int(payload.get('refundedMinor', 0)), c.currency)} refunded.")
    _evt(session, E.DISPUTE_ENFORCED, c)
    CASE_STATES.assert_can("ENFORCED", "CLOSED")
    c.status, c.closed_at = "CLOSED", now
    await _set_retention(session, c)
    _log(session, c, "CLOSED", "System", f"Case closed and the record sealed. Kept until at least {c.retain_until:%d %b %Y} ({c.retention_basis}).")
    _evt(session, E.DISPUTE_CLOSED, c)


async def open_for_contract(session: AsyncSession, contract_id: uuid.UUID) -> list[DisputeCase]:
    return list((await session.scalars(select(DisputeCase).where(DisputeCase.contract_id == contract_id, DisputeCase.status.in_(OPEN)))).all())


def appeal_out(a: DisputeAppeal) -> dict:
    return {"id": str(a.id), "caseId": str(a.case_id), "grounds": a.grounds, "explanation": a.explanation,
            "evidence": [file_out(f).model_dump(mode="json") for f in a.evidence], "status": a.status,
            "reason": a.decision_reason, "remediation": a.remediation, "createdAt": a.created_at,
            "decidedAt": a.decided_at}


async def get_appeal(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> dict | None:
    c = await _case(session, case_id)
    await _viewer(session, actor, c)
    a = await session.scalar(select(DisputeAppeal).where(DisputeAppeal.case_id == case_id))
    return appeal_out(a) if a else None


async def file_appeal(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body) -> dict:
    c = await _case(session, case_id, lock=True)
    await _require_party(session, actor, c)
    if not c.decision or c.decision.get("decisionPath") != "PLATFORM" or not c.decided_at:
        raise Conflict("Only a platform decision can be appealed", code="APPEAL_INELIGIBLE")
    if clock.now() > c.decided_at + timedelta(days=14):
        raise Conflict("The appeal window has ended", code="APPEAL_WINDOW_ENDED")
    if await session.scalar(select(DisputeAppeal.id).where(DisputeAppeal.case_id == c.id)):
        raise Conflict("An appeal already exists for this decision", code="APPEAL_EXISTS")
    if body.grounds == "NEW_MATERIAL_EVIDENCE" and not body.evidence:
        raise ValidationFailed("Attach the new material evidence")
    evidence = store_uploads(f"dispute/{c.id}/appeal", body.evidence)
    a = DisputeAppeal(case_id=c.id, submitted_by=actor.identity_id, grounds=body.grounds,
                      explanation=body.explanation.strip(), evidence=evidence, created_at=clock.now())
    session.add(a)
    await session.flush()
    _evt(session, E.DISPUTE_APPEALED, c, appealId=a.id, grounds=a.grounds)
    _log(session, c, "APPEAL_FILED", "Party", "An independent review was requested. The original decision remains recorded.")
    return appeal_out(a)


async def decide_appeal(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body) -> dict:
    actor.require_platform_role(PlatformRole.LEGAL)
    actor.require_step_up()
    c = await _case(session, case_id, lock=True)
    if await _party_of(session, actor, c.organization_id, c.professional_id):
        raise Forbidden("A party cannot review the appeal", code="CONFLICT_OF_INTEREST")
    reviewers = set((c.decision or {}).get("originalReviewers", []))
    if c.mediator_identity_id:
        reviewers.add(str(c.mediator_identity_id))
    if (c.decision or {}).get("decidedBy"):
        reviewers.add(c.decision["decidedBy"])
    if str(actor.identity_id) in reviewers:
        raise Forbidden("The appeal requires a reviewer independent of the original decision", code="FOUR_EYES")
    a = await session.scalar(select(DisputeAppeal).where(DisputeAppeal.case_id == c.id).with_for_update())
    if a is None:
        raise NotFound("Appeal not found")
    if a.status != "PENDING":
        raise Conflict("This appeal has already been decided", code="APPEAL_DECIDED")
    if body.outcome == "UPHELD" and not body.remediation.strip():
        raise ValidationFailed("Explain the follow-up remedy for an upheld appeal")
    a.status, a.reviewed_by, a.decided_at = body.outcome, actor.identity_id, clock.now()
    a.decision_reason, a.remediation = body.reason.strip(), body.remediation.strip() or None
    _evt(session, E.DISPUTE_APPEAL_DECIDED, c, appealId=a.id, appealOutcome=a.status)
    record_audit(session, "dispute.appeal.decided", object_type="DisputeAppeal", object_id=a.id,
                 tenant_id=c.organization_id, details={"outcome": a.status, "reason": a.decision_reason, "remediation": a.remediation})
    _log(session, c, "APPEAL_DECIDED", "Independent reviewer", f"Appeal {a.status.lower()}: {a.decision_reason}")
    return appeal_out(a)


async def appeal_file(session: AsyncSession, actor: Actor, case_id: uuid.UUID, sha256: str):
    c = await _case(session, case_id)
    await _viewer(session, actor, c)
    a = await session.scalar(select(DisputeAppeal).where(DisputeAppeal.case_id == c.id))
    if a is None:
        raise NotFound("Appeal not found")
    record_audit(session, "dispute.appeal.evidence.read", object_type="DisputeAppeal", object_id=a.id,
                 tenant_id=c.organization_id, details={"sha256": sha256})
    rec = find_file(a.evidence, sha256)
    return read_file(rec), rec.get("contentType"), rec["name"]


TIMER_MISSED_DEADLINE = "dispute.milestone_deadline"


async def automatic_case(session, contract_id, milestone_ids, category, trigger):
    from sqlalchemy import text
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"dispute:{contract_id}"})
    k = await contract_facade.get_contract(session, contract_id)
    if not k or k.status not in ("ACTIVE", "DISPUTED"):
        return
    occupied = {m for case in await open_for_contract(session, k.id) for m in case.milestone_ids}
    eligible = [m for m in k.milestones if m.id in milestone_ids and str(m.id) not in occupied and m.status in DISPUTABLE]
    if not eligible:
        return
    controls = await contract_facade.policy_controls(session, k.id)
    c = DisputeCase(reference=f"ZK-DSP-{uuid.uuid4().hex[:8].upper()}", contract_id=k.id, contract_reference=k.reference,
                    organization_id=k.organization_id, professional_id=k.professional_id, milestone_ids=[str(m.id) for m in eligible],
                    category=category, summary=f"Policy-triggered review: {trigger}", desired_outcome="REWORK", context="Automatic intake only; evidence and human review determine the outcome.",
                    initiated_by=None, initiator_party="PLATFORM", currency=k.currency, disputed_minor=sum(m.amount_minor for m in eligible),
                    evidence_deadline=clock.now() + timedelta(days=controls.get("disputeEvidenceDays", get_settings().dispute_evidence_days)), evidence_complete=[])
    session.add(c); await session.flush()
    _log(session, c, "OPENED", "Platform policy", c.summary)
    _evt(session, E.DISPUTE_INITIATED, c, milestoneIds=c.milestone_ids, category=category, desiredOutcome="REWORK", initiatedBy=None, trigger=trigger)
    _evt(session, E.DISPUTE_EVIDENCE_WINDOW_OPENED, c, deadline=c.evidence_deadline)
    await schedule_timer(session, TIMER_EVIDENCE, str(c.id), c.evidence_deadline, {"disputeId": str(c.id)})


async def schedule_deadlines(session, payload):
    from datetime import datetime, time, timezone
    k = await contract_facade.get_contract(session, uuid.UUID(str(payload["contractId"])))
    if not k or not (await contract_facade.policy_controls(session, k.id)).get("autoDisputeMissedDeadline"):
        return
    for m in k.milestones:
        if m.due_date and m.status not in ("ACCEPTED", "CANCELLED"):
            due = datetime.combine(m.due_date + timedelta(days=1), time.min, timezone.utc)
            await schedule_timer(session, TIMER_MISSED_DEADLINE, f"{m.id}:{k.contract_version}:{payload.get('fundingId', 'activation')}", due,
                                 {"contractId": str(k.id), "milestoneId": str(m.id), "dueDate": str(m.due_date)})


async def missed_deadline(session, payload):
    k = await contract_facade.get_contract(session, uuid.UUID(payload["contractId"]))
    if not k or not (await contract_facade.policy_controls(session, k.id)).get("autoDisputeMissedDeadline"):
        return
    m = next((m for m in k.milestones if str(m.id) == payload["milestoneId"]), None)
    if not m or str(m.due_date) != payload["dueDate"] or not m.due_date or m.due_date >= clock.now().date() or m.status not in ("IN_PROGRESS", "REVISION_REQUESTED"):
        return
    await automatic_case(session, k.id, {m.id}, "TIMELINE_DELAY", "missed delivery deadline")


async def repeated_rejection(session, payload):
    cid = uuid.UUID(str(payload["contractId"]))
    threshold = (await contract_facade.policy_controls(session, cid)).get("autoDisputeRejectionCount")
    if threshold and int(payload.get("revisionCount", 0)) >= threshold:
        await automatic_case(session, cid, {uuid.UUID(str(payload["milestoneId"]))}, "QUALITY_ACCEPTANCE", "repeated deliverable rejection")


# Verification closes a check with these when the professional changed something themselves (verification/service.py).
SELF_INITIATED_CLOSURES = ("NAME_CHANGED", "WITHDRAWN", "DETAILS_CHANGED")


async def compliance_trigger(session, payload):
    if payload.get("subjectType") != "PROFESSIONAL":
        return
    if payload.get("action") and payload["action"] not in ("CREDENTIAL_ENFORCEMENT", "VERIFICATION_RESET", "ENGAGEMENT_SUSPENSION"):
        return
    if payload.get("reasonCode") in SELF_INITIATED_CLOSURES:
        return  # the professional changed their name, details or withdrew a credential: re-verify, not a breach
    pid = uuid.UUID(str(payload["subjectId"]))
    for cid in await contract_facade.active_contract_ids(session, pid):
        if (await contract_facade.policy_controls(session, cid)).get("autoDisputeComplianceFlag"):
            c = await contract_facade.get_contract(session, cid)
            await automatic_case(session, cid, {m.id for m in c.milestones}, "COMPLIANCE_BREACH", "confirmed compliance restriction")



# ---- Evidence from the engagement conversation, clarifications, cooldown --------------------------------------------

async def import_messages(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> DisputeOut:
    """Add the engagement's conversation as evidence: every message with its time, sender and content fingerprint, as a
    CSV file both sides and the mediator can open. The messages themselves stay unchanged in the thread."""
    import base64
    import csv
    import hashlib
    import io

    from zoikorum.domains.messaging import facade as messaging_facade
    from zoikorum.shared.uploads import UploadIn

    c = await _case(session, case_id, lock=True)
    party = await _require_party(session, actor, c)
    if c.status != "EVIDENCE_COLLECTION" or clock.now() > c.evidence_deadline:
        raise Conflict("The evidence window has closed", code="EVIDENCE_CLOSED")
    k = await _contract(session, c.contract_id)
    messages = (await messaging_facade.export_thread(session, "PROPOSAL_REQUEST", k.request_id)
                + await messaging_facade.export_thread(session, "CONTRACT", c.contract_id))
    if not messages:
        raise Conflict("There are no messages to add", code="NO_MESSAGES")
    people = await identity_facade.get_identities(session, [m.sender_identity_id for m in messages if m.sender_identity_id])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sent_at", "sender", "message", "content_sha256", "attachment_sha256s"])
    for m in messages:
        who = people[m.sender_identity_id].display_name if m.sender_identity_id in people else "Zoikorum"
        w.writerow([m.sent_at.isoformat(), who, m.body, m.content_hash, " ".join(m.attachment_hashes)])
    data = buf.getvalue().encode()
    upload = UploadIn(name=f"{c.reference}-conversation.csv", sha256=hashlib.sha256(data).hexdigest(), size=len(data),
                      contentType="text/csv", dataBase64=base64.b64encode(data).decode())
    item = EvidenceItem(case_id=c.id, party=party, submitted_by=actor.identity_id, evidence_type="COMMUNICATION",
                        description=f"Conversation record from Zoikorum messages ({len(messages)} messages, fingerprints included)",
                        items=store_uploads(f"disputes/{c.id}", [upload]))
    session.add(item)
    await session.flush()
    _log(session, c, "EVIDENCE", await _actor_label(session, actor, party),
         f"Conversation record added ({len(messages)} messages)", ref=f"evidence:{item.id}")
    _evt(session, E.DISPUTE_EVIDENCE_SUBMITTED, c, party=party, evidenceType="COMMUNICATION", files=1)
    await session.flush()
    return await _out(session, actor, c, party)


MAX_CLARIFICATIONS = 3


async def request_clarification(session: AsyncSession, actor: Actor, case_id: uuid.UUID, to: str, question: str) -> DisputeOut:
    """The mediator asks one side a focused question (limited, so a case does not drift). They answer with evidence."""
    c = await _case(session, case_id, lock=True)
    await _require_mediator(session, actor, c)
    if len(c.clarifications) >= MAX_CLARIFICATIONS:
        raise Conflict(f"At most {MAX_CLARIFICATIONS} clarification requests per dispute", code="TOO_MANY_CLARIFICATIONS")
    c.clarifications = [*c.clarifications, {"to": to, "question": question.strip(), "at": clock.now().isoformat()}]
    _log(session, c, "CLARIFICATION", "Mediator", f"Asked the {to.lower()}: {question.strip()}")
    _evt(session, E.DISPUTE_CLARIFICATION_REQUESTED, c, audience=to, question=question.strip(),
         message=f"The mediator asks: {question.strip()} Answer by adding evidence to the dispute.")
    await session.flush()
    return await _out(session, actor, c, "MEDIATOR")


COOLDOWN = timedelta(hours=24)


async def cooldown(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> DisputeOut:
    """Once per dispute, either side may pause the current deadline for 24 hours (Dispute resolution: cooling-off)."""
    c = await _case(session, case_id, lock=True)
    party = await _require_party(session, actor, c)
    if party in c.cooldown_used_by:
        raise Conflict("You have already used your 24-hour pause in this dispute", code="COOLDOWN_USED")
    if c.status == "EVIDENCE_COLLECTION":
        c.evidence_deadline = c.evidence_deadline + COOLDOWN
        await schedule_timer(session, TIMER_EVIDENCE, str(c.id), c.evidence_deadline, {"disputeId": str(c.id)})
    elif c.status == "DIRECT_RESOLUTION" and c.direct_deadline:
        c.direct_deadline = c.direct_deadline + COOLDOWN
        await schedule_timer(session, TIMER_DIRECT, str(c.id), c.direct_deadline, {"disputeId": str(c.id)})
    else:
        raise Conflict("A pause is possible during evidence or direct resolution only", code="COOLDOWN_NOT_AVAILABLE")
    c.cooldown_used_by = [*c.cooldown_used_by, party]
    _log(session, c, "COOLDOWN", await _actor_label(session, actor, party), "Paused the current deadline for 24 hours.")
    await session.flush()
    return await _out(session, actor, c, party)



# ---- Bad-faith pattern (Dispute resolution: bad-faith disputes) --------------------------------------------------

LOST = {"BUYER": {"FULL_RELEASE"}, "PROFESSIONAL": {"FULL_REFUND", "TERMINATION"}}
PATTERN_WINDOW = timedelta(days=90)
PATTERN_COUNT = 3


async def _check_bad_faith(session: AsyncSession, c: DisputeCase, outcome: str) -> None:
    """Someone who keeps opening disputes that are decided entirely against them is flagged to Trust & Safety as an
    advisory signal (Level 0): a person reviews it; nothing is restricted automatically."""
    if c.initiated_by is None or outcome not in LOST.get(c.initiator_party, set()):
        return
    since = clock.now() - PATTERN_WINDOW
    lost = 0
    for other in (await session.scalars(select(DisputeCase).where(
            DisputeCase.initiated_by == c.initiated_by, DisputeCase.decided_at >= since))).all():
        decided = (other.decision or {}).get("outcome")
        if decided in LOST.get(other.initiator_party, set()):
            lost += 1
    if lost >= PATTERN_COUNT:
        record_event(session, E.DISPUTE_PATTERN_FLAGGED, aggregate_type="DisputeCase", aggregate_id=c.id,
                     payload={"subjectType": "IDENTITY", "subjectId": c.initiated_by, "disputesLost": lost,
                              "reasonCode": f"DISPUTES_DECIDED_AGAINST_INITIATOR_{lost}_IN_90_DAYS", "audience": "STAFF"})


# ---- Case record export (Dispute resolution: exportable record for regulators, courts, auditors) -----------------

async def case_record(session: AsyncSession, actor: Actor, case_id: uuid.UUID, fmt: str) -> tuple[bytes, str, str]:
    """Everything about one dispute in one attested file: metadata, timeline, evidence (with file fingerprints),
    proposals, recommendation, decision, appeal and the dispute conversation. Its SHA-256 is recorded with the download."""
    import hashlib
    import json

    from zoikorum.domains.messaging import facade as messaging_facade
    from zoikorum.shared import pdf

    c = await _case(session, case_id)
    viewer = await _viewer(session, actor, c)
    out = await _out(session, actor, c, viewer)
    appeal = await session.scalar(select(DisputeAppeal).where(DisputeAppeal.case_id == c.id))
    messages = await messaging_facade.export_thread(session, "DISPUTE", c.id)
    record = {
        "case": {"reference": c.reference, "engagement": c.contract_reference, "category": c.category, "status": c.status,
                 "summary": c.summary, "desiredOutcome": c.desired_outcome, "initiator": c.initiator_party,
                 "disputed": {"amountMinor": c.disputed_minor, "currency": c.currency}, "openedAt": c.created_at.isoformat(),
                 "decidedAt": c.decided_at.isoformat() if c.decided_at else None},
        "timeline": [{"at": t.at.isoformat(), "by": t.actor, "what": t.text, "ref": t.ref} for t in out.timeline],
        "evidence": [{"party": e.party, "type": e.evidenceType, "description": e.description,
                      "files": [{"name": f.name, "sha256": f.sha256} for f in e.items], "at": e.submittedAt.isoformat()}
                     for e in out.evidence],
        "proposals": [{"party": p.party, "outcome": p.outcome, "status": p.status, "note": p.note} for p in out.proposals],
        "recommendation": c.recommendation, "decision": c.decision,
        "appeal": {"grounds": appeal.grounds, "status": appeal.status, "decisionReason": appeal.decision_reason} if appeal else None,
        "messages": [{"at": m.sent_at.isoformat(), "contentSha256": m.content_hash, "body": m.body} for m in messages],
    }
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    fingerprint = hashlib.sha256(body.encode()).hexdigest()
    record_audit(session, "dispute.record.downloaded", object_type="DisputeCase", object_id=c.id, tenant_id=c.organization_id,
                 evidence_hash=fingerprint, details={"format": fmt})
    name = f"{c.reference}-record"
    if fmt == "json":
        return json.dumps({"fingerprintSha256": fingerprint, "record": record}, indent=2, default=str).encode(), f"{name}.json", "application/json"
    decision = c.decision or {}
    doc = pdf.PdfDocument(
        title="Dispute record", reference=c.reference, issued=clock.now(), fingerprint=fingerprint,
        subtitle=f"Engagement {c.contract_reference} · {c.category.replace('_', ' ').lower()} · {c.status.replace('_', ' ').lower()}",
        sections=[
            pdf.Section("The dispute", rows=[("Opened by", c.initiator_party.title()), ("Summary", c.summary),
                                             ("Desired outcome", OUTCOME_LABEL.get(c.desired_outcome, c.desired_outcome)),
                                             ("Money frozen", _money(c.disputed_minor, c.currency))]),
            pdf.Section("Decision", rows=[("Outcome", OUTCOME_LABEL.get(decision.get("outcome", ""), "Not decided yet")),
                                          ("How", decision.get("decisionPath", "—")), ("Reasoning", decision.get("plainSummary", "—"))]),
            pdf.Section("Evidence", rows=[(f"{e['party'].title()} · {e['type'].replace('_', ' ').lower()}",
                                           e["description"] + "".join(f" [{f['name']} {f['sha256'][:12]}…]" for f in e["files"]))
                                          for e in record["evidence"]] or [("None", "")]),
            pdf.Section("Timeline", rows=[(t["at"][:19].replace("T", " "), f"{t['by']}: {t['what']}") for t in record["timeline"]]),
            pdf.Section("Dispute conversation", rows=[(m["at"][:19].replace("T", " "), m["body"][:300]) for m in record["messages"]]
                        or [("No messages", "")]),
            pdf.Section(text="Attestation: produced by Zoikorum from its records. Timeline and evidence are append-only; files are "
                             "identified by SHA-256. The fingerprint below is the SHA-256 of this record and is stored with the download."),
        ])
    return pdf.render(doc), f"{name}.pdf", "application/pdf"



# ---- Enterprise dispute controls and external arbitration (Dispute resolution: enterprise controls) ----------------

async def _rules(session: AsyncSession, c: DisputeCase) -> policy_facade.ProfileSettings:
    """The buyer organisation's effective policy (platform defaults when it has none)."""
    return await policy_facade.get_settings_for_org(session, c.organization_id)


async def _mediation_required(session: AsyncSession, c: DisputeCase, rules=None) -> bool:
    rules = rules or await _rules(session, c)
    return rules.dispute_mediation_above_minor is not None and c.disputed_minor > rules.dispute_mediation_above_minor


async def refer_to_arbitration(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: ArbitrationReferIn) -> DisputeOut:
    """The assigned mediator refers a case the platform should not decide (size, legal complexity, a clause naming a forum)
    to an outside arbitrator. The money stays frozen; nothing moves until Legal records the award."""
    c = await _case(session, case_id, lock=True)
    await _require_mediator(session, actor, c)
    if c.pending_decision:
        raise Conflict("A platform decision is awaiting approval; withdraw it first", code="DECISION_PENDING")
    c.arbitration = {"forum": body.forum.strip(), "reason": body.reason.strip(), "referredAt": clock.now().isoformat(),
                     "referredBy": str(actor.identity_id)}
    await cancel_timer(session, TIMER_RECOMMENDATION, f"{c.id}:{(c.recommendation or {}).get('issuedAt')}")
    _log(session, c, "ARBITRATION_REFERRED", "Mediator", f"Referred to external arbitration ({c.arbitration['forum']}). "
         "The money stays frozen until the award is recorded.")
    _evt(session, E.DISPUTE_REFERRED_TO_ARBITRATION, c, forum=c.arbitration["forum"])
    record_audit(session, "dispute.arbitration.referred", object_type="DisputeCase", object_id=c.id, tenant_id=c.organization_id,
                 details={"forum": c.arbitration["forum"]})
    await session.flush()
    return await _out(session, actor, c, "MEDIATOR")


async def record_arbitration_award(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: ArbitrationAwardIn) -> DisputeOut:
    """Legal records the outside arbitrator's award; the platform then moves the money exactly as for any other decision."""
    actor.require_platform_role(PlatformRole.LEGAL)
    actor.require_step_up()
    c = await _case(session, case_id, lock=True)
    if c.status != "MEDIATION" or not c.arbitration:
        raise Conflict("This case is not waiting for an arbitration award", code="NOT_IN_ARBITRATION")
    if await _party_of(session, actor, c.organization_id, c.professional_id):
        raise Forbidden("A party to the dispute cannot record its award", code="CONFLICT_OF_INTEREST")
    allocations = await _allocations(session, c, body.outcome, body.allocations, body.extendDays)
    c.arbitration = {**c.arbitration, "awardReference": body.awardReference.strip(), "recordedAt": clock.now().isoformat(),
                     "recordedBy": str(actor.identity_id)}
    await _resolve(session, c, body.outcome, allocations, "ARBITRATION", actor.identity_id, body.summary.strip(),
                   [f"Arbitration award {body.awardReference.strip()} ({c.arbitration['forum']})", *body.citations])
    record_audit(session, "dispute.arbitration.award_recorded", object_type="DisputeCase", object_id=c.id, tenant_id=c.organization_id,
                 details={"awardReference": body.awardReference.strip(), "outcome": body.outcome})
    await session.flush()
    return await _out(session, actor, c, await _viewer(session, actor, c))



# ---- Retention (Dispute resolution: retention rules by policy and jurisdiction) -----------------------------------

# Minimum years records about a commercial dispute are kept, per country. STARTER VALUES pending confirmation by
# counsel; the platform default (ZK_DISPUTE_RETENTION_YEARS) applies wherever it is longer.
RETENTION_MINIMUM_YEARS = {"US": 7, "GB": 6, "IE": 6, "DE": 10, "FR": 10, "NL": 7, "ES": 6, "IT": 10, "IN": 8, "SG": 5,
                           "AE": 5, "AU": 7, "CA": 7}
TIMER_RETENTION = "dispute.retention_review"


async def _set_retention(session: AsyncSession, c: DisputeCase) -> None:
    """Keep the record for the longest of: the platform default, the buyer organisation's policy, and the minimum
    for the countries of both parties. When that date comes, Legal reviews it; nothing is deleted automatically."""
    from datetime import date as _date

    years = {"platform default": get_settings().dispute_retention_years}
    rules = await _rules(session, c)
    if rules.dispute_retention_years:
        years["organisation policy"] = rules.dispute_retention_years
    org = await buyer_facade.get_organization(session, c.organization_id)
    pro = await professional_facade.get_professional(session, c.professional_id)
    for country in {x for x in ((org.country if org else None), (pro.country if pro else None)) if x}:
        if country.upper() in RETENTION_MINIMUM_YEARS:
            years[f"law in {country.upper()}"] = RETENTION_MINIMUM_YEARS[country.upper()]
    basis, n = max(years.items(), key=lambda kv: kv[1])
    closed = (c.closed_at or clock.now()).date()
    try:
        until = closed.replace(year=closed.year + n)
    except ValueError:  # 29 February
        until = _date(closed.year + n, 3, 1)
    c.retain_until, c.retention_basis = until, f"{n} years: {basis}"
    from datetime import datetime as _dt, time as _time, timezone as _tz
    await schedule_timer(session, TIMER_RETENTION, str(c.id), _dt.combine(until, _time(6), tzinfo=_tz.utc), {"disputeId": str(c.id)})


async def retention_due(session: AsyncSession, payload: dict) -> None:
    """The retention period ended: flag the record for Legal to review (delete, keep, or anonymise). A legal hold
    keeps it out of review until the hold is lifted."""
    c = await session.get(DisputeCase, uuid.UUID(payload["disputeId"]), with_for_update=True)
    if c is None or c.legal_hold or c.retention_review_due:
        return
    c.retention_review_due = True
    record_event(session, E.DISPUTE_RETENTION_DUE, aggregate_type="DisputeCase", aggregate_id=c.id,
                 payload={"disputeId": c.id, "reference": c.reference, "audience": "STAFF"})


async def set_legal_hold(session: AsyncSession, actor: Actor, case_id: uuid.UUID, hold: bool, reason: str) -> DisputeOut:
    """Legal places or lifts a hold (litigation, a regulator's request): the record is kept regardless of its date."""
    actor.require_platform_role(PlatformRole.LEGAL)
    actor.require_step_up()
    c = await _case(session, case_id, lock=True)
    if c.legal_hold == hold:
        raise Conflict("The hold is already " + ("on" if hold else "off"), code="NO_CHANGE")
    c.legal_hold = hold
    if hold:
        c.retention_review_due = False
    elif c.retain_until and c.retain_until <= clock.now().date():
        c.retention_review_due = True
    record_audit(session, "dispute.legal_hold." + ("placed" if hold else "lifted"), object_type="DisputeCase", object_id=c.id,
                 tenant_id=c.organization_id, details={"reason": reason})
    await session.flush()
    return await _out(session, actor, c, await _viewer(session, actor, c))


async def retention_queue(session: AsyncSession, actor: Actor) -> list[dict]:
    """Legal: closed records whose retention period has ended, and records on hold."""
    actor.require_platform_role(PlatformRole.LEGAL, PlatformRole.PLATFORM_ADMIN)
    rows = (await session.scalars(select(DisputeCase).where(or_(DisputeCase.retention_review_due.is_(True), DisputeCase.legal_hold.is_(True)))
                                  .order_by(DisputeCase.retain_until))).all()
    return [{"id": c.id, "reference": c.reference, "closedAt": c.closed_at, "retainUntil": c.retain_until, "basis": c.retention_basis,
             "legalHold": c.legal_hold, "reviewDue": c.retention_review_due} for c in rows]
