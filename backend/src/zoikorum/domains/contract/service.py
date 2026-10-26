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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.audit import facade as audit_facade
from zoikorum.domains.dispute import facade as dispute_facade
from zoikorum.domains.messaging import facade as messaging_facade
from zoikorum.domains.proposal import facade as proposal_facade
from zoikorum.domains.policy import facade as policy_facade
from zoikorum.domains.contract import delivery
from zoikorum.domains.contract.models import (
    ChangeOrder, Contract, ContractRevision, Milestone, Signature, Submission, SubmissionDraft, SubmissionReview,
    TerminationRequest,
)
from zoikorum.domains.contract.schemas import (
    AdminBuyerPartyOut, AdminContractOut, AdminContractSummaryOut, AdminMilestoneOut, AdminProfessionalPartyOut,
    PartialOfferIn, PartialOfferOut, ChangeOrderIn, ChangePreviewOut, ContractOut, ContractRevisionOut, ContractSummaryOut, MilestoneOut,
    DraftItemOut, DraftTextIn, EvidenceIn, EvidenceOut, IssueOut, PartyOut, ReviewIn, RevisionIn, SignatureOut, SignIn,
    SubmissionDraftOut, SubmissionItemOut, SubmissionOut, SubmissionReviewOut, SubmitIn, TerminateIn, TerminationDecisionIn,
    TerminationRequestOut,
)
from zoikorum.domains.escrow import facade as escrow_facade
from zoikorum.domains.firm import facade as firm_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock, pdf
from zoikorum.shared.auth import Actor, OrgRole
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.http import page_of, paginate
from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.relay import cancel_timer, schedule_timer
from zoikorum.shared.state_machine import StateMachine
from zoikorum.shared import uploads
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
TIMER_SIGNATURE = "contract.signature_deadline"
TIMER_SIGNATURE_EXPIRY = "contract.signature_expiry"  # a never-signed contract ends; nobody is left waiting forever"
TIMER_REVIEW_REMINDER = "contract.review_reminder"  # one day before the buyer's review window closes
TIMER_REVIEW_DUE = "contract.review_due"  # the review window has passed
TIMER_AUTO_ACCEPT = "contract.policy_auto_accept"
TIMER_TERMINATION_LAPSE = "contract.termination_lapse"  # an unanswered request to end by agreement closes
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
    if c.activated_at is None:
        return  # not signed yet: escrow opens at activation, so nothing can be funded
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
    if actor.has_capability(Cap.CONTRACTS_DETAIL_READ):
        actor.require_capability(Cap.CONTRACTS_DETAIL_READ)
        return "OPERATOR"
    raise NotFound("Contract not found")


# ---- Generation ---------------------------------------------------------------------------

def _buyer_line(buyer: dict) -> str:
    """The contracting party: the organisation's legal entity with its registration details when it has one."""
    e = buyer.get("legalEntity")
    if not e:
        return f"Buyer: {buyer['name']}, represented by {buyer['signatory']}."
    details = ", ".join(x for x in (f"registration no. {e['registrationNumber']}" if e.get("registrationNumber") else None,
                                    f"tax ID {e['taxId']}" if e.get("taxId") else None, e.get("registeredAddress"),
                                    e.get("country")) if x)
    return f"Buyer: {e['legalName']} ({details}), part of {buyer['name']}, represented by {buyer['signatory']}."


def render_document(c: Contract, milestones: list[Milestone]) -> str:
    """Plain-language agreement from the accepted terms and the platform template (Agreement Finalization s.10)."""
    t, p = c.terms, c.parties
    keys = {d["key"]: d["title"] for d in t.get("deliverables", [])}
    lines = [
        f"ENGAGEMENT AGREEMENT {c.reference} (version {c.contract_version})",
        "",
        "1. PARTIES",
        _buyer_line(p["buyer"]),
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
    success = t.get("successCriteria") or {}
    if success.get("definition") or success.get("measures"):
        lines.append(f"  Success criteria (what done looks like): {success.get('definition') or 'as measured below'}")
        lines += [f"  - Measured by: {m}" for m in success.get("measures") or []]
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
    lines += ["", "DATA HANDLING",
              "Each party uses personal data received for this engagement only to perform it, keeps it confidential and secure, "
              "and does not keep it longer than the engagement and its legal record-keeping require. Files shared through "
              "Zoikorum are stored encrypted, scanned for malware and kept with an audit record; each person can ask Zoikorum "
              "for a copy of, or the deletion of, their personal data (records the law requires are kept).",
              "", "STANDARD TERMS",
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
                           "country": org.country if org else None, "legalEntity": payload.get("buyerLegalEntity")},
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
    if c.activated_at is None:  # a new agreement (not an amendment): it lapses if it is still unsigned a period later
        await schedule_timer(session, TIMER_SIGNATURE_EXPIRY, str(c.id),
                             clock.now() + timedelta(days=get_settings().signature_deadline_days), {"contractId": str(c.id)})


async def signature_expired(session: AsyncSession, payload: dict) -> None:
    """Still unsigned a full period after the deadline: the agreement lapses (no money has moved: escrow opens only
    when both have signed), so the buyer can engage someone else and the professional is not held to it."""
    c = await session.get(Contract, uuid.UUID(payload["contractId"]), with_for_update=True)
    if c is None or c.status != "PENDING_SIGNATURE" or c.activated_at is not None:
        return
    CONTRACT_STATES.assert_can(c.status, "TERMINATED")
    c.status = "TERMINATED"
    for m in await _milestones(session, c.id, lock=True):
        if MILESTONE_STATES.can(m.status, "CANCELLED"):
            m.status = "CANCELLED"
    _evt(session, E.CONTRACT_TERMINATED, c, reason="SIGNATURE_EXPIRED")


async def funding_expired(session: AsyncSession, payload: dict) -> None:
    """Consumer of ESCROW_FUNDING_EXPIRED: the engagement was signed but never funded within the funding window. No work
    can have started (no work without funding) and no money was paid in, so it ends: its milestones are cancelled."""
    c = await session.get(Contract, uuid.UUID(str(payload["contractId"])), with_for_update=True)
    if c is None or c.status != "ACTIVE":
        return
    ms = await _milestones(session, c.id, lock=True)
    if any(m.started_at for m in ms):
        return  # funded at some point after all: the engagement carries on
    for m in ms:
        if MILESTONE_STATES.can(m.status, "CANCELLED"):
            m.status = "CANCELLED"
            await cancel_timer(session, TIMER_FUNDING_REMINDER, str(m.id))
    CONTRACT_STATES.assert_can(c.status, "TERMINATED")
    c.status = "TERMINATED"
    await _close_termination_request(session, c, "CANCELLED", "The engagement ended: it was never funded.")
    _evt(session, E.CONTRACT_TERMINATED, c, reason="FUNDING_EXPIRED")


# ---- Reads ------------------------------------------------------------------------------------

def awaiting_payment_protection(c: Contract, ms: list[Milestone]) -> bool:
    """Signed, but the first required funding is not in place yet: no milestone has ever started (work starts only when its
    money is held in escrow). The contract status stays ACTIVE (escrow funds only an active contract); this is the stage
    people see instead of "Active"."""
    return (c.status == "ACTIVE" and getattr(c, "activated_at", None) is not None and not any(getattr(m, "started_at", None) for m in ms)
            and any(m.status == "PENDING_FUNDING" for m in ms))


def _stage(c: Contract, ms: list[Milestone]) -> str:
    if c.status == "PENDING_SIGNATURE":
        return "AWAITING_SIGNATURES"
    if awaiting_payment_protection(c, ms):
        return "AWAITING_PAYMENT_PROTECTION"
    return c.status


def _next_action(c: Contract, ms: list[Milestone], signed: set[str], viewer: str, pro_name: str) -> str:
    if c.status == "PENDING_SIGNATURE":
        if "BUYER" not in signed:
            return "Review and sign the contract" if viewer == "BUYER" else "Waiting for the buyer to sign"
        return f"Waiting for {pro_name} to countersign" if viewer == "BUYER" else "Countersign the contract"
    if c.status == "COMPLETED":
        return "Completed — all milestones accepted"
    if c.status != "ACTIVE":
        return c.status.replace("_", " ").capitalize()
    if awaiting_payment_protection(c, ms):
        first = next(m for m in ms if m.status == "PENDING_FUNDING")
        return (f"Set up payment protection and fund M{first.sequence} to start work" if viewer == "BUYER"
                else f"Awaiting payment protection: do not start work until the buyer funds M{first.sequence}")
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


def _evidence_out(e: dict) -> EvidenceOut:
    if e["type"] == "FILE":
        return EvidenceOut(id=e["id"], type="FILE", file=file_out(e))
    return EvidenceOut(id=e["id"], type="LINK", url=e["url"], host=e.get("host"), provider=e.get("provider"), kind=e.get("kind"),
                       label=e.get("label", ""), version=e.get("version", ""))


def _submission_out(s: Submission, review: SubmissionReview | None) -> SubmissionOut:
    return SubmissionOut(
        id=s.id, note=s.note, files=[file_out(f) for f in s.files], submittedAt=s.created_at, revisionNumber=s.revision_number,
        items=[SubmissionItemOut(deliverableKey=i["deliverableKey"], title=i["title"], acceptanceCriteria=i["acceptanceCriteria"],
                                 note=i["note"], evidence=[_evidence_out(e) for e in i["evidence"]], carriedOver=i.get("carriedOver", False))
               for i in s.items],
        declaredAt=s.declaration.get("confirmedAt") if s.declaration else None, lateReason=s.late_reason,
        review=SubmissionReviewOut(verdicts=review.verdicts, outcome=review.outcome, reviewedAt=review.created_at) if review else None)


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
    reviews = {r.submission_id: r for r in (await session.scalars(select(SubmissionReview).where(
        SubmissionReview.submission_id.in_([s.id for s in subs])))).all()} if subs else {}
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
    can_end_now, can_request_end, termination = await _termination_view(session, actor, c, viewer)
    return ContractOut(
        id=c.id, reference=c.reference, proposalId=c.proposal_id, requestId=c.request_id, organizationId=c.organization_id,
        professionalId=c.professional_id, title=c.title, engagementType=c.engagement_type, pricingModel=c.pricing_model,
        status=c.status, stage=_stage(c, ms), pendingChangeOrderId=c.pending_change_order_id,
        total=MoneyDTO(amountMinor=c.total_minor, currency=c.currency), termsHash=c.terms_hash,
        contractVersion=c.contract_version,
        parties=[_buyer_party(p["buyer"]),
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
            submissions=[_submission_out(s, reviews.get(s.id)) for s in subs if s.milestone_id == m.id],
        ) for m in ms],
        viewerRole=viewer, nextAction=_next_action(c, ms, signed, viewer, p["professional"]["name"]), canSign=can_sign,
        acceptedAmount=MoneyDTO(amountMinor=accepted, currency=c.currency), pausedAt=c.paused_at, pauseReason=c.pause_reason,
        canEndNow=can_end_now,
        canRequestEnd=can_request_end, terminationRequest=termination, createdAt=c.created_at, version=c.version,
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


async def document_pdf(session: AsyncSession, actor: Actor, contract_id: uuid.UUID, version: int | None = None) -> tuple[bytes, str]:
    """The agreement as a PDF: the exact text whose SHA-256 is recorded (shown on every page), plus the signatures for
    that version. Same access rules and audit as the text (get_document)."""
    text, sha = await get_document(session, actor, contract_id, version)
    c = await _contract(session, contract_id)
    v = version or c.contract_version
    revision = await session.scalar(select(ContractRevision).where(ContractRevision.contract_id == c.id,
                                                                   ContractRevision.contract_version == v))
    signatures = (await session.scalars(select(Signature).where(Signature.contract_id == c.id, Signature.contract_version == v)
                                        .order_by(Signature.signed_at))).all()
    rows = [("Buyer" if s.party == "BUYER" else "Professional",
             f"{s.signer_name}, {s.signed_at:%d %B %Y %H:%M} UTC ({'two-step verified' if s.auth_strength == 'MFA' else s.auth_strength.lower()})")
            for s in signatures] or [("Status", "Not signed yet")]
    doc = pdf.PdfDocument(title="Engagement agreement", reference=c.reference, fingerprint=sha,
                          issued=revision.created_at if revision else c.created_at, subtitle=f"{c.title} · version {v}",
                          sections=[pdf.Section("Signatures", rows=rows), pdf.Section("Agreement", text=text)])
    record_audit(session, "contract.document.pdf_downloaded", object_type="Contract", object_id=c.id,
                 tenant_id=c.organization_id, evidence_hash=sha, details={"version": v})
    return pdf.render(doc), f"{c.reference}-v{v}.pdf"


async def _scope(session: AsyncSession, actor: Actor, role: str):
    if role == "buyer":
        # Live memberships only: someone removed from the organisation stops seeing its contracts at once (their sign-in
        # token may still list it for a few minutes, and having created a contract gives no lasting access).
        return Contract.organization_id.in_(await buyer_facade.list_identity_organizations(session, actor.identity_id))
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
    started = select(Milestone.contract_id).where(Milestone.started_at.is_not(None))
    awaiting = await session.scalar(select(func.count()).select_from(Contract).where(
        where, Contract.status == "ACTIVE", Contract.activated_at.is_not(None), Contract.id.not_in(started))) or 0
    milestones = dict((await session.execute(select(Milestone.status, func.count()).join(Contract, Contract.id == Milestone.contract_id)
                                             .where(where, Contract.status != "TERMINATED").group_by(Milestone.status))).all())
    return ContractSummaryOut(role=role, contracts=contracts, milestones=milestones, awaitingPaymentProtection=awaiting)


def _amendable(c: Contract) -> bool:
    """Before anyone signed the first version, or while active with no amendment waiting for signatures."""
    if c.status == "PENDING_SIGNATURE" and c.activated_at is None:
        return True
    return c.status == "ACTIVE" and c.pending_change_order_id is None


async def propose_change_order(
    session: AsyncSession, actor: Actor, contract_id: uuid.UUID, body: ChangeOrderIn
) -> ContractOut:
    c = await _contract(session, contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    if viewer == "OPERATOR":
        raise Forbidden("Only the contract parties can propose a change")
    if not _amendable(c):
        raise Conflict("A change can be proposed before the agreement is signed, or on an active contract with no amendment "
                       "awaiting signatures", code="CONTRACT_NOT_AMENDABLE")
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
    if not _amendable(c) or c.contract_version != change.base_contract_version:
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
    unsigned = c.activated_at is None  # agreed before anyone was bound: the new version simply replaces the draft
    _evt(session, E.CHANGE_ORDER_APPROVED, c, changeOrderId=change.id, decidedByIdentityId=actor.identity_id,
         contractVersion=c.contract_version, awaitingSignatures=material or unsigned)
    if unsigned:
        change.applied_version = c.contract_version  # both sign this version (signatures on the earlier one no longer count)
        c.signature_deadline = now + timedelta(days=get_settings().signature_deadline_days)
        await cancel_timer(session, TIMER_SIGNATURE, str(c.id))
        await schedule_timer(session, TIMER_SIGNATURE, str(c.id), c.signature_deadline, {"contractId": str(c.id)})
    elif material:
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
    if c.status == "ACTIVE" and c.paused_at is None:  # no reminders while a retainer is paused
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
    states = await escrow_facade.get_allocation_states_for_amendment(session, c.id, {m.id for m in future}) or {}
    paying = [m for m in future if states.get(m.id) == "FUNDING"]
    if paying:
        raise Conflict(f"A payment for M{paying[0].sequence} is still being processed. Cancel once it has finished or failed.",
                       code="PAYMENT_IN_PROGRESS")
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
    paused = False
    for m in await _milestones(session, c.id, lock=True):
        if m.id in ids and MILESTONE_STATES.can(m.status, "DISPUTED"):
            m.status = "DISPUTED"
            m.partial_offer_minor = m.partial_offer_reason = m.partial_offered_at = None
            paused = True
    if not paused:
        return  # only accepted work's payment is disputed (escrow holds it); the engagement carries on
    if c.status == "ACTIVE":
        c.status = "DISPUTED"
        _evt(session, E.CONTRACT_DISPUTED, c, disputeId=payload["disputeId"])
    await _close_termination_request(session, c, "CANCELLED", "A dispute was opened; it decides how the engagement ends.")


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
            days = next((a.get("extendDays") for a in payload.get("allocations", []) if str(a["milestoneId"]) == str(m.id)), None)
            if o == "EXTEND" and days:  # the decision gives more time: the milestone is due that much later
                m.due_date = (m.due_date or now.date()) + timedelta(days=int(days))
    for m in ms:
        if m.status == "CANCELLED" and outcomes.get(str(m.id)) == "CANCEL":
            _evt(session, E.MILESTONE_CANCELLED, c, milestoneId=m.id, reason="DISPUTE_DECISION")
    if payload.get("outcome") == "TERMINATION":
        for m in ms:
            if m.status in ("PENDING_FUNDING", "IN_PROGRESS", "SUBMITTED", "REVISION_REQUESTED"):
                m.status = "CANCELLED"
                _evt(session, E.MILESTONE_CANCELLED, c, milestoneId=m.id, reason="DISPUTE_DECISION")
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


# ---- Delivering work: a draft per milestone, item by item against the contract's deliverables -------------------------

async def _latest_submission(session: AsyncSession, milestone_id: uuid.UUID) -> Submission | None:
    return await session.scalar(select(Submission).where(Submission.milestone_id == milestone_id)
                                .order_by(Submission.created_at.desc()).limit(1))


def _deliverables(c: Contract, m: Milestone) -> list[dict]:
    return delivery.deliverables_for(c.terms, m.deliverable_keys, m.title, m.description)


def _previous_items(previous: Submission | None) -> list[dict] | None:
    return previous.items if previous is not None and previous.items else None


def _require_open_for_delivery(m: Milestone) -> None:
    if m.status == "PENDING_FUNDING":
        raise Conflict("This milestone is not funded yet; work starts after funding", code="NOT_FUNDED")
    if m.status not in ("IN_PROGRESS", "REVISION_REQUESTED"):
        raise Conflict("This milestone is not open for submission", code="MILESTONE_NOT_OPEN")


async def _delivery_ctx(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID) -> tuple[Milestone, Contract]:
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    if viewer != "PROFESSIONAL":
        raise Forbidden("Only the professional prepares a delivery")
    return m, c


async def _find_draft(session: AsyncSession, milestone_id: uuid.UUID) -> SubmissionDraft | None:
    return await session.scalar(select(SubmissionDraft).where(SubmissionDraft.milestone_id == milestone_id).with_for_update())


async def _editable_draft(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID) -> tuple[Milestone, Contract, SubmissionDraft]:
    """The draft to change, created on the first change. After the buyer asked for changes it starts from the last delivery."""
    m, c = await _delivery_ctx(session, actor, milestone_id)
    _require_open_for_delivery(m)
    d = await _find_draft(session, m.id)
    if d is None:
        previous = _previous_items(await _latest_submission(session, m.id))
        d = SubmissionDraft(milestone_id=m.id, professional_identity_id=actor.identity_id, note="",
                            items=delivery.seed_from(previous) if previous else {})
        session.add(d)
        await session.flush()
    return m, c, d


def _require_deliverable(c: Contract, m: Milestone, key: str) -> dict:
    found = next((d for d in _deliverables(c, m) if d["key"] == key), None)
    if found is None:
        raise ValidationFailed("This milestone has no such deliverable", code="UNKNOWN_DELIVERABLE")
    return found


async def _draft_out(session: AsyncSession, m: Milestone, c: Contract, d: SubmissionDraft | None) -> SubmissionDraftOut:
    previous = await _latest_submission(session, m.id)
    prev_items = _previous_items(previous)
    items = d.items if d is not None else (delivery.seed_from(prev_items) if prev_items else {})
    deliverables = _deliverables(c, m)
    blockers, warnings = delivery.check(deliverables, items, m.due_date, clock.now().date(), prev_items)
    asked: dict[str, str] = {}
    if previous is not None and m.status == "REVISION_REQUESTED":
        review = await session.scalar(select(SubmissionReview).where(SubmissionReview.submission_id == previous.id))
        asked = {v["deliverableKey"]: v["comment"] for v in (review.verdicts if review else []) if v["verdict"] == "CHANGES_REQUESTED"}
    count = await session.scalar(select(func.count()).select_from(Submission).where(Submission.milestone_id == m.id)) or 0
    return SubmissionDraftOut(
        milestoneId=m.id, revisionNumber=count, note=d.note if d is not None else "",
        items=[DraftItemOut(deliverableKey=x["key"], title=x["title"], acceptanceCriteria=x["acceptanceCriteria"],
                            note=(items.get(x["key"]) or {}).get("note", ""),
                            evidence=[_evidence_out(e) for e in (items.get(x["key"]) or {}).get("evidence", [])],
                            ready=bool((items.get(x["key"]) or {}).get("evidence")), changesRequested=asked.get(x["key"]))
               for x in deliverables],
        blockers=[IssueOut(**b) for b in blockers], warnings=[IssueOut(**w) for w in warnings], canSubmit=not blockers,
        declaration=delivery.DECLARATION, savedAt=d.updated_at if d is not None else None)


async def get_submission_draft(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID) -> SubmissionDraftOut:
    m, c = await _delivery_ctx(session, actor, milestone_id)
    return await _draft_out(session, m, c, await _find_draft(session, m.id))


async def save_draft_text(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, body: DraftTextIn) -> SubmissionDraftOut:
    m, c, d = await _editable_draft(session, actor, milestone_id)
    items = {k: dict(v) for k, v in d.items.items()}
    for key, note in body.itemNotes.items():
        _require_deliverable(c, m, key)
        items[key] = {"evidence": [], **items.get(key, {}), "note": note.strip()}
    d.items = items
    if body.note is not None:
        d.note = body.note.strip()
    d.updated_at = clock.now()
    await session.flush()
    return await _draft_out(session, m, c, d)


async def add_evidence(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, key: str, body: EvidenceIn) -> SubmissionDraftOut:
    """A file (stored at once, checked like every upload) or a link, recognised from its address. Never fetched."""
    if (body.file is None) == (not (body.url or "").strip()):
        raise ValidationFailed("Add either a file or a link", code="EVIDENCE_REQUIRED")
    m, c, d = await _editable_draft(session, actor, milestone_id)
    _require_deliverable(c, m, key)
    items = {k: dict(v) for k, v in d.items.items()}
    item = {"note": "", **items.get(key, {})}
    evidence = list(item.get("evidence", []))
    if len(evidence) >= delivery.MAX_EVIDENCE_PER_ITEM:
        raise Conflict(f"Up to {delivery.MAX_EVIDENCE_PER_ITEM} files or links per deliverable", code="TOO_MUCH_EVIDENCE")
    now = clock.now()
    if body.file is not None:
        if any(e["type"] == "FILE" and e["sha256"] == body.file.sha256 for e in evidence):
            return await _draft_out(session, m, c, d)  # the same file again: nothing to add
        evidence.append(delivery.file_record(store_uploads(f"contracts/{c.id}/{m.id}", [body.file])[0], now))
    else:
        link = delivery.link_record(body.url or "", body.label, body.version, now)
        if any(e["type"] == "LINK" and e["url"] == link["url"] and e.get("version") == link["version"] for e in evidence):
            return await _draft_out(session, m, c, d)
        evidence.append(link)
    items[key] = {**item, "evidence": evidence}
    d.items, d.updated_at = items, now
    await session.flush()
    return await _draft_out(session, m, c, d)


async def remove_evidence(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, key: str, evidence_id: str) -> SubmissionDraftOut:
    m, c, d = await _editable_draft(session, actor, milestone_id)
    items = {k: dict(v) for k, v in d.items.items()}
    evidence = (items.get(key) or {}).get("evidence", [])
    if not any(e["id"] == evidence_id for e in evidence):
        raise NotFound("That file or link is not in this delivery")
    items[key] = {**items[key], "evidence": [e for e in evidence if e["id"] != evidence_id]}
    d.items, d.updated_at = items, clock.now()
    await session.flush()
    return await _draft_out(session, m, c, d)


async def discard_draft(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID) -> SubmissionDraftOut:
    m, c = await _delivery_ctx(session, actor, milestone_id)
    d = await _find_draft(session, m.id)
    if d is not None:
        await session.delete(d)
        await session.flush()
    return await _draft_out(session, m, c, None)


async def draft_file(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, sha256: str) -> tuple[bytes, str | None, str]:
    """A file in the professional's own draft. The buyer never sees a draft."""
    m, _ = await _delivery_ctx(session, actor, milestone_id)
    d = await _find_draft(session, m.id)
    files = [e for item in (d.items.values() if d else []) for e in item.get("evidence", []) if e["type"] == "FILE"]
    rec = find_file(files, sha256)
    return read_file(rec), rec.get("contentType"), rec["name"]


def _stored(e: dict) -> dict:
    return {k: e[k] for k in ("name", "sha256", "size", "contentType", "key", "versionId") if k in e}


async def submit_milestone(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, body: SubmitIn, ip: str | None = None) -> ContractOut:
    """Sends the saved draft (every deliverable needs evidence, and the professional confirms the declaration). Without a
    draft, a note and files are still accepted in one step for the whole milestone."""
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    if viewer != "PROFESSIONAL":
        raise Forbidden("Only the professional submits work")
    _require_open_for_delivery(m)
    now = clock.now()
    draft = await _find_draft(session, m.id)
    previous = await _latest_submission(session, m.id)
    revision = await session.scalar(select(func.count()).select_from(Submission).where(Submission.milestone_id == m.id)) or 0
    late_reason = (body.lateReason or "").strip() or None
    if draft is not None:
        if body.note.strip() or body.files:
            raise Conflict("You have a delivery in progress. Send it, or discard it first.", code="DRAFT_IN_PROGRESS")
        deliverables, prev_items = _deliverables(c, m), _previous_items(previous)
        blockers, _ = delivery.check(deliverables, draft.items, m.due_date, now.date(), prev_items)
        if blockers:
            raise Conflict(" · ".join(b["message"] for b in blockers), code="DELIVERY_INCOMPLETE", extra={"blockers": blockers})
        if not body.confirmed:
            raise Conflict("Confirm that the work meets the agreed acceptance criteria before sending", code="DECLARATION_REQUIRED")
        items = delivery.frozen_items(deliverables, draft.items, prev_items)
        files = list({e["sha256"]: _stored(e) for i in items for e in i["evidence"] if e["type"] == "FILE"}.values())
        sub = Submission(milestone_id=m.id, submitted_by=actor.identity_id, note=draft.note.strip(), files=files, items=items,
                         revision_number=revision, late_reason=late_reason,
                         declaration={"text": delivery.DECLARATION, "confirmedAt": now.isoformat(), "ip": ip})
        await session.delete(draft)
    else:
        if not body.note.strip() and not body.files:
            raise Conflict("Add a note or at least one file describing what you delivered", code="EMPTY_SUBMISSION")
        sub = Submission(milestone_id=m.id, submitted_by=actor.identity_id, note=body.note.strip(), revision_number=revision,
                         late_reason=late_reason, files=store_uploads(f"contracts/{c.id}/{m.id}", body.files))
    session.add(sub)
    await session.flush()
    MILESTONE_STATES.assert_can(m.status, "SUBMITTED")
    m.status, m.submitted_at = "SUBMITTED", now
    m.acceptance_due_at = now + timedelta(days=c.terms.get("policySettings", {}).get("acceptanceWindowDays", get_settings().acceptance_window_days))
    _evt(session, E.MILESTONE_SUBMITTED, c, milestoneId=m.id, submissionId=sub.id, acceptanceDueAt=m.acceptance_due_at,
         revisionNumber=revision, itemCount=len(sub.items))
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
    if m.partial_offer_minor is not None:  # the buyer offered to accept part of it: wait for that answer, then try again
        await schedule_timer(session, TIMER_AUTO_ACCEPT, f"{payload['submissionId']}:{clock.now().date().isoformat()}",
                             clock.now() + timedelta(days=1), payload)
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
    await _accept_as_buyer(session, actor, m, c)
    return await _out(session, actor, c, viewer)


async def _accept_as_buyer(session: AsyncSession, actor: Actor, m: Milestone, c: Contract) -> None:
    """The organisation's policy decides first (it may need an approval); then the milestone is accepted."""
    await policy_facade.require_allowed(session, await policy_facade.commercial_context(session,
        org_id=c.organization_id, professional_id=c.professional_id, action=policy_facade.PolicyAction.MILESTONE_ACCEPT,
        subject_type="Milestone", subject_id=m.id, actor_identity_id=actor.identity_id,
        amount=m.amount_minor, currency=m.currency, engagement_type=c.engagement_type,
        pinned_version_id=c.policy_version_id, platform_default_pinned=c.policy_version_id is None,
        extra={"contract.termsHash": c.terms_hash, "contract.version": c.contract_version,
            "milestone.submissionId": str(await session.scalar(select(Submission.id).where(Submission.milestone_id == m.id).order_by(Submission.created_at.desc()).limit(1)))}))
    await _accept(session, m, c, actor.identity_id)


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
    await _send_back(session, m, c, body.reason.strip())
    return await _out(session, actor, c, viewer)


async def _send_back(session: AsyncSession, m: Milestone, c: Contract, reason: str) -> None:
    MILESTONE_STATES.assert_can(m.status, "REVISION_REQUESTED")
    m.status, m.last_revision_reason = "REVISION_REQUESTED", reason
    m.partial_offer_minor = m.partial_offer_reason = m.partial_offered_at = None
    m.revision_count += 1
    _evt(session, E.MILESTONE_REVISION_REQUESTED, c, milestoneId=m.id, reason=m.last_revision_reason, revisionCount=m.revision_count)
    await session.flush()


async def review_submission(session: AsyncSession, actor: Actor, milestone_id: uuid.UUID, body: ReviewIn) -> ContractOut:
    """Buyer: a verdict on each deliverable of the latest delivery. All met: the milestone is accepted (the organisation's
    policy still decides first). Anything not met: it goes back to the professional with one comment per item."""
    m, c, viewer = await _milestone_ctx(session, actor, milestone_id)
    await _require_decider(session, actor, c, viewer)
    if m.status != "SUBMITTED":
        raise Conflict("Only submitted work can be reviewed", code="MILESTONE_NOT_SUBMITTED")
    sub = await _latest_submission(session, m.id)
    if sub is None:
        raise Conflict("Nothing has been delivered yet", code="MILESTONE_NOT_SUBMITTED")
    titles = {i["deliverableKey"]: i["title"] for i in sub.items} or {d["key"]: d["title"] for d in _deliverables(c, m)}
    given = [v.deliverableKey for v in body.verdicts]
    if sorted(given) != sorted(titles) or len(set(given)) != len(given):
        raise ValidationFailed("Give one verdict for each deliverable in this delivery", code="VERDICTS_INCOMPLETE")
    if any(v.verdict == "CHANGES_REQUESTED" and len(v.comment.strip()) < 5 for v in body.verdicts):
        raise ValidationFailed("Say what needs to change for each item you send back", code="COMMENT_REQUIRED")
    if await session.scalar(select(SubmissionReview.id).where(SubmissionReview.submission_id == sub.id)):
        raise Conflict("This delivery has already been reviewed", code="ALREADY_REVIEWED")
    verdicts = [{"deliverableKey": v.deliverableKey, "verdict": v.verdict, "comment": v.comment.strip()} for v in body.verdicts]
    changes = [v for v in verdicts if v["verdict"] == "CHANGES_REQUESTED"]
    outcome = "REVISION_REQUESTED" if changes else "ACCEPTED"
    if changes:
        await _send_back(session, m, c, "; ".join(f"{titles[v['deliverableKey']]}: {v['comment']}" for v in changes)[:1000])
    else:
        await _accept_as_buyer(session, actor, m, c)
    session.add(SubmissionReview(submission_id=sub.id, milestone_id=m.id, reviewer_identity_id=actor.identity_id,
                                 verdicts=verdicts, outcome=outcome))
    record_audit(session, "contract.submission.reviewed", object_type="Milestone", object_id=m.id, tenant_id=c.organization_id,
                 policy_version=c.policy_version_label,
                 details={"contractId": str(c.id), "submissionId": str(sub.id), "outcome": outcome,
                          "met": len(verdicts) - len(changes), "changesRequested": len(changes)})
    await session.flush()
    return await _out(session, actor, c, viewer)


def _buyer_party(buyer: dict) -> PartyOut:
    """The contracting legal entity when the organisation has one, with the organisation and signatory below it."""
    e = buyer.get("legalEntity")
    if not e:
        return PartyOut(role="BUYER", name=buyer["name"], detail=f"Signatory: {buyer['signatory']}")
    reg = f" · Reg. no. {e['registrationNumber']}" if e.get("registrationNumber") else ""
    return PartyOut(role="BUYER", name=e["legalName"], detail=f"{buyer['name']}{reg} · Signatory: {buyer['signatory']}")


# ---- Ending an engagement ------------------------------------------------------------------------------------------
# Either side may end it at once while nothing is in escrow and no dispute is open (e.g. before any funding, or after
# the last funded milestone was paid). While money is held, the other side must agree; held money for work not accepted
# goes back to the buyer and accepted work is still paid (escrow consumer of CONTRACT_TERMINATED). A disputed
# engagement is never ended by one side: the dispute decides (Architecture: contract invariants).

OPEN_MILESTONES = ("PENDING_FUNDING", "IN_PROGRESS", "SUBMITTED", "REVISION_REQUESTED", "ACCEPTANCE_PENDING_APPROVAL")


async def _pending_termination(session: AsyncSession, c: Contract, lock: bool = False) -> TerminationRequest | None:
    stmt = select(TerminationRequest).where(TerminationRequest.contract_id == c.id, TerminationRequest.status == "PENDING")
    return await session.scalar(stmt.with_for_update() if lock else stmt)


async def _may_end(session: AsyncSession, actor: Actor, c: Contract, viewer: str) -> bool:
    """The viewer may speak for their side: the professional, or a Requester/Approver of the buyer organisation."""
    if viewer == "PROFESSIONAL":
        return True
    return viewer == "BUYER" and bool(
        (await buyer_facade.get_member_roles(session, c.organization_id, actor.identity_id)).intersection(DECIDERS))


async def _termination_view(session: AsyncSession, actor: Actor, c: Contract, viewer: str):
    pending = await _pending_termination(session, c)
    latest = pending or await session.scalar(select(TerminationRequest).where(TerminationRequest.contract_id == c.id)
                                             .order_by(TerminationRequest.created_at.desc()).limit(1))
    speaks = c.status in ("ACTIVE", "PENDING_SIGNATURE") and await _may_end(session, actor, c, viewer)
    held = await escrow_facade.money_in_escrow(session, c.id) if speaks else True
    can_end_now = speaks and not held and pending is None
    can_request_end = speaks and c.status == "ACTIVE" and held and pending is None
    out = None
    if latest is not None and (latest.status == "PENDING" or c.status in ("ACTIVE", "TERMINATED")):
        out = TerminationRequestOut(
            id=latest.id, requesterParty=latest.requester_party, reason=latest.reason, status=latest.status,
            expiresAt=latest.expires_at, decisionNote=latest.decision_note, decidedAt=latest.decided_at,
            createdAt=latest.created_at,
            canAnswer=latest.status == "PENDING" and speaks and viewer != latest.requester_party,
            canWithdraw=latest.status == "PENDING" and speaks and viewer == latest.requester_party)
    return can_end_now, can_request_end, out


async def _end(session: AsyncSession, c: Contract, reason: str, **extra) -> None:
    """Close the open milestones and the contract; escrow refunds what is held for work not accepted."""
    CONTRACT_STATES.assert_can(c.status, "TERMINATED")
    for m in await _milestones(session, c.id, lock=True):
        if m.status in OPEN_MILESTONES:
            m.status = "CANCELLED"
            m.partial_offer_minor = m.partial_offer_reason = m.partial_offered_at = None
            await cancel_timer(session, TIMER_FUNDING_REMINDER, str(m.id))
            _evt(session, E.MILESTONE_CANCELLED, c, milestoneId=m.id, reason=reason)
    c.status = "TERMINATED"
    if c.pending_change_order_id:  # an amendment waiting for signatures no longer applies
        change = await session.get(ChangeOrder, c.pending_change_order_id, with_for_update=True)
        if change is not None and change.status == "PROPOSED":
            change.status, change.decided_at, change.decision_reason = "REJECTED", clock.now(), "The engagement ended."
        c.pending_change_order_id = None
    await cancel_timer(session, TIMER_SIGNATURE, str(c.id))
    await cancel_timer(session, TIMER_SIGNATURE_EXPIRY, str(c.id))
    _evt(session, E.CONTRACT_TERMINATED, c, reason=reason, **extra)


async def _close_termination_request(session: AsyncSession, c: Contract, status: str, note: str,
                                     by: uuid.UUID | None = None) -> TerminationRequest | None:
    req = await _pending_termination(session, c, lock=True)
    if req is None:
        return None
    req.status, req.decision_note, req.decided_at, req.decided_by_identity_id = status, note, clock.now(), by
    await cancel_timer(session, TIMER_TERMINATION_LAPSE, str(req.id))
    if status in ("WITHDRAWN", "LAPSED", "CANCELLED"):
        _evt(session, E.CONTRACT_TERMINATION_WITHDRAWN, c, requestId=req.id, outcome=status)
    return req


async def terminate(session: AsyncSession, actor: Actor, contract_id: uuid.UUID, body: TerminateIn) -> ContractOut:
    """End now (nothing in escrow, no dispute) or ask the other side to agree (``mutual``). Needs a fresh two-step
    confirmation: it changes what happens to money."""
    c = await _contract(session, contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    if not await _may_end(session, actor, c, viewer):
        raise Forbidden("Ending an engagement needs the professional, or the Requester or Approver role in the buyer "
                        "organisation", code="ROLE_REQUIRED")
    if c.status == "DISPUTED":
        raise Conflict("A dispute is open: the dispute decides how this engagement ends", code="CONTRACT_DISPUTED")
    if c.status not in ("ACTIVE", "PENDING_SIGNATURE"):
        raise Conflict("This engagement has already ended", code="CONTRACT_CLOSED")
    actor.require_step_up()
    if await _pending_termination(session, c, lock=True):
        raise Conflict("A request to end this engagement is already waiting for an answer", code="TERMINATION_PENDING")
    reason = body.reason.strip()
    held = await escrow_facade.money_in_escrow(session, c.id)
    if not body.mutual:
        if held:
            raise Conflict("Money is held in escrow for this engagement, so ending it needs the other side's agreement. "
                           "Send them a request to end it instead.", code="MONEY_IN_ESCROW")
        await _end(session, c, "ENDED_BY_" + viewer, endedBy=actor.identity_id, note=reason)
        record_audit(session, "contract.terminated", object_type="Contract", object_id=c.id, tenant_id=c.organization_id,
                     details={"party": viewer, "reason": reason})
        await session.flush()
        return await _out(session, actor, c, viewer)
    if c.status != "ACTIVE":
        raise Conflict("Only an active engagement can be ended by agreement; an unsigned agreement can simply be ended",
                       code="CONTRACT_NOT_ACTIVE")
    req = TerminationRequest(contract_id=c.id, requested_by_identity_id=actor.identity_id, requester_party=viewer,
                             reason=reason, status="PENDING",
                             expires_at=clock.now() + timedelta(days=get_settings().termination_response_days))
    session.add(req)
    await session.flush()
    await schedule_timer(session, TIMER_TERMINATION_LAPSE, str(req.id), req.expires_at, {"requestId": str(req.id)})
    _evt(session, E.CONTRACT_TERMINATION_REQUESTED, c, requestId=req.id, requesterParty=viewer, reason=reason,
         expiresAt=req.expires_at)
    return await _out(session, actor, c, viewer)


async def decide_termination(session: AsyncSession, actor: Actor, contract_id: uuid.UUID,
                             body: TerminationDecisionIn) -> ContractOut:
    """The other side agrees (the engagement ends now) or declines (it continues)."""
    c = await _contract(session, contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    req = await _pending_termination(session, c, lock=True)
    if req is None:
        raise Conflict("There is no request to end this engagement waiting for an answer", code="NO_TERMINATION_REQUEST")
    if not await _may_end(session, actor, c, viewer) or viewer == req.requester_party:
        raise Forbidden("Only the other side can answer this request", code="NOT_THE_OTHER_SIDE")
    actor.require_step_up()
    note = (body.note or "").strip() or None
    if body.agree:
        if c.status != "ACTIVE":
            raise Conflict("The engagement is no longer active", code="CONTRACT_NOT_ACTIVE")
        req.status, req.decision_note, req.decided_at, req.decided_by_identity_id = "AGREED", note, clock.now(), actor.identity_id
        await cancel_timer(session, TIMER_TERMINATION_LAPSE, str(req.id))
        await _end(session, c, "MUTUAL_AGREEMENT", requestId=req.id, requesterParty=req.requester_party,
                   agreedBy=actor.identity_id)
    else:
        req.status, req.decision_note, req.decided_at, req.decided_by_identity_id = "DECLINED", note, clock.now(), actor.identity_id
        await cancel_timer(session, TIMER_TERMINATION_LAPSE, str(req.id))
        _evt(session, E.CONTRACT_TERMINATION_DECLINED, c, requestId=req.id, note=note)
    await session.flush()
    return await _out(session, actor, c, viewer)


async def withdraw_termination(session: AsyncSession, actor: Actor, contract_id: uuid.UUID) -> ContractOut:
    c = await _contract(session, contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    req = await _pending_termination(session, c, lock=True)
    if req is None:
        raise Conflict("There is no request to end this engagement waiting for an answer", code="NO_TERMINATION_REQUEST")
    if not await _may_end(session, actor, c, viewer) or viewer != req.requester_party:
        raise Forbidden("Only the side that asked can withdraw the request", code="NOT_THE_REQUESTER")
    await _close_termination_request(session, c, "WITHDRAWN", "Withdrawn by the side that asked.", actor.identity_id)
    await session.flush()
    return await _out(session, actor, c, viewer)


async def termination_lapsed(session: AsyncSession, payload: dict) -> None:
    req = await session.get(TerminationRequest, uuid.UUID(payload["requestId"]))
    if req is None or req.status != "PENDING":
        return
    c = await _contract(session, req.contract_id, lock=True)
    await _close_termination_request(session, c, "LAPSED", "Not answered in time; the engagement continues.")


async def professional_offboarded(session: AsyncSession, professional_id: uuid.UUID) -> None:
    """Exit governance: when a professional is offboarded, their engagements do not stay open. Unsigned and active
    engagements end (accepted work is still paid, held money for other work goes back to the buyer); disputed ones
    continue through their dispute, which decides the money."""
    contracts = (await session.scalars(select(Contract).where(
        Contract.professional_id == professional_id, Contract.status.in_(("ACTIVE", "PENDING_SIGNATURE")))
        .with_for_update())).all()
    for c in contracts:
        await _close_termination_request(session, c, "CANCELLED", "The professional was offboarded.")
        await _end(session, c, "PROFESSIONAL_OFFBOARDED")


# ---- Telling buyers about changes to their professional ---------------------------------------------------------------

SUSPENSIONS = {
    "SUSPEND_ACCOUNT": "{name}'s account is suspended after a Trust & Safety decision, so they cannot work on engagements for now.",
    "ENGAGEMENT_SUSPENSION": "{name} cannot take part in engagements for now after a Trust & Safety decision.",
    "CREDENTIAL_ENFORCEMENT": "A credential {name} relied on was withdrawn after a Trust & Safety review.",
    "VERIFICATION_RESET": "{name}'s verification has to be done again after a Trust & Safety review.",
}
WHAT_NEXT = ("Money held in escrow stays protected: nothing is released without your acceptance. Pause new work, raise a "
             "dispute about delivered work, or end the engagement by agreement from the engagement page.")


async def tell_buyers(session: AsyncSession, professional_id: uuid.UUID, change: str, message: str) -> int:
    """One notice per open engagement of this professional, to the buyer organisation only."""
    contracts = (await session.scalars(select(Contract).where(
        Contract.professional_id == professional_id,
        Contract.status.in_(("PENDING_SIGNATURE", "ACTIVE", "DISPUTED"))))).all()
    for c in contracts:
        _evt(session, E.CONTRACT_PROFESSIONAL_STATUS_CHANGED, c, change=change, message=message, buyersOnly=True)
    return len(contracts)


async def professional_restricted(session: AsyncSession, payload: dict, reversed_: bool = False) -> None:
    action = payload.get("action")
    if action not in SUSPENSIONS:  # every one of these changes whether the professional can work on engagements
        return
    subject = uuid.UUID(str(payload["subjectId"]))
    pro = (await professional_facade.get_professional(session, subject) if payload.get("subjectType") == "PROFESSIONAL"
           else await professional_facade.get_professional_by_identity(session, subject)
           if payload.get("subjectType") == "IDENTITY" else None)
    if pro is None:
        return
    if reversed_:
        await tell_buyers(session, pro.id, "RESTRICTION_LIFTED",
                          f"The restriction on {pro.display_name} has ended; they can work on your engagement again.")
    else:
        await tell_buyers(session, pro.id, action, SUSPENSIONS[action].format(name=pro.display_name) + " " + WHAT_NEXT)


CHECK_LABEL = {"IDENTITY": "identity check", "CREDENTIAL": "credential", "INSURANCE": "insurance",
               "JURISDICTION": "right to practise", "RESTRICTIONS": "restrictions screening", "BACKGROUND": "background check"}


async def professional_check_lapsed(session: AsyncSession, payload: dict, expired: bool) -> None:
    if payload.get("subjectType") != "PROFESSIONAL":
        return
    pro = await professional_facade.get_professional(session, uuid.UUID(str(payload["subjectId"])))
    if pro is None:
        return
    what = CHECK_LABEL.get(payload.get("verificationType"), "verification")
    label = f" ({payload['label']})" if payload.get("label") and payload.get("verificationType") == "CREDENTIAL" else ""
    how = "has expired" if expired else "is no longer verified"
    await tell_buyers(session, pro.id, "CHECK_EXPIRED" if expired else "CHECK_REVOKED",
                      f"{pro.display_name}'s {what}{label} {how}. Check whether your engagement or your organisation's "
                      f"policy needs it before more work is delivered. {WHAT_NEXT}")


# ---- Engagement record: activity, files, evidence pack -------------------------------------------------------------

def _plain(action: str) -> str:
    """'zoikorum.contract.milestone.accepted.v1' -> 'Milestone accepted'; 'contract.terminated' -> 'Contract terminated'."""
    parts = action.split(".")
    if parts[0] == "zoikorum" and len(parts) >= 5:
        words = [parts[2], parts[3]]
    else:
        words = parts[-2:] if len(parts) >= 2 else parts
    text = " ".join(w.replace("_", " ") for w in words)
    return text[:1].upper() + text[1:]


async def _subject_ids(session: AsyncSession, c: Contract) -> list[uuid.UUID]:
    """The engagement's own records: request, proposal, contract, milestones and its escrow account."""
    ids = [c.id, c.proposal_id, c.request_id] + [m.id for m in await _milestones(session, c.id)]
    account = await escrow_facade.account_id_for_contract(session, c.id)
    return ids + ([account] if account else [])


async def _record_ids(session: AsyncSession, c: Contract, include_policy: bool = True) -> list[str]:
    """Objects whose audit rows make up the engagement's activity: its own records, its disputes and, for the buyer
    organisation, its policy approval and exception requests (the buyer's internal authorisations)."""
    subjects = await _subject_ids(session, c)
    ids = [str(i) for i in subjects]
    ids += [d["id"] for d in await dispute_facade.disputes_for_contract(session, c.id)]
    if include_policy:
        ids += await policy_facade.record_ids(session, c.organization_id, subjects)
    return ids


async def activity(session: AsyncSession, actor: Actor, contract_id: uuid.UUID) -> list[dict]:
    """The engagement's history from the tamper-evident audit trail (each line carries its chain hash)."""
    c = await _contract(session, contract_id)
    viewer = await _viewer(session, actor, c)
    entries = await audit_facade.timeline_for_objects(session, await _record_ids(session, c, include_policy=viewer == "BUYER"))
    people = await identity_facade.get_identities(session, [uuid.UUID(e.actor_id) for e in entries
                                                            if e.actor_id and _is_uuid(e.actor_id)])
    return [{"at": e.occurred_at, "what": _plain(e.action), "action": e.action,
             "by": people[uuid.UUID(e.actor_id)].display_name if e.actor_id and _is_uuid(e.actor_id)
             and uuid.UUID(e.actor_id) in people else ("Zoikorum" if not e.actor_id else "System"),
             "hash": e.hash} for e in entries]


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


async def files(session: AsyncSession, actor: Actor, contract_id: uuid.UUID) -> list[dict]:
    """Every file of the engagement in one place: request, proposal, delivered work, messages, dispute evidence."""
    c = await _contract(session, contract_id)
    await _viewer(session, actor, c)
    refs = await proposal_facade.files_for(session, c.request_id, c.proposal_id)
    for m in await _milestones(session, c.id):
        for s in (await session.scalars(select(Submission).where(Submission.milestone_id == m.id)
                                        .order_by(Submission.created_at))).all():
            refs += [uploads.FileRef(f"Delivered work (M{m.sequence})", f["name"], f["sha256"], int(f.get("size", 0)),
                                     s.created_at, f"/v1/contracts/{c.id}/files/{f['sha256']}") for f in s.files]
    refs += await messaging_facade.files_for_contexts(session, [("PROPOSAL_REQUEST", c.request_id), ("CONTRACT", c.id)])
    refs += await dispute_facade.files_for_contract(session, c.id)
    return [{"source": f.source, "name": f.name, "sha256": f.sha256, "size": f.size, "uploadedAt": f.uploaded_at,
             "url": f.url} for f in refs]


async def evidence_pack(session: AsyncSession, actor: Actor, contract_id: uuid.UUID, fmt: str) -> tuple[bytes, str, str]:
    """The engagement record as one attested document (PDF, JSON or CSV): parties, agreement versions and their hashes,
    signatures, milestones and acceptance, escrow ledger, disputes, files with fingerprints, eligibility evidence, the
    buyer's approval log and exception history (buyer's pack only), and the audit timeline.
    The SHA-256 of the record is printed on every page and recorded with the download."""
    c = await _contract(session, contract_id)
    viewer = await _viewer(session, actor, c)
    out = await _out(session, actor, c, viewer)
    record = {
        "engagement": {"reference": c.reference, "title": c.title, "status": c.status, "policy": c.policy_version_label,
                       "total": {"amountMinor": c.total_minor, "currency": c.currency}},
        "parties": [p.model_dump() for p in out.parties],
        "versions": [{"version": r.contractVersion, "termsHash": r.termsHash, "documentSha256": r.documentSha256,
                      "createdAt": r.createdAt.isoformat()} for r in out.revisions],
        "signatures": [{"party": s.party, "signer": s.signerName, "version": s.contractVersion, "termsHash": s.termsHash,
                        "authStrength": s.authStrength, "signedAt": s.signedAt.isoformat()} for s in out.signatures],
        "milestones": [{"sequence": m.sequence, "title": m.title, "amountMinor": m.amount.amountMinor, "status": m.status,
                        "acceptedAt": m.acceptedAt.isoformat() if m.acceptedAt else None} for m in out.milestones],
        "escrowLedger": await escrow_facade.ledger_for_contract(session, c.id),
        "disputes": await dispute_facade.disputes_for_contract(session, c.id),
        "files": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in f.items() if k != "url"}
                  for f in await files(session, actor, c.id)],
        "activity": [{"at": a["at"].isoformat(), "what": a["what"], "by": a["by"], "hash": a["hash"]}
                     for a in await activity(session, actor, c.id)],
    }
    # Policy evidence: eligibility checks for both parties; the approval log and exception history are the buyer
    # organisation's internal authorisations, so only its own pack carries them.
    policy = await policy_facade.engagement_evidence(session, c.organization_id, await _subject_ids(session, c))
    record["eligibility"] = policy["eligibility"]
    if viewer == "BUYER":
        record["approvalLog"], record["exceptionHistory"] = policy["approvals"], policy["exceptions"]
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    fingerprint = hashlib.sha256(body.encode()).hexdigest()
    record_audit(session, "contract.evidence_pack.downloaded", object_type="Contract", object_id=c.id,
                 tenant_id=c.organization_id, evidence_hash=fingerprint, details={"format": fmt})
    name = f"{c.reference}-evidence-pack"
    if fmt == "json":
        return (json.dumps({"fingerprintSha256": fingerprint, "record": record}, indent=2, default=str).encode(),
                f"{name}.json", "application/json")
    if fmt == "csv":
        return _evidence_csv(c, record, fingerprint), f"{name}.csv", "text/csv; charset=utf-8"
    money = lambda m: pdf.money(m, c.currency)  # noqa: E731
    approval_rows = [(f"{a['requestedAt'][:10]} {a['action'].replace('_', ' ').lower()}",
                      f"{a['status'].lower()}" + "".join(f" · {v['by']} ({v['role'].replace('_', ' ').lower()}) {v['decision'].lower()}: {v['reason']}"
                                                         for v in a["votes"])) for a in record.get("approvalLog", [])]
    exception_rows = [(f"{x['requestedAt'][:10]} {x['action'].replace('_', ' ').lower()}" + (" (emergency)" if x["emergency"] else ""),
                       f"{x['status'].lower()}" + (f" · {x['decidedBy']}: {x['decisionReason']}" if x["decidedBy"] else "")
                       + f" · until {x['expiresAt'][:10]}") for x in record.get("exceptionHistory", [])]
    eligibility_rows = [(f"{e['at'][:10]} {e['action'].replace('_', ' ').lower()}",
                         f"{e['decision'].lower()} · tier {e['professionalTier'] or '—'} · "
                         + (", ".join(f"{k} {v.lower()}" for k, v in sorted(e["dimensions"].items())) or "no checks recorded")
                         + f" · {e['policy']}") for e in record["eligibility"]]
    policy_sections = [pdf.Section("Eligibility evidence (policy checks)", rows=eligibility_rows or [("None recorded", "")])]
    if viewer == "BUYER":
        policy_sections += [pdf.Section("Approval log", rows=approval_rows or [("No approvals were needed", "")]),
                            pdf.Section("Exception history", rows=exception_rows or [("No exceptions", "")])]
    doc = pdf.PdfDocument(
        title="Engagement evidence pack", reference=c.reference, issued=clock.now(), fingerprint=fingerprint,
        subtitle=f"{c.title} · {c.status.replace('_', ' ').lower()} · policy {c.policy_version_label}",
        sections=[
            pdf.Section("Parties", rows=[(p.role.title(), p.name) for p in out.parties]),
            pdf.Section("Agreement versions", rows=[(f"Version {v['version']}", f"terms {v['termsHash'][:16]}… · "
                                                     f"document {v['documentSha256'][:16]}…") for v in record["versions"]]),
            pdf.Section("Signatures", rows=[(f"{s['party'].title()} (v{s['version']})", f"{s['signer']} · {s['signedAt'][:19]}"
                                             f" · {s['authStrength']}") for s in record["signatures"]] or [("—", "Not signed")]),
            pdf.Section("Milestones", table=[(f"M{m['sequence']} {m['title']} ({m['status'].lower()})", money(m["amountMinor"]))
                                             for m in record["milestones"]], total=("Total", money(c.total_minor))),
            pdf.Section("Escrow ledger", table=[(f"{e['at'][:10]} {e['type'].lower()} · {e['account'].lower()}",
                                                 money(e["debitMinor"] or e["creditMinor"])) for e in record["escrowLedger"]]
                        or [("No money has moved", "")]),
            pdf.Section("Disputes", rows=[(d["reference"], f"{d['category'].lower()} · {d['status'].lower()}")
                                          for d in record["disputes"]] or [("None", "")]),
            pdf.Section("Files", rows=[(f["name"], f"{f['source']} · SHA-256 {f['sha256'][:16]}…") for f in record["files"]]
                        or [("None", "")]),
            *policy_sections,
            pdf.Section("Activity (from the audit trail)", rows=[(a["at"][:19].replace("T", " "), f"{a['what']} · {a['by']}")
                                                                 for a in record["activity"]]),
            pdf.Section(text="Attestation: this pack was produced by Zoikorum from its records. Each activity line comes from "
                             "the append-only, hash-chained audit trail; files are identified by their SHA-256. The fingerprint "
                             "below is the SHA-256 of this record and is stored with the download in the audit trail."),
        ])
    return pdf.render(doc), f"{name}.pdf", "application/pdf"


def _evidence_csv(c: Contract, record: dict, fingerprint: str) -> bytes:
    """The evidence pack as one CSV (section, date, item, detail, reference) for spreadsheets and audit tools."""
    import csv
    import io

    class _Safe:  # a cell starting with = + - @ would run as a formula in a spreadsheet: keep it text
        def __init__(self, inner):
            self.inner = inner

        def writerow(self, row):
            self.inner.writerow(["'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in row])

    buf = io.StringIO()
    w = _Safe(csv.writer(buf))
    w.writerow(["section", "date", "item", "detail", "reference"])
    w.writerow(["Engagement", "", c.reference, f"{c.title} · {c.status} · policy {c.policy_version_label}", f"fingerprint {fingerprint}"])
    for p in record["parties"]:
        w.writerow(["Parties", "", p.get("role"), p.get("name"), ""])
    for v in record["versions"]:
        w.writerow(["Agreement versions", v["createdAt"], f"Version {v['version']}", f"terms {v['termsHash']}", v["documentSha256"]])
    for s in record["signatures"]:
        w.writerow(["Signatures", s["signedAt"], s["party"], f"{s['signer']} (v{s['version']}, {s['authStrength']})", s["termsHash"]])
    for m in record["milestones"]:
        w.writerow(["Milestones", m["acceptedAt"] or "", f"M{m['sequence']} {m['title']}", f"{m['status']} · {m['amountMinor']} {c.currency}", ""])
    for e in record["escrowLedger"]:
        w.writerow(["Escrow ledger", e.get("at", ""), e.get("type", ""), f"{e.get('account', '')} · debit {e.get('debitMinor', 0)} · "
                    f"credit {e.get('creditMinor', 0)} {c.currency}", ""])
    for d in record["disputes"]:
        w.writerow(["Disputes", "", d.get("reference", ""), f"{d.get('category', '')} · {d.get('status', '')}", d.get("id", "")])
    for f in record["files"]:
        w.writerow(["Files", f.get("uploadedAt", ""), f.get("name", ""), f.get("source", ""), f.get("sha256", "")])
    for e in record["eligibility"]:
        w.writerow(["Eligibility evidence", e["at"], e["action"], f"{e['decision']} · tier {e['professionalTier'] or '-'} · "
                    + "; ".join(f"{k} {v}" for k, v in sorted(e["dimensions"].items())) + f" · {e['policy']}", e["contextHash"]])
    for a in record.get("approvalLog", []):
        w.writerow(["Approval log", a["requestedAt"], a["action"], f"{a['status']} · " + "; ".join(a["reasons"] or []), a["id"]])
        for v in a["votes"]:
            w.writerow(["Approval log", v["at"], f"{v['role']} {v['decision']}", f"{v['by']}: {v['reason']}", a["id"]])
    for x in record.get("exceptionHistory", []):
        w.writerow(["Exception history", x["requestedAt"], x["action"] + (" (emergency)" if x["emergency"] else ""),
                    f"{x['status']} · until {x['expiresAt']}" + (f" · {x['decidedBy']}: {x['decisionReason']}" if x["decidedBy"] else ""),
                    x["id"]])
    for a in record["activity"]:
        w.writerow(["Activity", a["at"], a["what"], a["by"], a["hash"]])
    return buf.getvalue().encode("utf-8")



# ---- Retainer pause (Payments & Escrow s.15: pause and resume cycles) -------------------------------------------

async def set_retainer_pause(session: AsyncSession, actor: Actor, contract_id: uuid.UUID, pause: bool, reason: str | None) -> ContractOut:
    """The buyer pauses a retainer: no new cycles are funded or reminded until they resume. Funded cycles continue."""
    c = await _contract(session, contract_id, lock=True)
    viewer = await _viewer(session, actor, c)
    await _require_decider(session, actor, c, viewer)
    if c.engagement_type != "RETAINER" and c.pricing_model != "RETAINER":
        raise Conflict("Only a retainer can be paused", code="NOT_A_RETAINER")
    if c.status != "ACTIVE":
        raise Conflict("Only an active retainer can be paused or resumed", code="CONTRACT_NOT_ACTIVE")
    if pause == (c.paused_at is not None):
        raise Conflict("The retainer is already " + ("paused" if pause else "running"), code="NO_CHANGE")
    c.paused_at, c.pause_reason = (clock.now(), (reason or "").strip()[:500] or None) if pause else (None, None)
    _evt(session, E.RETAINER_PAUSED if pause else E.RETAINER_RESUMED, c, reason=c.pause_reason, by=actor.identity_id)
    await session.flush()
    return await _out(session, actor, c, viewer)


async def is_paused(session: AsyncSession, contract_id: uuid.UUID) -> bool:
    c = await session.get(Contract, contract_id)
    return bool(c and c.paused_at)



# ---- Live policy state (Enterprise policies: show blocked actions before they are tried) ---------------------------

ACTION_LABEL = {"ESCROW_FUND": "Fund the next milestone", "MILESTONE_ACCEPT": "Accept submitted work", "ESCROW_RELEASE": "Release payment"}


async def policy_state(session: AsyncSession, actor: Actor, contract_id: uuid.UUID) -> dict:
    """For the buyer side: what the engagement's agreed policy version would decide for the next money actions, so a
    blocked action is shown as blocked (with its reason and the way forward) before anyone presses the button."""
    from zoikorum.domains.escrow import facade as escrow_facade

    c = await _contract(session, contract_id)
    if await _viewer(session, actor, c) != "BUYER":
        raise Forbidden("Only the buyer organisation sees its policy state")
    ms = await _milestones(session, c.id)
    account_id = await escrow_facade.account_id_for_contract(session, c.id)
    checks = []
    to_fund = next((m for m in ms if m.status == "PENDING_FUNDING"), None)
    if to_fund and account_id and c.status == "ACTIVE":
        checks.append(("ESCROW_FUND", "EscrowAccount", account_id, to_fund))
    submitted = next((m for m in ms if m.status == "SUBMITTED"), None)
    if submitted:
        checks.append(("MILESTONE_ACCEPT", "Milestone", submitted.id, submitted))
        checks.append(("ESCROW_RELEASE", "Milestone", submitted.id, submitted))
    out = []
    for action, subject_type, subject_id, m in checks:
        d = await policy_facade.preview(session, await policy_facade.commercial_context(session,
            org_id=c.organization_id, professional_id=c.professional_id, action=action, subject_type=subject_type,
            subject_id=subject_id, actor_identity_id=actor.identity_id, amount=m.amount_minor, currency=m.currency,
            engagement_type=c.engagement_type, pinned_version_id=c.policy_version_id,
            platform_default_pinned=c.policy_version_id is None))
        out.append({"action": action, "label": ACTION_LABEL[action], "milestoneId": m.id, "milestone": f"M{m.sequence} {m.title}",
                    "decision": d.decision, "reasons": [{"code": r.code, "message": r.message} for r in d.reasons]})
    return {"contractId": c.id, "policyVersion": c.policy_version_label, "actions": out}


# ---- Staff admin console: every contract ---------------------------------------------------------------------------

async def admin_contracts(session: AsyncSession, actor: Actor, q: str | None, status: str | None, cursor: str | None,
                          limit: int | None) -> dict:
    """Staff Contracts list, newest first: search by title or reference, filter by status. Each contract carries its
    milestones, the money funded and released in escrow, and whether a dispute is open. Every read is audited."""
    from sqlalchemy import or_

    from zoikorum.shared.http import next_cursor

    actor.require_capability(Cap.CONTRACTS_READ, Cap.ENGAGEMENTS_READ)
    stmt = select(Contract)
    if q and q.strip():
        term = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(func.lower(Contract.title).like(term, escape="\\"),
                              func.lower(Contract.reference).like(term, escape="\\")))
    if status:
        stmt = stmt.where(Contract.status == status)
    stmt, lim = paginate(stmt, Contract, cursor, limit)
    rows = list((await session.scalars(stmt)).all())
    page = rows[:lim]
    ids = [c.id for c in page]
    milestones: dict[uuid.UUID, list[Milestone]] = {}
    for m in (await session.scalars(select(Milestone).where(Milestone.contract_id.in_(ids))
                                    .order_by(Milestone.contract_id, Milestone.sequence))).all() if ids else []:
        milestones.setdefault(m.contract_id, []).append(m)
    orgs = {o: await buyer_facade.get_organization(session, o) for o in {c.organization_id for c in page}}
    pros = await professional_facade.get_professionals(session, list({c.professional_id for c in page}))
    money = await escrow_facade.money_by_contract(session, ids)
    disputed = await dispute_facade.contracts_with_open_disputes(session, ids)
    record_audit(session, "contract.admin.contracts_listed", object_type="Identity", object_id=actor.identity_id,
                 details={"search": bool(q and q.strip()), "status": status, "count": len(page)})

    def out(c: Contract) -> AdminContractOut:
        org, pro, parties = orgs.get(c.organization_id), pros.get(c.professional_id), c.parties or {}
        return AdminContractOut(
            id=c.id, title=c.title, status=c.status, version=c.contract_version, currency=c.currency, totalMinor=c.total_minor,
            buyer=AdminBuyerPartyOut(organizationId=c.organization_id, country=org.country if org else None,
                                     name=org.name if org else parties.get("buyer", {}).get("name", "")),
            professional=AdminProfessionalPartyOut(id=c.professional_id, country=pro.country if pro else None,
                                                   name=pro.display_name if pro else parties.get("professional", {}).get("name", "")),
            milestones=[AdminMilestoneOut(id=m.id, sequence=m.sequence, title=m.title, status=m.status,
                                          amountMinor=m.amount_minor, dueDate=m.due_date) for m in milestones.get(c.id, [])],
            fundedMinor=money.get(c.id, {}).get("funded", 0), releasedMinor=money.get(c.id, {}).get("released", 0),
            hasOpenDispute=c.id in disputed, createdAt=c.created_at, signedAt=c.activated_at, updatedAt=c.updated_at)

    return {"items": [out(c) for c in page], "nextCursor": next_cursor(rows, lim)}


async def admin_contract_summary(session: AsyncSession, actor: Actor) -> AdminContractSummaryOut:
    """Counts for the Contracts page cards: contracts and milestones by status, and disputes still open."""
    actor.require_capability(Cap.CONTRACTS_READ, Cap.ENGAGEMENTS_READ)
    by_status = dict((await session.execute(select(Contract.status, func.count()).group_by(Contract.status))).all())
    milestones = dict((await session.execute(select(Milestone.status, func.count()).group_by(Milestone.status))).all())
    return AdminContractSummaryOut(total=sum(by_status.values()), byStatus=by_status, milestonesByStatus=milestones,
                                   openDisputes=await dispute_facade.open_count(session))
