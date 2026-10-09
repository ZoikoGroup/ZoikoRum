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
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.dispute.models import DisputeAppeal, DisputeCase, EvidenceItem, ResolutionProposal, TimelineEntry
from zoikorum.domains.dispute.schemas import (
    AllocationIn, AllocationOut, AssignIn, DisputeIn, DisputeOut, EvidenceIn, EvidenceOut, MilestoneRef, ProposalOut,
    RecommendationIn, ResolutionIn, TimelineOut,
)
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
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


def _log(session: AsyncSession, c: DisputeCase, kind: str, actor: str, text: str) -> None:
    session.add(TimelineEntry(case_id=c.id, kind=kind, actor=actor, text=text[:500]))


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

async def _allocations(session: AsyncSession, c: DisputeCase, outcome: str, raw: list[AllocationIn]) -> list[dict]:
    """Validates a structured outcome. Money outcomes split each disputed milestone fully into release + refund."""
    k = await _contract(session, c.contract_id)
    ms = {m.id: m for m in k.milestones if str(m.id) in c.milestone_ids}
    if outcome in ("REWORK", "TIMELINE_EXTENSION"):
        if any(a.releaseMinor or a.refundMinor for a in raw):
            raise ValidationFailed("Rework and timeline extension keep the money held; do not split it", code="ALLOCATION_NOT_ALLOWED")
        mo = "REWORK" if outcome == "REWORK" else "EXTEND"
        return [{"milestoneId": str(mid), "releaseMinor": 0, "refundMinor": 0, "milestoneOutcome": mo} for mid in ms]
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
    return DisputeOut(
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
        timeline=[TimelineOut(kind=t.kind, actor=t.actor, text=t.text, at=t.created_at) for t in timeline],
        viewerRole=viewer, canEscalate=c.status == "DIRECT_RESOLUTION" and viewer in ("BUYER", "PROFESSIONAL")
        and any(p.status == "REJECTED" for p in proposals),
        nextStep=_next_step(c, viewer), createdAt=c.created_at,
    )


async def get_dispute(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> DisputeOut:
    c = await _case(session, case_id)
    return await _out(session, actor, c, await _viewer(session, actor, c))


async def list_disputes(session: AsyncSession, actor: Actor, role: str, contract_id: uuid.UUID | None) -> list[DisputeOut]:
    stmt = select(DisputeCase).order_by(DisputeCase.created_at.desc()).limit(100)
    if contract_id:
        stmt = stmt.where(DisputeCase.contract_id == contract_id)
    if role == "buyer":
        stmt = stmt.where(or_(DisputeCase.organization_id.in_(actor.org_ids), DisputeCase.initiated_by == actor.identity_id))
    elif role == "professional":
        pro = await professional_facade.get_professional_by_identity(session, actor.identity_id)
        if pro is None:
            return []
        stmt = stmt.where(DisputeCase.professional_id == pro.id)
    else:
        actor.require_platform_role(*OPERATORS)
    out = []
    for c in (await session.scalars(stmt)).all():
        try:
            out.append(await _out(session, actor, c, await _viewer(session, actor, c)))
        except NotFound:
            continue  # stale token org list: skip cases the caller cannot see
    return out


# ---- Intake ------------------------------------------------------------------------------------------------

async def open_dispute(session: AsyncSession, actor: Actor, body: DisputeIn) -> DisputeOut:
    from sqlalchemy import text
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"dispute:{body.contractId}"})
    k = await _contract(session, body.contractId)
    party = await _party_of(session, actor, k.organization_id, k.professional_id)
    if party is None:
        raise NotFound("Contract not found")
    if k.status not in ("ACTIVE", "DISPUTED"):
        raise Conflict("Only an active engagement can be disputed", code="CONTRACT_NOT_ACTIVE")
    ms = {m.id: m for m in k.milestones}
    wanted = set(body.milestoneIds)
    if not wanted <= set(ms):
        raise NotFound("Milestone not found on this contract")
    open_cases = (await session.scalars(select(DisputeCase).where(DisputeCase.contract_id == k.id, DisputeCase.status.in_(OPEN)))).all()
    if any(wanted & {uuid.UUID(m) for m in oc.milestone_ids} for oc in open_cases):
        raise Conflict("There is already an open dispute for this milestone; add evidence to it instead", code="DUPLICATE_DISPUTE")
    bad = [ms[i] for i in wanted if ms[i].status not in DISPUTABLE]
    if bad:
        raise Conflict(f"M{bad[0].sequence} cannot be disputed ({bad[0].status.replace('_', ' ').lower()}). Only funded milestones that are "
                       "not yet accepted can be disputed.", code="MILESTONE_NOT_DISPUTABLE")

    now = clock.now()
    c = DisputeCase(reference=f"ZK-DSP-{uuid.uuid4().hex[:8].upper()}", contract_id=k.id, contract_reference=k.reference or "—",
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
    session.add(EvidenceItem(case_id=c.id, party=party, submitted_by=actor.identity_id, evidence_type=body.evidenceType,
                             description=body.description.strip(), items=store_uploads(f"disputes/{c.id}", body.items)))
    _log(session, c, "EVIDENCE", await _actor_label(session, actor, party),
         f"Evidence added: {body.evidenceType.replace('_', ' ').lower()}" + (f" ({len(body.items)} file(s))" if body.items else ""))
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
    allocations = await _allocations(session, c, body.outcome, body.allocations)
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
    if not await session.scalar(select(ResolutionProposal.id).where(ResolutionProposal.case_id == c.id, ResolutionProposal.status == "REJECTED")):
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
    actor.require_step_up()


async def recommend(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: RecommendationIn) -> DisputeOut:
    c = await _case(session, case_id, lock=True)
    await _require_mediator(session, actor, c)
    allocations = await _allocations(session, c, body.outcome, body.allocations)
    c.recommendation = {"outcome": body.outcome, "allocations": allocations, "summary": body.summary.strip(), "citations": body.citations,
                        "acceptedBy": [], "rejectedBy": [], "issuedAt": clock.now().isoformat()}
    _log(session, c, "RECOMMENDATION", "Mediator", f"Recommendation issued: {OUTCOME_LABEL[body.outcome]}. Binding only if both parties accept.")
    _evt(session, E.DISPUTE_RECOMMENDATION_ISSUED, c, outcome=body.outcome)
    await session.flush()
    return await _out(session, actor, c, "MEDIATOR")


async def answer_recommendation(session: AsyncSession, actor: Actor, case_id: uuid.UUID, accept: bool) -> DisputeOut:
    c = await _case(session, case_id, lock=True)
    party = await _require_party(session, actor, c)
    if c.status != "MEDIATION" or not c.recommendation:
        raise Conflict("There is no recommendation to answer", code="NO_RECOMMENDATION")
    r = dict(c.recommendation)
    if party in r["acceptedBy"] or party in r["rejectedBy"]:
        raise Conflict("You have already answered this recommendation", code="ALREADY_ANSWERED")
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
    allocations = await _allocations(session, c, body.outcome, body.allocations)
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
    _log(session, c, "DECIDED", {"DIRECT": "Both parties", "MEDIATION": "Both parties (mediated)", "PLATFORM": "Platform (two reviewers)"}[path],
         f"Decision issued: {plain}")
    _evt(session, E.DISPUTE_RESOLVED, c, outcome=outcome, decidedBy=decided_by, decisionPath=path, allocations=allocations,
         milestoneOutcome=outcomes.pop() if len(outcomes) == 1 else "MIXED", currency=c.currency)


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
    _log(session, c, "CLOSED", "System", "Case closed and the record sealed.")
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


async def compliance_trigger(session, payload):
    if payload.get("subjectType") != "PROFESSIONAL":
        return
    if payload.get("action") and payload["action"] not in ("CREDENTIAL_ENFORCEMENT", "VERIFICATION_RESET", "ENGAGEMENT_SUSPENSION"):
        return
    pid = uuid.UUID(str(payload["subjectId"]))
    for cid in await contract_facade.active_contract_ids(session, pid):
        if (await contract_facade.policy_controls(session, cid)).get("autoDisputeComplianceFlag"):
            c = await contract_facade.get_contract(session, cid)
            await automatic_case(session, cid, {m.id for m in c.milestones}, "COMPLIANCE_BREACH", "confirmed compliance restriction")
