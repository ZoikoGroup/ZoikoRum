"""Contract domain (Step 7): agreement generated from the accepted proposal, buyer signs then professional countersigns,
milestones wait for funding, then deliver -> review -> accept (Request Proposal & Engagement Flow s.10-13, BUILD_SPEC).

Every signature needs a fresh two-step confirmation and is stored as an append-only receipt bound to the exact terms
hash the signer saw. Change orders and dispute hooks arrive in a follow-up step; policy-required clauses arrive with
the policy domain (platform template until then).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.contract.models import Contract, Milestone, Signature, Submission
from zoikorum.domains.contract.schemas import (
    ContractOut, ContractSummaryOut, FileRef, MilestoneOut, PartyOut, RevisionIn, SignatureOut, SignIn, SubmissionOut, SubmitIn,
)
from zoikorum.domains.firm import facade as firm_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, OrgRole, PlatformRole
from zoikorum.shared.errors import Conflict, Forbidden, NotFound
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.http import page_of, paginate
from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.relay import cancel_timer, schedule_timer
from zoikorum.shared.state_machine import StateMachine

CONTRACT_STATES = StateMachine("Contract", {
    "GENERATED": {"PENDING_SIGNATURE"},
    "PENDING_SIGNATURE": {"ACTIVE", "TERMINATED"},
    "ACTIVE": {"COMPLETED", "TERMINATED", "DISPUTED"},
    "DISPUTED": {"ACTIVE"},
    "COMPLETED": set(),
    "TERMINATED": set(),
})
MILESTONE_STATES = StateMachine("Milestone", {
    "PENDING_FUNDING": {"IN_PROGRESS", "CANCELLED", "DISPUTED"},
    "IN_PROGRESS": {"SUBMITTED", "CANCELLED", "DISPUTED"},
    "SUBMITTED": {"REVISION_REQUESTED", "ACCEPTANCE_PENDING_APPROVAL", "ACCEPTED", "DISPUTED"},
    "REVISION_REQUESTED": {"IN_PROGRESS", "SUBMITTED", "DISPUTED"},
    "ACCEPTANCE_PENDING_APPROVAL": {"ACCEPTED", "REVISION_REQUESTED", "DISPUTED"},
    "DISPUTED": {"IN_PROGRESS", "ACCEPTED", "CANCELLED"},
    "ACCEPTED": set(),
    "CANCELLED": set(),
})
DECIDERS = (OrgRole.REQUESTER, OrgRole.APPROVER)
VIEWERS = (PlatformRole.PLATFORM_ADMIN, PlatformRole.COMPLIANCE_OFFICER, PlatformRole.LEGAL, PlatformRole.MEDIATOR)
TIMER_SIGNATURE = "contract.signature_deadline"
LABEL = {"ADVISORY": "Advisory", "PROJECT": "Project", "RETAINER": "Retainer", "FRACTIONAL": "Fractional",
         "HOURLY": "Hourly", "FIXED": "Fixed fee"}


def _hash(terms: dict) -> str:
    return hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _money(minor: int, currency: str) -> str:
    return f"{currency} {minor / 100:,.2f}"


def _evt(session: AsyncSession, event_type: str, c: Contract, **payload) -> None:
    record_event(session, event_type, aggregate_type="Contract", aggregate_id=c.id, tenant_id=c.organization_id,
                 payload={"contractId": c.id, "organizationId": c.organization_id, "professionalId": c.professional_id, **payload},
                 policy_version=c.policy_version_label)


def _milestone_list(ms: list[Milestone]) -> list[dict]:
    return [{"milestoneId": m.id, "sequence": m.sequence, "amountMinor": m.amount_minor, "title": m.title} for m in ms]


async def _contract(session: AsyncSession, contract_id: uuid.UUID, lock: bool = False) -> Contract:
    c = await session.get(Contract, contract_id, with_for_update=lock)
    if c is None:
        raise NotFound("Contract not found")
    return c


async def _milestones(session: AsyncSession, contract_id: uuid.UUID, lock: bool = False) -> list[Milestone]:
    stmt = select(Milestone).where(Milestone.contract_id == contract_id).order_by(Milestone.sequence)
    return list((await session.scalars(stmt.with_for_update() if lock else stmt)).all())


async def _viewer(session: AsyncSession, actor: Actor, c: Contract) -> str:
    if await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id):
        return "BUYER"
    pro = await professional_facade.get_professional(session, c.professional_id)
    if pro is not None and pro.identity_id == actor.identity_id:
        return "PROFESSIONAL"
    if actor.has_platform_role(*VIEWERS):
        actor.require_platform_role(*VIEWERS)
        return "OPERATOR"
    raise NotFound("Contract not found")


# ---- Generation ---------------------------------------------------------------------------

def render_document(c: Contract, milestones: list[Milestone]) -> str:
    """Plain-language agreement from the accepted terms and the platform template (Agreement Finalization s.10)."""
    t, p = c.terms, c.parties
    keys = {d["key"]: d["title"] for d in t.get("deliverables", [])}
    lines = [
        f"ENGAGEMENT AGREEMENT {c.reference} (version {c.contract_version})",
        "",
        "1. PARTIES",
        f"Buyer: {p['buyer']['name']}, represented by {p['buyer']['signatory']}.",
        f"Professional: {p['professional']['name']}" + (f", practising with {p['professional']['firm']}" if p["professional"].get("firm") else "") + ".",
        "Zoikorum provides the marketplace, verification, contracting and payment-protection infrastructure. It is not a party "
        "to the professional services and does not guarantee outcomes.",
        "",
        "2. ENGAGEMENT",
        f"Service: {c.title}. Type: {LABEL.get(c.engagement_type, c.engagement_type)}."
        + (f" Pricing: {LABEL.get(c.pricing_model or '', c.pricing_model)}." if c.pricing_model else ""),
        f"Objective: {t.get('objective', '')}",
        f"Start: {t.get('startDate') or 'on activation'}. Target completion: {t.get('endDate') or 'per milestones'}.",
        "",
        "3. SCOPE AND DELIVERABLES",
        t.get("scope") or "As described in the deliverables below.",
    ]
    for i, d in enumerate(t.get("deliverables", []), 1):
        lines.append(f"  3.{i} {d['title']}. Acceptance criteria: {d['acceptanceCriteria']}")
    lines += ["", "4. MILESTONES AND PAYMENT SCHEDULE"]
    for m in milestones:
        delivers = ", ".join(keys.get(k, k) for k in m.deliverable_keys)
        lines.append(f"  M{m.sequence}. {m.title}: {_money(m.amount_minor, m.currency)}"
                     + (f", due {m.due_date.isoformat()}" if m.due_date else "") + (f". Delivers: {delivers}" if delivers else ""))
    lines.append(f"  Total: {_money(c.total_minor, c.currency)}.")
    if t.get("assumptions"):
        lines += ["", "5. ASSUMPTIONS"] + [f"  - {a}" for a in t["assumptions"]]
    if t.get("exclusions"):
        lines += ["", "6. EXCLUSIONS (OUT OF SCOPE)"] + [f"  - {x}" for x in t["exclusions"]]
    window = get_settings().acceptance_window_days
    lines += [
        "",
        "7. PAYMENT PROTECTION",
        "Each milestone is funded into escrow before work on it starts. Funds are released to the professional only after the "
        "buyer accepts the milestone. No work is required on an unfunded milestone.",
        "",
        "8. DELIVERY AND ACCEPTANCE",
        f"The professional submits each milestone for review. The buyer reviews against the acceptance criteria within {window} days "
        "and either accepts or requests a revision with reasons.",
        "",
        "9. CHANGES",
        "Scope, price or timeline changes require a change order accepted by both parties. Each accepted change creates a new "
        "contract version; changes to scope or price must be signed again.",
        "",
        "10. DISPUTES",
        "Either party may open a dispute through Zoikorum. Funds for the affected milestone are held until the dispute is resolved "
        "through the platform's dispute resolution process.",
    ]
    if c.nda_required:
        lines += ["", "11. CONFIDENTIALITY",
                  "The professional keeps the buyer's confidential information confidential and uses it only for this engagement, "
                  "as accepted before the proposal was written."]
    lines += ["", "STANDARD TERMS",
              "The Zoikorum Terms of Service apply to this agreement. Governing law and jurisdiction follow those terms unless an "
              "enterprise policy profile sets them.",
              "", f"Terms reference (SHA-256): {c.terms_hash}", f"Policy: {c.policy_version_label}"]
    return "\n".join(lines)


async def generate_from_proposal(session: AsyncSession, payload: dict) -> None:
    """Consumer of PROPOSAL_ACCEPTED. Idempotent per proposal."""
    proposal_id = uuid.UUID(str(payload["proposalId"]))
    if await session.scalar(select(Contract.id).where(Contract.proposal_id == proposal_id)):
        return
    terms = payload["terms"]
    if _hash(terms) != payload["termsHash"]:
        raise ValueError(f"Terms hash mismatch for proposal {proposal_id}")  # never generate from altered terms
    org_id, buyer_id = uuid.UUID(str(payload["organizationId"])), uuid.UUID(str(payload["buyerIdentityId"]))
    pro_id = uuid.UUID(str(payload["professionalId"]))
    org = await buyer_facade.get_organization(session, org_id)
    buyer = await identity_facade.get_identity(session, buyer_id)
    pro = await professional_facade.get_professional(session, pro_id)
    firm = await firm_facade.get_firm(session, pro.firm_id) if pro and pro.firm_id else None
    now = clock.now()
    c = Contract(
        reference=f"ZK-ENG-{uuid.uuid4().hex[:8].upper()}", proposal_id=proposal_id, request_id=uuid.UUID(str(payload["requestId"])),
        organization_id=org_id, buyer_identity_id=buyer_id, professional_id=pro_id, firm_id=firm.id if firm else None,
        title=payload.get("service") or "Professional engagement", engagement_type=payload.get("engagementType") or "PROJECT",
        pricing_model=payload.get("pricingModel"), status="PENDING_SIGNATURE", currency=payload["currency"],
        total_minor=int(payload["totalMinor"]), terms=terms, terms_hash=payload["termsHash"],
        parties={"buyer": {"name": org.name if org else "Buyer", "signatory": buyer.display_name if buyer else "Buyer",
                           "country": org.country if org else None},
                 "professional": {"name": pro.display_name if pro else "Professional",
                                  "firm": (firm.trading_name or firm.legal_name) if firm else None,
                                  "country": pro.country if pro else None}},
        nda_required=bool(payload.get("ndaRequired")), document="", document_sha256="",
        policy_version_label=payload.get("policyVersionLabel") or "platform-default@1",
        signature_deadline=now + timedelta(days=get_settings().signature_deadline_days),
    )
    session.add(c)
    await session.flush()
    milestones = [Milestone(contract_id=c.id, sequence=m["sequence"], title=m["title"], description=m.get("description") or "",
                            amount_minor=int(m["amountMinor"]), currency=c.currency,
                            due_date=date.fromisoformat(m["dueDate"]) if m.get("dueDate") else None,
                            deliverable_keys=m.get("deliverableKeys") or [], status="PENDING_FUNDING")
                  for m in terms.get("milestones", [])]
    session.add_all(milestones)
    await session.flush()
    c.document = render_document(c, milestones)
    c.document_sha256 = hashlib.sha256(c.document.encode()).hexdigest()
    _evt(session, E.CONTRACT_GENERATED, c, proposalId=proposal_id, buyerIdentityId=buyer_id, totalMinor=c.total_minor,
         currency=c.currency, termsHash=c.terms_hash, signatureDeadline=c.signature_deadline)
    for m in milestones:
        _evt(session, E.MILESTONE_CREATED, c, milestoneId=m.id, sequence=m.sequence, amountMinor=m.amount_minor, currency=m.currency)
    await schedule_timer(session, TIMER_SIGNATURE, str(c.id), c.signature_deadline, {"contractId": str(c.id)})


async def signature_deadline_passed(session: AsyncSession, payload: dict) -> None:
    c = await session.get(Contract, uuid.UUID(payload["contractId"]))
    if c is None or c.status != "PENDING_SIGNATURE":
        return
    signed = set((await session.scalars(select(Signature.party).where(
        Signature.contract_id == c.id, Signature.contract_version == c.contract_version))).all())
    _evt(session, E.SIGNATURE_DEADLINE_ESCALATED, c, waitingFor=sorted({"BUYER", "PROFESSIONAL"} - signed))


# ---- Reads ------------------------------------------------------------------------------------

def _next_action(c: Contract, ms: list[Milestone], signed: set[str], viewer: str, pro_name: str) -> str:
    if c.status == "PENDING_SIGNATURE":
        if "BUYER" not in signed:
            return "Review and sign the contract" if viewer == "BUYER" else "Waiting for the buyer to sign"
        return f"Waiting for {pro_name} to countersign" if viewer == "BUYER" else "Countersign the contract"
    if c.status == "COMPLETED":
        return "Completed — all milestones accepted"
    if c.status != "ACTIVE":
        return c.status.replace("_", " ").capitalize()
    by = {s: [m for m in ms if m.status == s] for s in ("SUBMITTED", "REVISION_REQUESTED", "IN_PROGRESS", "PENDING_FUNDING")}
    if by["SUBMITTED"]:
        m = by["SUBMITTED"][0]
        return f"Review submitted work: M{m.sequence} {m.title}" if viewer == "BUYER" else f"Waiting for review of M{m.sequence}"
    if by["REVISION_REQUESTED"]:
        m = by["REVISION_REQUESTED"][0]
        return f"Revise and resubmit M{m.sequence} {m.title}" if viewer == "PROFESSIONAL" else f"Waiting for the revised M{m.sequence}"
    if by["IN_PROGRESS"]:
        m = by["IN_PROGRESS"][0]
        return f"Deliver M{m.sequence} {m.title}" if viewer == "PROFESSIONAL" else f"Work in progress on M{m.sequence}"
    if by["PENDING_FUNDING"]:
        m = by["PENDING_FUNDING"][0]
        return (f"Fund M{m.sequence} to start work (payment protection opens in the next release)" if viewer == "BUYER"
                else f"Waiting for the buyer to fund M{m.sequence}")
    return "In progress"


async def _out(session: AsyncSession, actor: Actor, c: Contract, viewer: str) -> ContractOut:
    ms = await _milestones(session, c.id)
    sigs = list((await session.scalars(select(Signature).where(Signature.contract_id == c.id).order_by(Signature.signed_at))).all())
    subs = list((await session.scalars(select(Submission).where(Submission.milestone_id.in_([m.id for m in ms]))
                                       .order_by(Submission.created_at.desc()))).all()) if ms else []
    signed = {s.party for s in sigs if s.contract_version == c.contract_version}
    can_sign = False
    if c.status == "PENDING_SIGNATURE":
        if viewer == "BUYER" and "BUYER" not in signed:
            can_sign = bool((await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id)).intersection(DECIDERS))
        elif viewer == "PROFESSIONAL":
            can_sign = "BUYER" in signed and "PROFESSIONAL" not in signed
    p = c.parties
    firm_line = f"Practising with {p['professional']['firm']}" if p["professional"].get("firm") else "Independent professional"
    accepted = sum(m.amount_minor for m in ms if m.status == "ACCEPTED")
    return ContractOut(
        id=c.id, reference=c.reference, proposalId=c.proposal_id, requestId=c.request_id, organizationId=c.organization_id,
        professionalId=c.professional_id, title=c.title, engagementType=c.engagement_type, pricingModel=c.pricing_model,
        status=c.status, total=MoneyDTO(amountMinor=c.total_minor, currency=c.currency), termsHash=c.terms_hash,
        contractVersion=c.contract_version,
        parties=[PartyOut(role="BUYER", name=p["buyer"]["name"], detail=f"Signatory: {p['buyer']['signatory']}"),
                 PartyOut(role="PROFESSIONAL", name=p["professional"]["name"], detail=firm_line)],
        terms=c.terms, ndaRequired=c.nda_required, documentSha256=c.document_sha256, policyVersionLabel=c.policy_version_label,
        signatureDeadline=c.signature_deadline, activatedAt=c.activated_at, completedAt=c.completed_at,
        signatures=[SignatureOut(party=s.party, signerName=s.signer_name, contractVersion=s.contract_version, termsHash=s.terms_hash,
                                 authStrength=s.auth_strength, signedAt=s.signed_at) for s in sigs],
        milestones=[MilestoneOut(
            id=m.id, sequence=m.sequence, title=m.title, description=m.description,
            amount=MoneyDTO(amountMinor=m.amount_minor, currency=m.currency), dueDate=m.due_date, deliverableKeys=m.deliverable_keys,
            status=m.status, startedAt=m.started_at, submittedAt=m.submitted_at, acceptanceDueAt=m.acceptance_due_at,
            acceptedAt=m.accepted_at, revisionCount=m.revision_count, lastRevisionReason=m.last_revision_reason,
            submissions=[SubmissionOut(id=s.id, note=s.note, files=[FileRef(**f) for f in s.files], submittedAt=s.created_at)
                         for s in subs if s.milestone_id == m.id],
        ) for m in ms],
        viewerRole=viewer, nextAction=_next_action(c, ms, signed, viewer, p["professional"]["name"]), canSign=can_sign,
        acceptedAmount=MoneyDTO(amountMinor=accepted, currency=c.currency), createdAt=c.created_at, version=c.version,
    )


async def get_contract(session: AsyncSession, actor: Actor, contract_id: uuid.UUID) -> ContractOut:
    c = await _contract(session, contract_id)
    return await _out(session, actor, c, await _viewer(session, actor, c))


async def get_document(session: AsyncSession, actor: Actor, contract_id: uuid.UUID) -> tuple[str, str]:
    c = await _contract(session, contract_id)
    await _viewer(session, actor, c)
    record_audit(session, "contract.document.viewed", object_type="Contract", object_id=c.id, tenant_id=c.organization_id,
                 evidence_hash=c.document_sha256, details={"version": c.contract_version})
    return c.document, c.document_sha256


async def _scope(session: AsyncSession, actor: Actor, role: str):
    if role == "buyer":
        return or_(Contract.organization_id.in_(actor.org_ids), Contract.buyer_identity_id == actor.identity_id)
    pro = await professional_facade.get_professional_by_identity(session, actor.identity_id)
    return Contract.professional_id == pro.id if pro else None


async def list_contracts(session: AsyncSession, actor: Actor, role: str, status: str | None, cursor: str | None, limit: int | None) -> dict:
    where = await _scope(session, actor, role)
    if where is None:
        return {"items": [], "nextCursor": None}
    stmt = select(Contract).where(where)
    if status:
        stmt = stmt.where(Contract.status.in_([s.strip().upper() for s in status.split(",") if s.strip()]))
    stmt, lim = paginate(stmt, Contract, cursor, limit)
    rows = list((await session.scalars(stmt)).all())
    viewer = "BUYER" if role == "buyer" else "PROFESSIONAL"
    items = {c.id: await _out(session, actor, c, viewer) for c in rows[:lim]}
    return page_of(rows, lim, lambda c: items[c.id])


async def summary(session: AsyncSession, actor: Actor, role: str) -> ContractSummaryOut:
    where = await _scope(session, actor, role)
    if where is None:
        return ContractSummaryOut(role=role, contracts={}, milestones={})
    contracts = dict((await session.execute(select(Contract.status, func.count()).where(where).group_by(Contract.status))).all())
    milestones = dict((await session.execute(select(Milestone.status, func.count()).join(Contract, Contract.id == Milestone.contract_id)
                                             .where(where, Contract.status != "TERMINATED").group_by(Milestone.status))).all())
    return ContractSummaryOut(role=role, contracts=contracts, milestones=milestones)


# ---- Signing ------------------------------------------------------------------------------------

async def sign(session: AsyncSession, actor: Actor, contract_id: uuid.UUID, body: SignIn, ip: str | None) -> ContractOut:
    c = await _contract(session, contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    if viewer == "OPERATOR":
        raise Forbidden("Only the parties sign a contract")
    if c.status != "PENDING_SIGNATURE":
        raise Conflict("This contract is not waiting for a signature", code="NOT_AWAITING_SIGNATURE")
    if body.termsHash != c.terms_hash:
        raise Conflict("The contract changed since you opened it; review the latest version", code="TERMS_CHANGED")
    signed = set((await session.scalars(select(Signature.party).where(
        Signature.contract_id == c.id, Signature.contract_version == c.contract_version))).all())
    if viewer == "BUYER":
        roles = await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id)
        if not roles.intersection(DECIDERS):
            raise Forbidden("Signing needs the Requester or Approver role in your organisation", code="ROLE_REQUIRED")
        if "BUYER" in signed:
            raise Conflict("Your organisation has already signed this contract", code="ALREADY_SIGNED")
    else:
        if "BUYER" not in signed:
            raise Conflict("The buyer signs first; you countersign after them", code="BUYER_SIGNS_FIRST")
        if "PROFESSIONAL" in signed:
            raise Conflict("You have already signed this contract", code="ALREADY_SIGNED")
    actor.require_step_up()

    who = await identity_facade.get_identity(session, actor.identity_id)
    now = clock.now()
    session.add(Signature(contract_id=c.id, contract_version=c.contract_version, party=viewer, signer_identity_id=actor.identity_id,
                          signer_name=who.display_name if who else "Signer", terms_hash=c.terms_hash,
                          auth_strength=actor.auth_strength, ip=ip, signed_at=now))
    _evt(session, E.CONTRACT_SIGNED, c, signerIdentityId=actor.identity_id, party=viewer, termsHash=c.terms_hash)
    if signed | {viewer} == {"BUYER", "PROFESSIONAL"}:
        CONTRACT_STATES.assert_can(c.status, "ACTIVE")
        c.status, c.activated_at = "ACTIVE", now
        await cancel_timer(session, TIMER_SIGNATURE, str(c.id))
        _evt(session, E.CONTRACT_ACTIVATED, c, buyerIdentityId=c.buyer_identity_id, currency=c.currency, totalMinor=c.total_minor,
             policyVersionId=None, milestones=_milestone_list(await _milestones(session, c.id)))
    await session.flush()
    return await _out(session, actor, c, viewer)


# ---- Milestones -----------------------------------------------------------------------------------

async def _milestone_ctx(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID) -> tuple[Milestone, Contract, str]:
    m = await session.get(Milestone, milestone_id, with_for_update=True)
    if m is None:
        raise NotFound("Milestone not found")
    c = await _contract(session, m.contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    if c.status != "ACTIVE":
        raise Conflict("The contract is not active", code="CONTRACT_NOT_ACTIVE")
    return m, c, viewer


async def escrow_funded(session: AsyncSession, payload: dict) -> None:
    """Consumer of ESCROW_FUNDED: funded milestones start (no work without funding). Idempotent."""
    c = await session.get(Contract, uuid.UUID(str(payload["contractId"])), with_for_update=True)
    if c is None or c.status != "ACTIVE":
        return
    ids = {uuid.UUID(str(i)) for i in payload.get("milestoneIds", [])}
    for m in await _milestones(session, c.id, lock=True):
        if m.id in ids and m.status == "PENDING_FUNDING":
            MILESTONE_STATES.assert_can(m.status, "IN_PROGRESS")
            m.status, m.started_at = "IN_PROGRESS", clock.now()
            _evt(session, E.MILESTONE_STARTED, c, milestoneId=m.id)


async def submit_milestone(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, body: SubmitIn) -> ContractOut:
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    if viewer != "PROFESSIONAL":
        raise Forbidden("Only the professional submits work")
    if m.status == "PENDING_FUNDING":
        raise Conflict("This milestone is not funded yet; work starts after funding", code="NOT_FUNDED")
    if m.status not in ("IN_PROGRESS", "REVISION_REQUESTED"):
        raise Conflict("This milestone is not open for submission", code="MILESTONE_NOT_OPEN")
    if not body.note.strip() and not body.files:
        raise Conflict("Add a note or at least one file describing what you delivered", code="EMPTY_SUBMISSION")
    now = clock.now()
    sub = Submission(milestone_id=m.id, submitted_by=actor.identity_id, note=body.note.strip(), files=[f.model_dump() for f in body.files])
    session.add(sub)
    await session.flush()
    MILESTONE_STATES.assert_can(m.status, "SUBMITTED")
    m.status, m.submitted_at = "SUBMITTED", now
    m.acceptance_due_at = now + timedelta(days=get_settings().acceptance_window_days)
    _evt(session, E.MILESTONE_SUBMITTED, c, milestoneId=m.id, submissionId=sub.id, acceptanceDueAt=m.acceptance_due_at)
    await session.flush()
    return await _out(session, actor, c, viewer)


async def _require_decider(session: AsyncSession, actor: Actor, c: Contract, viewer: str) -> None:
    if viewer != "BUYER":
        raise Forbidden("Only the buyer reviews submitted work")
    if not (await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id)).intersection(DECIDERS):
        raise Forbidden("Reviewing work needs the Requester or Approver role in your organisation", code="ROLE_REQUIRED")


async def accept_milestone(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID) -> ContractOut:
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    await _require_decider(session, actor, c, viewer)
    if m.status != "SUBMITTED":
        raise Conflict("Only submitted work can be accepted", code="MILESTONE_NOT_SUBMITTED")
    now = clock.now()
    MILESTONE_STATES.assert_can(m.status, "ACCEPTED")
    m.status, m.accepted_at, m.accepted_by = "ACCEPTED", now, actor.identity_id
    _evt(session, E.MILESTONE_ACCEPTED, c, milestoneId=m.id, amountMinor=m.amount_minor, currency=m.currency, acceptedBy=actor.identity_id,
         onTime=m.due_date is None or (m.submitted_at is not None and m.submitted_at.date() <= m.due_date), auto=False)
    await session.flush()
    if all(x.status == "ACCEPTED" for x in await _milestones(session, c.id)):
        CONTRACT_STATES.assert_can(c.status, "COMPLETED")
        c.status, c.completed_at = "COMPLETED", now
        _evt(session, E.CONTRACT_COMPLETED, c, reason="ALL_MILESTONES_ACCEPTED")
        await session.flush()
    return await _out(session, actor, c, viewer)


async def request_revision(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, body: RevisionIn) -> ContractOut:
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    await _require_decider(session, actor, c, viewer)
    if m.status != "SUBMITTED":
        raise Conflict("Only submitted work can be sent back for revision", code="MILESTONE_NOT_SUBMITTED")
    MILESTONE_STATES.assert_can(m.status, "REVISION_REQUESTED")
    m.status, m.last_revision_reason = "REVISION_REQUESTED", body.reason.strip()
    m.revision_count += 1
    _evt(session, E.MILESTONE_REVISION_REQUESTED, c, milestoneId=m.id, reason=m.last_revision_reason)
    await session.flush()
    return await _out(session, actor, c, viewer)
