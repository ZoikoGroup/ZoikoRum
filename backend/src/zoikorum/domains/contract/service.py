"""Contract domain: signatures, immutable amendments, and milestone lifecycle.

Every signature needs a fresh two-step confirmation and is stored as an append-only receipt bound to the exact terms
hash the signer saw. Change orders retain immutable revisions and disputes pause the milestone lifecycle.
Policy-required clauses arrive with the policy domain (platform template until then).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.policy import facade as policy_facade
from zoikorum.domains.contract.models import ChangeOrder, Contract, ContractRevision, Milestone, Signature, Submission
from zoikorum.domains.contract.schemas import (
    PartialOfferIn, PartialOfferOut, ChangeOrderIn, ChangePreviewOut, ContractOut, ContractRevisionOut, ContractSummaryOut, MilestoneOut,
    PartyOut, RevisionIn, SignatureOut, SignIn, SubmissionOut, SubmitIn,
)
from zoikorum.domains.escrow import facade as escrow_facade
from zoikorum.domains.firm import facade as firm_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, OrgRole, PlatformRole
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.http import page_of, paginate
from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.relay import cancel_timer, schedule_timer
from zoikorum.shared.state_machine import StateMachine
from zoikorum.shared.uploads import file_out, find_file, read_file, store_uploads

CONTRACT_STATES = StateMachine("Contract", {
    "GENERATED": {"PENDING_SIGNATURE"},
    "PENDING_SIGNATURE": {"ACTIVE", "TERMINATED"},
    "ACTIVE": {"COMPLETED", "TERMINATED", "DISPUTED", "PENDING_SIGNATURE"},
    "DISPUTED": {"ACTIVE", "COMPLETED", "TERMINATED"},
    "COMPLETED": set(),
    "TERMINATED": set(),
})
MILESTONE_STATES = StateMachine("Milestone", {
    "PENDING_FUNDING": {"IN_PROGRESS", "CANCELLED", "DISPUTED"},
    # -> PENDING_FUNDING only when a chargeback reverses the funding ("no work without funding").
    "IN_PROGRESS": {"SUBMITTED", "CANCELLED", "DISPUTED", "PENDING_FUNDING"},
    "SUBMITTED": {"REVISION_REQUESTED", "ACCEPTANCE_PENDING_APPROVAL", "ACCEPTED", "DISPUTED", "PENDING_FUNDING"},
    "REVISION_REQUESTED": {"IN_PROGRESS", "SUBMITTED", "DISPUTED", "PENDING_FUNDING"},
    "ACCEPTANCE_PENDING_APPROVAL": {"ACCEPTED", "REVISION_REQUESTED", "DISPUTED", "PENDING_FUNDING"},
    "DISPUTED": {"IN_PROGRESS", "ACCEPTED", "CANCELLED", "PENDING_FUNDING"},
    "ACCEPTED": set(),
    "CANCELLED": set(),
})
DECIDERS = (OrgRole.REQUESTER, OrgRole.APPROVER)
VIEWERS = (PlatformRole.PLATFORM_ADMIN, PlatformRole.COMPLIANCE_OFFICER, PlatformRole.LEGAL, PlatformRole.MEDIATOR)
TIMER_SIGNATURE = "contract.signature_deadline"
TIMER_REVIEW_REMINDER = "contract.review_reminder"  # one day before the buyer's review window closes
TIMER_REVIEW_DUE = "contract.review_due"  # the review window has passed
TIMER_AUTO_ACCEPT = "contract.policy_auto_accept"
TIMER_FUNDING_REMINDER = "contract.funding_reminder"  # an unfunded milestone / retainer cycle is coming up (P&E s.15)
LABEL = {"ADVISORY": "Advisory", "PROJECT": "Project", "RETAINER": "Retainer", "FRACTIONAL": "Fractional",
         "HOURLY": "Hourly", "FIXED": "Fixed fee"}
MAX_MONEY_MINOR = 9_223_372_036_854_775_807


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


def _change_order_out(change: ChangeOrder, preview: list[ChangePreviewOut]) -> dict:
    return {
        "id": change.id,
        "contractId": change.contract_id,
        "proposedByIdentityId": change.proposed_by_identity_id,
        "proposerParty": change.proposer_party,
        "type": change.change_type,
        "delta": change.delta,
        "impact": change.impact,
        "baseContractVersion": change.base_contract_version,
        "status": change.status,
        "decidedByIdentityId": change.decided_by_identity_id,
        "decisionReason": change.decision_reason,
        "decidedAt": change.decided_at,
        "appliedVersion": change.applied_version,
        "createdAt": change.created_at,
        "preview": preview,
    }


def _revision_milestone_snapshot(milestones: list[Milestone]) -> list[dict]:
    return [
        {
            "id": str(m.id),
            "sequence": m.sequence,
            "title": m.title,
            "amountMinor": m.amount_minor,
            "currency": m.currency,
            "dueDate": m.due_date.isoformat() if m.due_date else None,
            "deliverableKeys": list(m.deliverable_keys),
        }
        for m in milestones
    ]


async def _store_contract_revision(
    session: AsyncSession, c: Contract, milestones: list[Milestone], change_order_id: uuid.UUID | None = None
) -> ContractRevision:
    revision = ContractRevision(
        contract_id=c.id,
        contract_version=c.contract_version,
        change_order_id=change_order_id,
        currency=c.currency,
        total_minor=c.total_minor,
        terms=dict(c.terms),
        milestones=_revision_milestone_snapshot(milestones),
        terms_hash=c.terms_hash,
        document=c.document,
        document_sha256=c.document_sha256,
    )
    session.add(revision)
    await session.flush()
    return revision


def _change_preview(change: ChangeOrder, revision: ContractRevision | None) -> list[ChangePreviewOut]:
    if revision is None:
        return []
    delta = change.delta
    terms = revision.terms
    milestones = {item["id"]: item for item in revision.milestones}
    if change.change_type == "ADD_DELIVERABLE":
        item = delta["deliverable"]
        milestone = milestones[str(delta["milestoneId"])]
        return [
            ChangePreviewOut(
                label=f"M{milestone['sequence']} deliverables",
                before="No such deliverable",
                after=f"{item['title']} — {item['acceptanceCriteria']}",
            )
        ]
    if change.change_type == "MODIFY_DELIVERABLE":
        existing = next((item for item in terms.get("deliverables", []) if item["key"] == delta["key"]), {})
        labels = {"title": "Title", "description": "Description", "acceptanceCriteria": "Acceptance criteria"}
        return [
            ChangePreviewOut(
                label=f"{labels[field]} · {existing.get('title', delta['key'])}",
                before=str(existing.get(field) or "—"),
                after=value,
            )
            for field, value in delta["changes"].items()
        ]
    if change.change_type == "EXTEND_TIMELINE":
        result = [
            ChangePreviewOut(
                label="Contract end date",
                before=str(terms.get("endDate") or "Not set"),
                after=delta["endDate"],
            )
        ]
        for item in delta.get("milestoneDueDates", []):
            milestone = milestones[item["milestoneId"]]
            result.append(
                ChangePreviewOut(
                    label=f"M{milestone['sequence']} due date",
                    before=str(milestone.get("dueDate") or "Not set"),
                    after=item["dueDate"],
                )
            )
        return result
    if change.change_type == "PRICING_CHANGE":
        result = [
            ChangePreviewOut(
                label="Contract total",
                before=_money(revision.total_minor, revision.currency),
                after=_money(revision.total_minor + delta["totalDeltaMinor"], revision.currency),
            )
        ]
        for item in delta["milestoneAmounts"]:
            milestone = milestones[item["milestoneId"]]
            result.append(
                ChangePreviewOut(
                    label=f"M{milestone['sequence']} · {milestone['title']}",
                    before=_money(milestone["amountMinor"], revision.currency),
                    after=_money(item["amountMinor"], revision.currency),
                )
            )
        return result
    return []


def _change_error(message: str) -> Conflict:
    return Conflict(message, code="INVALID_CHANGE_ORDER")


async def _assert_allocations_unfunded(
    session: AsyncSession, c: Contract, milestone_ids: set[uuid.UUID]
) -> None:
    states = await escrow_facade.get_allocation_states_for_amendment(session, c.id, milestone_ids)
    if states is None or states.keys() != milestone_ids:
        raise Conflict("Escrow allocations are not available for this active contract", code="AMENDMENT_ESCROW_MISSING")
    if any(state != "UNFUNDED" for state in states.values()):
        raise _change_error("Scope or price can only change before the affected milestone enters funding")


async def _change_order_delta(
    session: AsyncSession, c: Contract, kind: str, delta: dict, *, apply: bool
) -> tuple[bool, list[Milestone]]:
    """Validate and optionally apply the documented delta shape for each supported change type."""
    milestones = await _milestones(session, c.id, lock=True)
    by_id = {str(m.id): m for m in milestones}
    terms = {**c.terms, "deliverables": [dict(d) for d in c.terms.get("deliverables", [])]}
    material = kind in {"ADD_DELIVERABLE", "MODIFY_DELIVERABLE", "PRICING_CHANGE"}

    if kind == "ADD_DELIVERABLE":
        item = delta.get("deliverable")
        milestone_id = delta.get("milestoneId")
        if set(delta) != {"milestoneId", "deliverable"}:
            raise _change_error("ADD_DELIVERABLE accepts only milestoneId and deliverable")
        if not isinstance(item, dict) or not milestone_id or not all(
            isinstance(item.get(key), str) and item[key].strip()
            for key in ("key", "title", "acceptanceCriteria")
        ):
            raise _change_error("ADD_DELIVERABLE needs milestoneId and a deliverable with key, title and acceptanceCriteria")
        if set(item) - {"key", "title", "description", "acceptanceCriteria"}:
            raise _change_error("Deliverable has unsupported fields")
        if len(item["key"].strip()) > 100 or len(item["title"].strip()) > 200 or len(item["acceptanceCriteria"].strip()) > 1000:
            raise _change_error("Deliverable key, title or acceptance criteria exceeds its maximum length")
        if item.get("description") is not None and not isinstance(item["description"], str):
            raise _change_error("Deliverable description must be text")
        if len((item.get("description") or "").strip()) > 1000:
            raise _change_error("Deliverable description exceeds 1000 characters")
        target = by_id.get(str(milestone_id))
        if target is None or target.status != "PENDING_FUNDING":
            raise _change_error("New deliverables can only be assigned to a milestone that has not started")
        await _assert_allocations_unfunded(session, c, {target.id})
        if any(d.get("key") == item["key"] for d in terms["deliverables"]):
            raise _change_error("Deliverable key already exists")
        if apply:
            terms["deliverables"].append({
                "key": item["key"].strip(),
                "title": item["title"].strip(),
                "description": (item.get("description") or "").strip(),
                "acceptanceCriteria": item["acceptanceCriteria"].strip(),
            })
            target.deliverable_keys = [*target.deliverable_keys, item["key"].strip()]
            c.terms = terms
    elif kind == "MODIFY_DELIVERABLE":
        key = delta.get("key")
        changes = delta.get("changes")
        if set(delta) != {"key", "changes"}:
            raise _change_error("MODIFY_DELIVERABLE accepts only key and changes")
        if not isinstance(key, str) or not isinstance(changes, dict) or not changes:
            raise _change_error("MODIFY_DELIVERABLE needs key and a non-empty changes object")
        if set(changes) - {"title", "description", "acceptanceCriteria"} or any(
            not isinstance(value, str) or not value.strip() for value in changes.values()
        ):
            raise _change_error("Changes may only set non-empty title, description or acceptanceCriteria values")
        if len(key.strip()) > 100 or any(
            len(value.strip()) > limit
            for field, value in changes.items()
            for limit in [{"title": 200, "description": 1000, "acceptanceCriteria": 1000}[field]]
        ):
            raise _change_error("Deliverable key or changed field exceeds its maximum length")
        target = next((d for d in terms["deliverables"] if d.get("key") == key), None)
        if target is None:
            raise _change_error("Deliverable key does not exist")
        linked = [m for m in milestones if key in m.deliverable_keys]
        if not linked or any(m.status != "PENDING_FUNDING" for m in linked):
            raise _change_error("Deliverables can only be modified before their linked milestone work starts")
        await _assert_allocations_unfunded(session, c, {m.id for m in linked})
        if apply:
            target.update({field: value.strip() for field, value in changes.items()})
            c.terms = terms
    elif kind == "EXTEND_TIMELINE":
        end_date = delta.get("endDate")
        if set(delta) - {"endDate", "milestoneDueDates"}:
            raise _change_error("EXTEND_TIMELINE has unsupported fields")
        if not isinstance(end_date, str):
            raise _change_error("EXTEND_TIMELINE needs an ISO endDate")
        try:
            new_end = date.fromisoformat(end_date)
        except ValueError as exc:
            raise _change_error("endDate must be an ISO calendar date") from exc
        old_end = date.fromisoformat(c.terms["endDate"]) if c.terms.get("endDate") else None
        if new_end <= clock.now().date() or (old_end is not None and new_end <= old_end):
            raise _change_error("The new contract end date must extend the existing date and remain in the future")
        due_dates = delta.get("milestoneDueDates", [])
        if not isinstance(due_dates, list) or len(due_dates) > len(milestones):
            raise _change_error("milestoneDueDates must be a list")
        changes: list[tuple[Milestone, date]] = []
        for item in due_dates:
            if not isinstance(item, dict) or not isinstance(item.get("milestoneId"), str) or not isinstance(item.get("dueDate"), str):
                raise _change_error("Each milestoneDueDates entry needs milestoneId and dueDate")
            if set(item) != {"milestoneId", "dueDate"} or item["milestoneId"] in {str(m.id) for m, _ in changes}:
                raise _change_error("Milestone due-date entries must be unique and contain only milestoneId and dueDate")
            milestone = by_id.get(item["milestoneId"])
            try:
                due = date.fromisoformat(item["dueDate"])
            except ValueError as exc:
                raise _change_error("Milestone dueDate must be an ISO calendar date") from exc
            if milestone is None or milestone.status in {"ACCEPTED", "CANCELLED"}:
                raise _change_error("Only open milestones can have their due date extended")
            if milestone.due_date and due < milestone.due_date:
                raise _change_error("Timeline change orders cannot move a milestone deadline earlier")
            changes.append((milestone, due))
        if apply:
            terms["endDate"] = new_end.isoformat()
            if due_dates:
                by_sequence = {m.sequence: m for m in milestones}
                due_by_id = {m.id: due.isoformat() for m, due in changes}
                terms["milestones"] = [
                    {**item, "dueDate": due_by_id[by_sequence[item["sequence"]].id]}
                    if item.get("sequence") in by_sequence and by_sequence[item["sequence"]].id in due_by_id
                    else item
                    for item in terms.get("milestones", [])
                ]
            c.terms = terms
            for milestone, due in changes:
                milestone.due_date = due
    elif kind == "PRICING_CHANGE":
        if set(delta) != {"totalDeltaMinor", "milestoneAmounts"}:
            raise _change_error("PRICING_CHANGE accepts only totalDeltaMinor and milestoneAmounts")
        delta_minor = delta.get("totalDeltaMinor")
        amounts = delta.get("milestoneAmounts")
        if not isinstance(delta_minor, int) or isinstance(delta_minor, bool) or delta_minor == 0 or not isinstance(amounts, list) or not amounts:
            raise _change_error("PRICING_CHANGE needs non-zero totalDeltaMinor and milestoneAmounts")
        parsed: list[tuple[Milestone, int]] = []
        for item in amounts:
            if not isinstance(item, dict) or not isinstance(item.get("milestoneId"), str):
                raise _change_error("Each milestone amount needs milestoneId and amountMinor")
            if set(item) != {"milestoneId", "amountMinor"} or item["milestoneId"] in {str(m.id) for m, _ in parsed}:
                raise _change_error("Milestone amount entries must be unique and contain only milestoneId and amountMinor")
            amount = item.get("amountMinor")
            milestone = by_id.get(item["milestoneId"])
            if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0 or amount > MAX_MONEY_MINOR:
                raise _change_error("Milestone amountMinor must be a positive 64-bit integer")
            if milestone is None or milestone.status != "PENDING_FUNDING":
                raise _change_error("Pricing can only change on milestones that have not been funded or started")
            parsed.append((milestone, amount))
        await _assert_allocations_unfunded(session, c, {milestone.id for milestone, _ in parsed})
        if sum(new - milestone.amount_minor for milestone, new in parsed) != delta_minor:
            raise _change_error("Milestone amount changes must add up to totalDeltaMinor")
        if c.total_minor + delta_minor <= 0 or c.total_minor + delta_minor > MAX_MONEY_MINOR:
            raise _change_error("The resulting contract total must be a positive 64-bit integer")
        if apply:
            for milestone, amount in parsed:
                milestone.amount_minor = amount
            c.total_minor += delta_minor
            by_sequence = {m.sequence: m for m in milestones}
            terms["milestones"] = [
                {**item, "amountMinor": by_sequence[item["sequence"]].amount_minor}
                if item.get("sequence") in by_sequence else item
                for item in terms.get("milestones", [])
            ]
            c.terms = terms
    else:
        raise _change_error("Unsupported change order type")
    return material, milestones


async def _refresh_contract_document(session: AsyncSession, c: Contract) -> list[Milestone]:
    milestones = await _milestones(session, c.id, lock=True)
    c.terms_hash = _hash(c.terms)
    c.contract_version += 1
    c.document = render_document(c, milestones)
    c.document_sha256 = hashlib.sha256(c.document.encode()).hexdigest()
    return milestones


def _amendment_payload(c: Contract, change: ChangeOrder, milestones: list[Milestone]) -> dict:
    return {
        "changeOrderId": change.id,
        "changeOrderType": change.change_type,
        "contractVersion": c.contract_version,
        "termsHash": c.terms_hash,
        "totalMinor": c.total_minor,
        "currency": c.currency,
        "milestones": _milestone_list(milestones),
    }


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
    window = c.terms.get("policySettings", {}).get("acceptanceWindowDays", get_settings().acceptance_window_days)
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
    if c.nda_required or "CONFIDENTIALITY" in t.get("clauses", []):
        lines += ["", "11. CONFIDENTIALITY",
                  "The professional keeps the buyer's confidential information confidential and uses it only for this engagement, "
                  "as accepted before the proposal was written."]
    lines += ["", "STANDARD TERMS",
              "The Zoikorum Terms of Service apply to this agreement. Governing law and jurisdiction follow those terms unless an "
              "enterprise policy profile sets them.",
              "", f"Terms reference (SHA-256): {c.terms_hash}", f"Policy: {c.policy_version_label}"]
    if t.get("governingLaw"):
        lines.extend(["Governing law: " + t["governingLaw"]])
    if "IP_OWNERSHIP" in t.get("clauses", []):
        lines.extend(["IP ownership: rights and licences follow the Zoikorum Terms of Service and any ownership terms expressly included in this agreement."])
    if "TERMINATION" in t.get("clauses", []):
        lines.extend(["Termination: cancellation and outstanding funds follow the Zoikorum termination and dispute procedures."])
    auto_days = t.get("policySettings", {}).get("autoAcceptAfterDays")
    if auto_days:
        lines.extend([f"Policy-authorised automatic acceptance: unanswered submissions may be accepted after {auto_days} days, subject to policy checks and dispute holds."])
    for clause, clause_text in t.get("clauseTexts", {}).items():
        if clause in t.get("clauses", []):
            lines.extend(["", f"ENTERPRISE CLAUSE — {clause.replace('_', ' ')}", clause_text])
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
        policy_version_id=uuid.UUID(str(payload["policyVersionId"])) if payload.get("policyVersionId") else None,
        signature_deadline=now + timedelta(days=terms.get("policySettings", {}).get("signatureDeadlineDays", get_settings().signature_deadline_days)),
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
    await _store_contract_revision(session, c, milestones)
    _evt(session, E.CONTRACT_GENERATED, c, proposalId=proposal_id, buyerIdentityId=buyer_id, totalMinor=c.total_minor,
         currency=c.currency, termsHash=c.terms_hash, signatureDeadline=c.signature_deadline)
    for m in milestones:
        _evt(session, E.MILESTONE_CREATED, c, milestoneId=m.id, sequence=m.sequence, amountMinor=m.amount_minor, currency=m.currency, dueDate=m.due_date, title=m.title)
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
        if _review_overdue(m):
            return (f"Review overdue: M{m.sequence} {m.title}. Accept it or request a revision" if viewer == "BUYER"
                    else f"The review of M{m.sequence} is overdue. The buyer has been reminded; payment stays protected in escrow")
        return f"Review submitted work: M{m.sequence} {m.title}" if viewer == "BUYER" else f"Waiting for review of M{m.sequence}"
    if by["REVISION_REQUESTED"]:
        m = by["REVISION_REQUESTED"][0]
        return f"Revise and resubmit M{m.sequence} {m.title}" if viewer == "PROFESSIONAL" else f"Waiting for the revised M{m.sequence}"
    if by["IN_PROGRESS"]:
        m = by["IN_PROGRESS"][0]
        return f"Deliver M{m.sequence} {m.title}" if viewer == "PROFESSIONAL" else f"Work in progress on M{m.sequence}"
    if by["PENDING_FUNDING"]:
        m = by["PENDING_FUNDING"][0]
        return (f"Fund M{m.sequence} to start work" if viewer == "BUYER"
                else f"Waiting for the buyer to fund M{m.sequence}")
    return "In progress"


async def _out(session: AsyncSession, actor: Actor, c: Contract, viewer: str) -> ContractOut:
    ms = await _milestones(session, c.id)
    sigs = list((await session.scalars(select(Signature).where(Signature.contract_id == c.id).order_by(Signature.signed_at))).all())
    changes = list((await session.scalars(
        select(ChangeOrder).where(ChangeOrder.contract_id == c.id).order_by(ChangeOrder.created_at)
    )).all())
    revisions = list((await session.scalars(
        select(ContractRevision).where(ContractRevision.contract_id == c.id).order_by(ContractRevision.contract_version)
    )).all())
    revisions_by_version = {revision.contract_version: revision for revision in revisions}
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
        status=c.status, pendingChangeOrderId=c.pending_change_order_id,
        total=MoneyDTO(amountMinor=c.total_minor, currency=c.currency), termsHash=c.terms_hash,
        contractVersion=c.contract_version,
        parties=[PartyOut(role="BUYER", name=p["buyer"]["name"], detail=f"Signatory: {p['buyer']['signatory']}"),
                 PartyOut(role="PROFESSIONAL", name=p["professional"]["name"], detail=firm_line)],
        terms=c.terms, ndaRequired=c.nda_required, documentSha256=c.document_sha256, policyVersionLabel=c.policy_version_label,
        signatureDeadline=c.signature_deadline, activatedAt=c.activated_at, completedAt=c.completed_at,
        signatures=[SignatureOut(party=s.party, signerName=s.signer_name, contractVersion=s.contract_version, termsHash=s.terms_hash,
                                 authStrength=s.auth_strength, signedAt=s.signed_at) for s in sigs],
        changeOrders=[
            _change_order_out(change, _change_preview(change, revisions_by_version.get(change.base_contract_version)))
            for change in changes
        ],
        revisions=[
            ContractRevisionOut(
                contractVersion=revision.contract_version,
                changeOrderId=revision.change_order_id,
                currency=revision.currency,
                total=MoneyDTO(amountMinor=revision.total_minor, currency=revision.currency),
                terms=revision.terms,
                milestones=revision.milestones,
                termsHash=revision.terms_hash,
                documentSha256=revision.document_sha256,
                createdAt=revision.created_at,
            )
            for revision in revisions
        ],
        milestones=[MilestoneOut(
            id=m.id, sequence=m.sequence, title=m.title, description=m.description,
            amount=MoneyDTO(amountMinor=m.amount_minor, currency=m.currency), dueDate=m.due_date, deliverableKeys=m.deliverable_keys,
            status=m.status, startedAt=m.started_at, submittedAt=m.submitted_at, acceptanceDueAt=m.acceptance_due_at,
            reviewOverdue=_review_overdue(m),
            acceptedAt=m.accepted_at, revisionCount=m.revision_count, lastRevisionReason=m.last_revision_reason,
            partialOffer=PartialOfferOut(amount=MoneyDTO(amountMinor=m.partial_offer_minor, currency=m.currency),
                                         refund=MoneyDTO(amountMinor=m.amount_minor - m.partial_offer_minor, currency=m.currency),
                                         reason=m.partial_offer_reason or "", offeredAt=m.partial_offered_at)
            if m.partial_offer_minor is not None and m.partial_offered_at is not None else None,
            acceptedRelease=MoneyDTO(amountMinor=m.accepted_release_minor, currency=m.currency) if m.accepted_release_minor is not None else None,
            submissions=[SubmissionOut(id=s.id, note=s.note, files=[file_out(f) for f in s.files], submittedAt=s.created_at)
                         for s in subs if s.milestone_id == m.id],
        ) for m in ms],
        viewerRole=viewer, nextAction=_next_action(c, ms, signed, viewer, p["professional"]["name"]), canSign=can_sign,
        acceptedAmount=MoneyDTO(amountMinor=accepted, currency=c.currency), createdAt=c.created_at, version=c.version,
    )


async def get_contract(session: AsyncSession, actor: Actor, contract_id: uuid.UUID) -> ContractOut:
    c = await _contract(session, contract_id)
    return await _out(session, actor, c, await _viewer(session, actor, c))


async def get_document(
    session: AsyncSession, actor: Actor, contract_id: uuid.UUID, version: int | None = None
) -> tuple[str, str]:
    c = await _contract(session, contract_id)
    await _viewer(session, actor, c)
    if version is None or version == c.contract_version:
        document, document_hash, selected_version = c.document, c.document_sha256, c.contract_version
    else:
        revision = await session.scalar(
            select(ContractRevision).where(
                ContractRevision.contract_id == c.id,
                ContractRevision.contract_version == version,
            )
        )
        if revision is None:
            raise NotFound("Contract version not found")
        document, document_hash, selected_version = revision.document, revision.document_sha256, version
    record_audit(session, "contract.document.viewed", object_type="Contract", object_id=c.id, tenant_id=c.organization_id,
                 evidence_hash=document_hash, details={"version": selected_version})
    return document, document_hash


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


async def propose_change_order(
    session: AsyncSession, actor: Actor, contract_id: uuid.UUID, body: ChangeOrderIn
) -> ContractOut:
    c = await _contract(session, contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    if viewer == "OPERATOR":
        raise Forbidden("Only the contract parties can propose a change")
    if c.status != "ACTIVE" or c.pending_change_order_id is not None:
        raise Conflict("A change order can only be proposed on an active contract with no amendment awaiting signatures",
                       code="CONTRACT_NOT_AMENDABLE")
    if await session.scalar(select(ChangeOrder.id).where(
        ChangeOrder.contract_id == c.id, ChangeOrder.status == "PROPOSED"
    )):
        raise Conflict("Resolve the existing proposed change order before proposing another", code="CHANGE_ORDER_PENDING")
    if viewer == "BUYER":
        roles = await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id)
        if not roles.intersection(DECIDERS):
            raise Forbidden("Proposing a change needs the Requester or Approver role", code="ROLE_REQUIRED")
    await _change_order_delta(session, c, body.type, body.delta, apply=False)
    change = ChangeOrder(
        contract_id=c.id,
        proposed_by_identity_id=actor.identity_id,
        proposer_party=viewer,
        change_type=body.type,
        delta=body.delta,
        impact=body.impact.strip(),
        base_contract_version=c.contract_version,
        status="PROPOSED",
    )
    session.add(change)
    await session.flush()
    _evt(session, E.CHANGE_ORDER_REQUESTED, c, changeOrderId=change.id, proposedByParty=viewer,
         changeType=body.type, impact=change.impact, baseContractVersion=c.contract_version)
    record_audit(session, "contract.change_order.proposed", object_type="ChangeOrder", object_id=change.id,
                 tenant_id=c.organization_id, policy_version=c.policy_version_label,
                 details={"contractId": str(c.id), "type": body.type, "delta": body.delta, "impact": change.impact})
    await session.flush()
    return await _out(session, actor, c, viewer)


async def decide_change_order(
    session: AsyncSession,
    actor: Actor,
    change_order_id: uuid.UUID,
    approve: bool,
    reason: str | None,
) -> ContractOut:
    change = await session.get(ChangeOrder, change_order_id, with_for_update=True)
    if change is None:
        raise NotFound("Change order not found")
    c = await _contract(session, change.contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    if viewer == "OPERATOR" or viewer == change.proposer_party:
        raise Forbidden("Only the other contract party can decide a change order")
    if viewer == "BUYER":
        roles = await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id)
        if not roles.intersection(DECIDERS):
            raise Forbidden("Deciding a change needs the Requester or Approver role", code="ROLE_REQUIRED")
    if change.status != "PROPOSED":
        raise Conflict("This change order has already been decided", code="CHANGE_ORDER_ALREADY_DECIDED")
    if c.status != "ACTIVE" or c.contract_version != change.base_contract_version:
        raise Conflict("The contract changed after this proposal; create a new change order", code="CHANGE_ORDER_STALE")
    actor.require_step_up()
    if approve:
        await policy_facade.require_allowed(session, await policy_facade.commercial_context(session,
            org_id=c.organization_id, professional_id=c.professional_id, action=policy_facade.PolicyAction.CHANGE_ORDER_APPROVE,
            subject_type="ChangeOrder", subject_id=change.id, actor_identity_id=actor.identity_id,
            amount=c.total_minor + (int(change.delta.get("totalDeltaMinor", 0)) if change.change_type == "PRICING_CHANGE" else 0),
            currency=c.currency, engagement_type=c.engagement_type,
            pinned_version_id=c.policy_version_id, platform_default_pinned=c.policy_version_id is None,
            extra={"contract.termsHash": c.terms_hash, "contract.version": c.contract_version}))
    now = clock.now()
    change.decided_by_identity_id = actor.identity_id
    change.decided_at = now
    change.decision_reason = reason.strip() if reason else None
    if not approve:
        change.status = "REJECTED"
        _evt(session, E.CHANGE_ORDER_REJECTED, c, changeOrderId=change.id, decidedByIdentityId=actor.identity_id,
             reason=change.decision_reason)
        record_audit(session, "contract.change_order.rejected", object_type="ChangeOrder", object_id=change.id,
                     tenant_id=c.organization_id, policy_version=c.policy_version_label,
                     details={"contractId": str(c.id), "reason": change.decision_reason})
        await session.flush()
        return await _out(session, actor, c, viewer)

    change.status = "APPROVED"
    material, _ = await _change_order_delta(session, c, change.change_type, change.delta, apply=True)
    milestones = await _refresh_contract_document(session, c)
    await _store_contract_revision(session, c, milestones, change.id)
    record_audit(session, "contract.change_order.approved", object_type="ChangeOrder", object_id=change.id,
                 tenant_id=c.organization_id, evidence_hash=c.terms_hash, policy_version=c.policy_version_label,
                 details={"contractId": str(c.id), "version": c.contract_version, "material": material,
                          "awaitingSignatures": material})
    _evt(session, E.CHANGE_ORDER_APPROVED, c, changeOrderId=change.id, decidedByIdentityId=actor.identity_id,
         contractVersion=c.contract_version, awaitingSignatures=material)
    if material:
        CONTRACT_STATES.assert_can(c.status, "PENDING_SIGNATURE")
        c.status = "PENDING_SIGNATURE"
        c.pending_change_order_id = change.id
        c.signature_deadline = now + timedelta(days=get_settings().signature_deadline_days)
        await cancel_timer(session, TIMER_SIGNATURE, str(c.id))
        await schedule_timer(session, TIMER_SIGNATURE, str(c.id), c.signature_deadline, {"contractId": str(c.id)})
    else:
        change.applied_version = c.contract_version
        _evt(session, E.CONTRACT_AMENDED, c, **_amendment_payload(c, change, milestones))
    await session.flush()
    return await _out(session, actor, c, viewer)


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
    await policy_facade.require_allowed(session, await policy_facade.commercial_context(session,
        org_id=c.organization_id, professional_id=c.professional_id, action=policy_facade.PolicyAction.CONTRACT_SIGN,
        subject_type="Contract", subject_id=c.id, actor_identity_id=actor.identity_id,
        amount=c.total_minor, currency=c.currency, engagement_type=c.engagement_type,
        pinned_version_id=c.policy_version_id, platform_default_pinned=c.policy_version_id is None,
        extra={"contract.termsHash": c.terms_hash, "contract.version": c.contract_version, "contract.signerParty": viewer}))
    now = clock.now()
    session.add(Signature(contract_id=c.id, contract_version=c.contract_version, party=viewer, signer_identity_id=actor.identity_id,
                          signer_name=who.display_name if who else "Signer", terms_hash=c.terms_hash,
                          auth_strength=actor.auth_strength, ip=ip, signed_at=now))
    _evt(session, E.CONTRACT_SIGNED, c, signerIdentityId=actor.identity_id, party=viewer, termsHash=c.terms_hash)
    if signed | {viewer} == {"BUYER", "PROFESSIONAL"}:
        CONTRACT_STATES.assert_can(c.status, "ACTIVE")
        c.status = "ACTIVE"
        await cancel_timer(session, TIMER_SIGNATURE, str(c.id))
        if c.pending_change_order_id is not None:
            change = await session.get(ChangeOrder, c.pending_change_order_id)
            if change is None or change.status != "APPROVED":
                raise Conflict("The pending contract amendment could not be verified", code="CHANGE_ORDER_STATE_INVALID")
            c.pending_change_order_id = None
            change.applied_version = c.contract_version
            record_audit(
                session,
                "contract.change_order.executed",
                object_type="ChangeOrder",
                object_id=change.id,
                tenant_id=c.organization_id,
                evidence_hash=c.terms_hash,
                policy_version=c.policy_version_label,
                details={"contractId": str(c.id), "version": c.contract_version},
            )
            _evt(session, E.CONTRACT_AMENDED, c, **_amendment_payload(c, change, await _milestones(session, c.id)))
        else:
            c.activated_at = now
            _evt(session, E.CONTRACT_ACTIVATED, c, buyerIdentityId=c.buyer_identity_id, currency=c.currency,
                 totalMinor=c.total_minor, policyVersionId=c.policy_version_id, milestones=_milestone_list(await _milestones(session, c.id)))
        await _schedule_funding_reminders(session, c, now)
    await session.flush()
    return await _out(session, actor, c, viewer)


# ---- Milestones -----------------------------------------------------------------------------------

async def _schedule_funding_reminders(session: AsyncSession, c: Contract, now: datetime) -> None:
    """Upcoming funding reminders (Payments & Escrow s.15): a few days before each dated milestone or retainer cycle."""
    days = get_settings().funding_reminder_days
    for m in await _milestones(session, c.id):
        if m.due_date is None:
            continue
        fire = datetime.combine(m.due_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=days)
        if fire > now:
            await schedule_timer(session, TIMER_FUNDING_REMINDER, str(m.id), fire, {"milestoneId": str(m.id)})


async def funding_reminder(session: AsyncSession, payload: dict) -> None:
    m = await session.get(Milestone, uuid.UUID(payload["milestoneId"]))
    if m is None or m.status != "PENDING_FUNDING":
        return  # already funded, cancelled or done
    c = await _contract(session, m.contract_id)
    if c.status == "ACTIVE":
        _evt(session, E.MILESTONE_FUNDING_REMINDER, c, milestoneId=m.id, dueDate=m.due_date, amountMinor=m.amount_minor, currency=m.currency)


async def cancel_remaining_cycles(session: AsyncSession, actor: Actor, contract_id: uuid.UUID, reason: str) -> ContractOut:
    """Retainer cancel control (Payments & Escrow s.15, policy-bound): the buyer stops future cycles that have not been
    funded. Funded cycles continue (or are settled through a dispute); nothing already paid moves."""
    c = await _contract(session, contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    await _require_decider(session, actor, c, viewer)
    if c.engagement_type != "RETAINER" and c.pricing_model != "RETAINER":
        raise Conflict("Only retainer cycles can be cancelled this way; for other engagements raise a dispute or agree a change",
                       code="NOT_A_RETAINER")
    if c.status != "ACTIVE":
        raise Conflict("Only an active retainer can be changed", code="CONTRACT_NOT_ACTIVE")
    ms = await _milestones(session, c.id, lock=True)
    future = [m for m in ms if m.status == "PENDING_FUNDING"]
    if not future:
        raise Conflict("There are no unfunded cycles left to cancel", code="NOTHING_TO_CANCEL")
    for m in future:
        MILESTONE_STATES.assert_can(m.status, "CANCELLED")
        m.status = "CANCELLED"
        await cancel_timer(session, TIMER_FUNDING_REMINDER, str(m.id))
        _evt(session, E.MILESTONE_CANCELLED, c, milestoneId=m.id, reason=reason.strip()[:500], cancelledBy=actor.identity_id)
    if all(m.status in ("ACCEPTED", "CANCELLED") for m in ms):
        now = clock.now()
        if any(m.status == "ACCEPTED" for m in ms):
            c.status, c.completed_at = "COMPLETED", now
            _evt(session, E.CONTRACT_COMPLETED, c, reason="REMAINING_CYCLES_CANCELLED")
        else:
            c.status = "TERMINATED"
            _evt(session, E.CONTRACT_TERMINATED, c, reason="ALL_CYCLES_CANCELLED")
    await session.flush()
    return await _out(session, actor, c, viewer)


async def _milestone_ctx(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID) -> tuple[Milestone, Contract, str]:
    m = await session.get(Milestone, milestone_id, with_for_update=True)
    if m is None:
        raise NotFound("Milestone not found")
    c = await _contract(session, m.contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    if c.status != "ACTIVE":
        raise Conflict("The contract is not active", code="CONTRACT_NOT_ACTIVE")
    return m, c, viewer


async def funding_reversed(session: AsyncSession, payload: dict) -> None:
    """Consumer of ESCROW_FUNDING_REVERSED (chargeback): the affected milestones wait for funding again."""
    ids = {uuid.UUID(str(i)) for i in payload.get("milestoneIds", [])}
    if not ids:
        return
    c = await session.get(Contract, uuid.UUID(str(payload["contractId"])), with_for_update=True)
    if c is None:
        return
    for m in await _milestones(session, c.id, lock=True):
        if m.id in ids and MILESTONE_STATES.can(m.status, "PENDING_FUNDING"):
            m.status, m.acceptance_due_at = "PENDING_FUNDING", None
            _evt(session, E.MILESTONE_FUNDING_REVERSED, c, milestoneId=m.id, reason=payload.get("reason") or "")
    if c.status == "DISPUTED" and not any(m.status == "DISPUTED" for m in await _milestones(session, c.id)):
        c.status = "ACTIVE"


async def dispute_initiated(session: AsyncSession, payload: dict) -> None:
    """Consumer of DISPUTE_INITIATED: the disputed milestones and the contract pause; no one can act unilaterally."""
    c = await session.get(Contract, uuid.UUID(str(payload["contractId"])), with_for_update=True)
    if c is None or c.status not in ("ACTIVE", "DISPUTED"):
        return
    ids = {uuid.UUID(str(i)) for i in payload.get("milestoneIds", [])}
    for m in await _milestones(session, c.id, lock=True):
        if m.id in ids and MILESTONE_STATES.can(m.status, "DISPUTED"):
            m.status = "DISPUTED"
            m.partial_offer_minor = m.partial_offer_reason = m.partial_offered_at = None
    if c.status == "ACTIVE":
        c.status = "DISPUTED"
        _evt(session, E.CONTRACT_DISPUTED, c, disputeId=payload["disputeId"])


async def dispute_resolved(session: AsyncSession, payload: dict) -> None:
    """Consumer of DISPUTE_RESOLVED: apply each milestone's outcome; terminate, complete or resume the contract."""
    c = await session.get(Contract, uuid.UUID(str(payload["contractId"])), with_for_update=True)
    if c is None or c.status != "DISPUTED":
        return
    now = clock.now()
    outcomes = {str(a["milestoneId"]): a["milestoneOutcome"] for a in payload.get("allocations", [])}
    ms = await _milestones(session, c.id, lock=True)
    for m in ms:
        o = outcomes.get(str(m.id))
        if o is None or m.status != "DISPUTED":
            continue
        if o == "ACCEPT":
            m.status, m.accepted_at = "ACCEPTED", now
        elif o == "CANCEL":
            m.status = "CANCELLED"
        else:  # REWORK / EXTEND: back to work; the money stays held
            m.status = "IN_PROGRESS"
    if payload.get("outcome") == "TERMINATION":
        for m in ms:
            if m.status in ("PENDING_FUNDING", "IN_PROGRESS", "SUBMITTED", "REVISION_REQUESTED"):
                m.status = "CANCELLED"
        c.status = "TERMINATED"
        _evt(session, E.CONTRACT_TERMINATED, c, reason="DISPUTE_DECISION", disputeId=payload["disputeId"])
        return
    if any(m.status == "DISPUTED" for m in ms):
        return  # another dispute on this contract is still open
    if all(m.status in ("ACCEPTED", "CANCELLED") for m in ms):
        if any(m.status == "ACCEPTED" for m in ms):
            c.status, c.completed_at = "COMPLETED", now
            _evt(session, E.CONTRACT_COMPLETED, c, reason="ALL_MILESTONES_SETTLED")
        else:
            c.status = "TERMINATED"
            _evt(session, E.CONTRACT_TERMINATED, c, reason="ALL_MILESTONES_CANCELLED", disputeId=payload["disputeId"])
        return
    c.status = "ACTIVE"
    _evt(session, E.CONTRACT_DISPUTE_CLEARED, c, disputeId=payload["disputeId"])


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


async def submission_file(session: AsyncSession, actor: Actor, contract_id: uuid.UUID, sha256: str) -> tuple[bytes, str | None, str]:
    """A delivered file, for the parties and for operators (e.g. a mediator in a dispute). Every opening is audited."""
    c = await _contract(session, contract_id)
    viewer = await _viewer(session, actor, c)
    subs = (await session.scalars(select(Submission).join(Milestone, Milestone.id == Submission.milestone_id)
                                  .where(Milestone.contract_id == c.id))).all()
    rec = find_file([f for s in subs for f in s.files], sha256)
    data = read_file(rec)
    record_audit(session, "contract.deliverable.viewed", object_type="Contract", object_id=c.id, tenant_id=c.organization_id,
                 evidence_hash=rec["sha256"], details={"viewer": viewer})
    return data, rec.get("contentType"), rec["name"]


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
    sub = Submission(milestone_id=m.id, submitted_by=actor.identity_id, note=body.note.strip(),
                     files=store_uploads(f"contracts/{c.id}/{m.id}", body.files))
    session.add(sub)
    await session.flush()
    MILESTONE_STATES.assert_can(m.status, "SUBMITTED")
    m.status, m.submitted_at = "SUBMITTED", now
    m.acceptance_due_at = now + timedelta(days=c.terms.get("policySettings", {}).get("acceptanceWindowDays", get_settings().acceptance_window_days))
    _evt(session, E.MILESTONE_SUBMITTED, c, milestoneId=m.id, submissionId=sub.id, acceptanceDueAt=m.acceptance_due_at)
    # Acceptance timer (Payments & Escrow s.10). Keyed per submission, so a resubmission starts a fresh window.
    timer = {"milestoneId": str(m.id), "submissionId": str(sub.id)}
    if m.acceptance_due_at - timedelta(days=1) > now:
        await schedule_timer(session, TIMER_REVIEW_REMINDER, str(sub.id), m.acceptance_due_at - timedelta(days=1), timer)
    await schedule_timer(session, TIMER_REVIEW_DUE, str(sub.id), m.acceptance_due_at, timer)
    auto_days = c.terms.get("policySettings", {}).get("autoAcceptAfterDays")
    if auto_days:
        await schedule_timer(session, TIMER_AUTO_ACCEPT, str(sub.id), now + timedelta(days=auto_days), timer)
    await session.flush()
    return await _out(session, actor, c, viewer)


async def _awaiting_review(session: AsyncSession, payload: dict) -> tuple[Milestone, Contract] | None:
    """The milestone still waits for review of this very submission (not accepted, revised, disputed or resubmitted)."""
    m = await session.get(Milestone, uuid.UUID(payload["milestoneId"]))
    if m is None or m.status != "SUBMITTED":
        return None
    latest = await session.scalar(select(Submission.id).where(Submission.milestone_id == m.id)
                                  .order_by(Submission.created_at.desc()).limit(1))
    if str(latest) != payload["submissionId"]:
        return None
    return m, await _contract(session, m.contract_id)


async def review_reminder(session: AsyncSession, payload: dict) -> None:
    if found := await _awaiting_review(session, payload):
        m, c = found
        _evt(session, E.MILESTONE_ACCEPTANCE_REMINDER, c, milestoneId=m.id, acceptanceDueAt=m.acceptance_due_at)


async def review_overdue(session: AsyncSession, payload: dict) -> None:
    """The window passed without a decision. The money stays in escrow: auto-release is an enterprise policy rule
    (Payments & Escrow s.17) that is off until a policy profile turns it on. The engagement is flagged for follow-up."""
    if found := await _awaiting_review(session, payload):
        m, c = found
        _evt(session, E.MILESTONE_ACCEPTANCE_OVERDUE, c, milestoneId=m.id, acceptanceDueAt=m.acceptance_due_at)


def _review_overdue(m: Milestone) -> bool:
    return m.status == "SUBMITTED" and m.acceptance_due_at is not None and m.acceptance_due_at <= clock.now()


async def policy_auto_accept(session, payload):
    found = await _awaiting_review(session, payload)
    if not found:
        return
    m, c = found
    c = await _contract(session, c.id, lock=True)
    m = await session.get(Milestone, m.id, with_for_update=True)
    if c.status != "ACTIVE" or m.status != "SUBMITTED":
        return
    auto_days = c.terms.get("policySettings", {}).get("autoAcceptAfterDays")
    if not auto_days or not m.submitted_at or m.submitted_at + timedelta(days=auto_days) > clock.now():
        return
    from zoikorum.domains.dispute import facade as dispute_facade
    if await dispute_facade.open_disputes_for_contract(session, c.id):
        return
    decision = await policy_facade.evaluate(session, await policy_facade.commercial_context(session,
        org_id=c.organization_id, professional_id=c.professional_id, action=policy_facade.PolicyAction.MILESTONE_ACCEPT,
        subject_type="Milestone", subject_id=m.id, actor_identity_id=None, amount=m.amount_minor, currency=m.currency,
        engagement_type=c.engagement_type, pinned_version_id=c.policy_version_id,
        platform_default_pinned=c.policy_version_id is None,
        extra={"contract.termsHash": c.terms_hash, "contract.version": c.contract_version,
               "milestone.submissionId": str(await session.scalar(select(Submission.id).where(Submission.milestone_id == m.id).order_by(Submission.created_at.desc()).limit(1)))}))
    if not decision.allowed:
        return
    m.status, m.accepted_at = "ACCEPTED", clock.now()
    _evt(session, E.MILESTONE_ACCEPTED, c, milestoneId=m.id, amountMinor=m.amount_minor, currency=m.currency,
        acceptedBy=None, onTime=m.due_date is None or m.submitted_at.date() <= m.due_date, auto=True)
    await session.flush()
    if all(x.status in ("ACCEPTED", "CANCELLED") for x in await _milestones(session, c.id)):
        CONTRACT_STATES.assert_can(c.status, "COMPLETED")
        c.status, c.completed_at = "COMPLETED", clock.now()
        _evt(session, E.CONTRACT_COMPLETED, c, reason="ALL_MILESTONES_ACCEPTED")


async def _require_decider(session: AsyncSession, actor: Actor, c: Contract, viewer: str) -> None:
    if viewer != "BUYER":
        raise Forbidden("Only the buyer reviews submitted work")
    if not (await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id)).intersection(DECIDERS):
        raise Forbidden("Reviewing work needs the Requester or Approver role in your organisation", code="ROLE_REQUIRED")


async def _accept(session: AsyncSession, m: Milestone, c: Contract, accepted_by: uuid.UUID, release_minor: int | None = None) -> None:
    """Accept a milestone; with ``release_minor`` (agreed partial acceptance) only that part is released, the rest refunded."""
    now = clock.now()
    MILESTONE_STATES.assert_can(m.status, "ACCEPTED")
    m.status, m.accepted_at, m.accepted_by = "ACCEPTED", now, accepted_by
    m.accepted_release_minor = release_minor
    m.partial_offer_minor = m.partial_offer_reason = m.partial_offered_at = None
    extra = {"releaseMinor": release_minor} if release_minor is not None else {}
    _evt(session, E.MILESTONE_ACCEPTED, c, milestoneId=m.id, amountMinor=m.amount_minor, currency=m.currency, acceptedBy=accepted_by,
         onTime=m.due_date is None or (m.submitted_at is not None and m.submitted_at.date() <= m.due_date), auto=False, **extra)
    await session.flush()
    if all(x.status in ("ACCEPTED", "CANCELLED") for x in await _milestones(session, c.id)):  # cancelled retainer cycles do not hold it open
        CONTRACT_STATES.assert_can(c.status, "COMPLETED")
        c.status, c.completed_at = "COMPLETED", now
        _evt(session, E.CONTRACT_COMPLETED, c, reason="ALL_MILESTONES_ACCEPTED")
        await session.flush()


async def accept_milestone(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID) -> ContractOut:
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    await _require_decider(session, actor, c, viewer)
    if m.status != "SUBMITTED":
        raise Conflict("Only submitted work can be accepted", code="MILESTONE_NOT_SUBMITTED")
    await policy_facade.require_allowed(session, await policy_facade.commercial_context(session,
        org_id=c.organization_id, professional_id=c.professional_id, action=policy_facade.PolicyAction.MILESTONE_ACCEPT,
        subject_type="Milestone", subject_id=m.id, actor_identity_id=actor.identity_id,
        amount=m.amount_minor, currency=m.currency, engagement_type=c.engagement_type,
        pinned_version_id=c.policy_version_id, platform_default_pinned=c.policy_version_id is None,
        extra={"contract.termsHash": c.terms_hash, "contract.version": c.contract_version,
            "milestone.submissionId": str(await session.scalar(select(Submission.id).where(Submission.milestone_id == m.id).order_by(Submission.created_at.desc()).limit(1)))}))
    await _accept(session, m, c, actor.identity_id)
    return await _out(session, actor, c, viewer)


async def offer_partial_acceptance(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, body: PartialOfferIn) -> ContractOut:
    """Buyer: accept this work for less, with a reason. Nothing moves until the professional agrees (no unilateral cut)."""
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    await _require_decider(session, actor, c, viewer)
    if m.status != "SUBMITTED":
        raise Conflict("Only submitted work can be accepted", code="MILESTONE_NOT_SUBMITTED")
    if body.amountMinor >= m.amount_minor:
        raise ValidationFailed("A partial acceptance must be less than the milestone amount; use Accept for the full amount",
                               code="NOT_PARTIAL")
    m.partial_offer_minor, m.partial_offer_reason, m.partial_offered_at = body.amountMinor, body.reason.strip(), clock.now()
    _evt(session, E.MILESTONE_PARTIAL_ACCEPTANCE_OFFERED, c, milestoneId=m.id, releaseMinor=body.amountMinor,
         refundMinor=m.amount_minor - body.amountMinor, currency=m.currency)
    await session.flush()
    return await _out(session, actor, c, viewer)


async def answer_partial_acceptance(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, agree: bool) -> ContractOut:
    """Professional: agree (that part is released, the rest refunded) or decline (the buyer accepts in full, asks for a revision
    or raises a dispute)."""
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    if viewer != "PROFESSIONAL":
        raise Forbidden("Only the professional answers a partial acceptance")
    if m.status != "SUBMITTED" or m.partial_offer_minor is None:
        raise Conflict("There is no partial acceptance waiting for your answer", code="NO_PARTIAL_OFFER")
    if agree:
        await _accept(session, m, c, actor.identity_id, release_minor=m.partial_offer_minor)
    else:
        _evt(session, E.MILESTONE_PARTIAL_ACCEPTANCE_DECLINED, c, milestoneId=m.id)
        m.partial_offer_minor = m.partial_offer_reason = m.partial_offered_at = None
        await session.flush()
    return await _out(session, actor, c, viewer)


async def request_revision(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, body: RevisionIn) -> ContractOut:
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    await _require_decider(session, actor, c, viewer)
    if m.status != "SUBMITTED":
        raise Conflict("Only submitted work can be sent back for revision", code="MILESTONE_NOT_SUBMITTED")
    MILESTONE_STATES.assert_can(m.status, "REVISION_REQUESTED")
    m.status, m.last_revision_reason = "REVISION_REQUESTED", body.reason.strip()
    m.partial_offer_minor = m.partial_offer_reason = m.partial_offered_at = None
    m.revision_count += 1
    _evt(session, E.MILESTONE_REVISION_REQUESTED, c, milestoneId=m.id, reason=m.last_revision_reason, revisionCount=m.revision_count)
    await session.flush()
    return await _out(session, actor, c, viewer)
