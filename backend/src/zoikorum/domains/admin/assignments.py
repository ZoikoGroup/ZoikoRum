"""Case owners across the staff console (engineering handoff P1): any staff case can have an owner, be assigned,
reassigned, released, escalated and de-escalated. Generic over the workstreams, so no domain needs a schema change: one
``admin.case_assignments`` row per (kind, case id). Decisions stay in each case's own screen; this only says who is
working it. Every change is audited and the new owner is notified.

Who may do what (kept deliberately simple):
- To touch a case of a kind you must hold the read capability of its staff page (``KIND_CAPABILITY``,
  shared/capabilities.py).
- Anyone who works the kind may take a case ("assign to me", also taking it over from someone else), release a case
  they own, and escalate or de-escalate it.
- Assigning a case to someone else, and releasing someone else's case: for enforcement, which every staff member can
  open, only with ``assignments.manage`` (Trust & Safety analyst, Risk Lead, Platform Admin); for every other kind,
  anyone who works the kind (the page's roles plus Platform Admin, who either works the kind already or cannot reach it).
- The new owner must hold that capability too, on an active account.

Support requests already have a native owner (support ``assigned_to``, set by the first agent who answers): for them
the owner is read from and written to that field through the support facade; only the escalation lives here. Dispute
ownership here is the operational owner and is separate from the dispute's assigned mediator (assign-mediator).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from zoikorum.domains.admin.models import CaseAssignment, EnforcementCase
from zoikorum.domains.dispute import facade as dispute_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.marketplace import facade as marketplace_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.support import facade as support_facade
from zoikorum.domains.verification import facade as verification_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, CurrentActor
from zoikorum.shared.capabilities import Cap, capabilities_for, roles_with
from zoikorum.shared.db import DbSession
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.platform_models import ConsumerFailure

CaseKind = Literal["VERIFICATION_CASE", "VERIFICATION_APPEAL", "ENFORCEMENT_CASE", "DISPUTE", "SUPPORT_REQUEST", "DUPLICATE",
                   "ENTERPRISE_APPLICATION", "TAXONOMY_SUGGESTION", "PAYMENT_EXCEPTION", "DEAD_LETTER"]

# Working a kind of case = the read capability of the console page that shows it.
KIND_CAPABILITY: dict[str, str] = {
    "VERIFICATION_CASE": Cap.VERIFICATION_READ,
    "VERIFICATION_APPEAL": Cap.VERIFICATION_READ,
    "ENTERPRISE_APPLICATION": Cap.ENTERPRISE_READ,
    "ENFORCEMENT_CASE": Cap.SAFETY_READ,
    "DISPUTE": Cap.DISPUTES_READ,
    "SUPPORT_REQUEST": Cap.SUPPORT_READ,
    "DUPLICATE": Cap.IDENTITY_CASES_READ,
    "TAXONOMY_SUGGESTION": Cap.TAXONOMY_READ,
    "PAYMENT_EXCEPTION": Cap.FINEXCEPTIONS_READ,
    "DEAD_LETTER": Cap.DLQ_READ,
}
# The roles that work each kind (to find eligible owners).
WORKERS: dict[str, frozenset[str]] = {k: roles_with(c) for k, c in KIND_CAPABILITY.items()}

LABELS = {"VERIFICATION_CASE": "verification case", "VERIFICATION_APPEAL": "verification appeal", "ENFORCEMENT_CASE": "trust & safety case",
          "DISPUTE": "dispute", "SUPPORT_REQUEST": "support request", "DUPLICATE": "duplicate-account case",
          "ENTERPRISE_APPLICATION": "enterprise readiness application", "TAXONOMY_SUGGESTION": "specialization suggestion",
          "PAYMENT_EXCEPTION": "payment exception", "DEAD_LETTER": "failed delivery"}


async def _exists(session, kind: str, case_id: uuid.UUID) -> bool:
    """The case is real, checked through its owning domain. Payment exceptions (a payout, refund or chargeback loss)
    have no single cheap lookup and are accepted by id."""
    if kind == "VERIFICATION_CASE":
        return await verification_facade.case_exists(session, case_id)
    if kind == "VERIFICATION_APPEAL":
        return await verification_facade.appeal_exists(session, case_id)
    if kind == "ENFORCEMENT_CASE":
        return await session.get(EnforcementCase, case_id) is not None
    if kind == "DISPUTE":
        return await dispute_facade.get_dispute(session, case_id) is not None
    if kind == "SUPPORT_REQUEST":
        return await support_facade.request_exists(session, case_id)
    if kind == "DUPLICATE":
        return await identity_facade.duplicate_exists(session, case_id)
    if kind == "ENTERPRISE_APPLICATION":  # keyed by the applying professional
        return await professional_facade.get_professional(session, case_id) is not None
    if kind == "TAXONOMY_SUGGESTION":
        return await marketplace_facade.suggestion_exists(session, case_id)
    if kind == "DEAD_LETTER":
        return await session.get(ConsumerFailure, case_id) is not None
    return True


async def _caps(session, actor: Actor) -> frozenset[str]:
    """Staff only (with a two-step session), using the capabilities of the roles held right now."""
    actor.require_capability(Cap.WORK_READ)
    caps = capabilities_for(await identity_facade.live_platform_roles(session, actor.identity_id))
    if Cap.WORK_READ not in caps:
        raise Forbidden("Your staff authority has changed")
    return caps


async def _works(session, actor: Actor, kind: str) -> frozenset[str]:
    caps = await _caps(session, actor)
    if KIND_CAPABILITY[kind] not in caps:
        raise Forbidden(f"Your roles do not work {LABELS[kind]}s", code="CASE_KIND_NOT_ALLOWED")
    return caps


def _case_uuid(case_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(case_id)
    except ValueError:
        raise NotFound("Case not found") from None


async def _row(session, kind: str, case_id: uuid.UUID) -> CaseAssignment:
    await session.execute(insert(CaseAssignment).values(id=uuid.uuid4(), kind=kind, case_id=str(case_id), escalated=False)
                          .on_conflict_do_nothing(constraint="uq_case_assignments_kind_case"))
    return await session.scalar(select(CaseAssignment).where(CaseAssignment.kind == kind, CaseAssignment.case_id == str(case_id))
                                .with_for_update().execution_options(populate_existing=True))


async def _owner_of(session, row: CaseAssignment) -> uuid.UUID | None:
    if row.kind == "SUPPORT_REQUEST":
        native = await support_facade.open_assignees(session)
        return native.get(uuid.UUID(row.case_id), row.owner_identity_id)
    return row.owner_identity_id


def _out(kind: str, case_id: str, owner: uuid.UUID | None, row: CaseAssignment | None, people: dict) -> dict:
    name = lambda i: (people[i].display_name if i in people else "Former staff member") if i else None  # noqa: E731
    return {"kind": kind, "caseId": case_id, "ownerId": owner, "ownerName": name(owner),
            "escalated": bool(row and row.escalated), "escalationReason": row.escalation_reason if row and row.escalated else None,
            "escalatedAt": row.escalated_at if row and row.escalated else None,
            "updatedBy": row.updated_by if row else None, "updatedByName": name(row.updated_by) if row else None,
            "updatedAt": row.updated_at if row else None}


async def _one(session, row: CaseAssignment) -> dict:
    owner = await _owner_of(session, row)
    people = await identity_facade.get_identities(session, [i for i in (owner, row.updated_by) if i])
    return _out(row.kind, row.case_id, owner, row, people)


async def list_assignments(session, actor: Actor, kinds: list[str] | None, owner_id: uuid.UUID | None, mine: bool) -> list[dict]:
    """Owned or escalated cases of the kinds the person works (all of them by default)."""
    caps = await _caps(session, actor)
    unknown = sorted(set(kinds or ()) - set(KIND_CAPABILITY))
    if unknown:
        raise ValidationFailed(f"Unknown case kind(s): {', '.join(unknown)}")
    allowed = [k for k in (kinds or KIND_CAPABILITY) if KIND_CAPABILITY[k] in caps]
    if not allowed:
        return []
    rows = (await session.scalars(select(CaseAssignment).where(
        CaseAssignment.kind.in_(allowed), or_(CaseAssignment.owner_identity_id.is_not(None), CaseAssignment.escalated.is_(True)))
        .order_by(CaseAssignment.updated_at.desc()).limit(2000))).all()
    found: dict[tuple[str, str], tuple[uuid.UUID | None, CaseAssignment | None]] = {(r.kind, r.case_id): (r.owner_identity_id, r) for r in rows}
    if "SUPPORT_REQUEST" in allowed:  # the support request's own owner wins
        native = await support_facade.open_assignees(session)
        for (kind, case_id), (owner, row) in list(found.items()):
            if kind == "SUPPORT_REQUEST":
                found[(kind, case_id)] = (native.get(uuid.UUID(case_id), owner), row)
        for request_id, owner in native.items():
            found.setdefault(("SUPPORT_REQUEST", str(request_id)), (owner, None))
    wanted = actor.identity_id if mine else owner_id
    items = [(k, c, o, r) for (k, c), (o, r) in found.items() if (o or (r and r.escalated)) and (wanted is None or o == wanted)]
    ids = {i for _, _, o, r in items for i in (o, r.updated_by if r else None) if i}
    people = await identity_facade.get_identities(session, list(ids))
    return [_out(k, c, o, r, people) for k, c, o, r in items]


async def assign(session, actor: Actor, kind: str, case_id: str, owner_id: uuid.UUID | None, note: str | None) -> dict:
    """Assign, reassign (``owner_id`` set) or release (``owner_id`` None)."""
    caps = await _works(session, actor, kind)
    cid = _case_uuid(case_id)
    if not await _exists(session, kind, cid):
        raise NotFound("Case not found")
    lead = Cap.ASSIGNMENTS_MANAGE in caps if kind == "ENFORCEMENT_CASE" else True
    row = await _row(session, kind, cid)
    previous = await _owner_of(session, row)
    if owner_id is None:
        if previous is None:
            return await _one(session, row)
        if previous != actor.identity_id and not lead:
            raise Forbidden("Only the owner, a Platform Admin or this workstream's lead role can release someone else's case",
                            code="ASSIGN_NOT_ALLOWED")
    else:
        if owner_id != actor.identity_id and not lead:
            raise Forbidden("Assigning a case to someone else needs Platform Admin or this workstream's role", code="ASSIGN_NOT_ALLOWED")
        if KIND_CAPABILITY[kind] not in capabilities_for(await identity_facade.live_platform_roles(session, owner_id)):
            raise ValidationFailed(f"That person cannot work {LABELS[kind]}s", code="OWNER_NOT_ELIGIBLE")
        if owner_id == previous:
            return await _one(session, row)
    row.owner_identity_id, row.updated_by, row.updated_at = owner_id, actor.identity_id, clock.now()
    if kind == "SUPPORT_REQUEST":
        await support_facade.set_assignee(session, cid, owner_id)
    action = "admin.case.released" if owner_id is None else "admin.case.assigned" if previous is None else "admin.case.reassigned"
    record_audit(session, action, object_type="CaseAssignment", object_id=row.id,
                 details={"kind": kind, "caseId": str(cid), "from": str(previous) if previous else None,
                          "to": str(owner_id) if owner_id else None, "note": (note or "").strip() or None})
    if owner_id and owner_id != actor.identity_id:
        record_event(session, E.CASE_ASSIGNED, aggregate_type="CaseAssignment", aggregate_id=row.id,
                     payload={"identityId": owner_id, "kind": kind, "caseId": str(cid), "assignedBy": actor.identity_id,
                              "message": f"A {LABELS[kind]} was assigned to you. Open My Work Queue to pick it up."
                                         + (f"\nNote: {note.strip()}" if note and note.strip() else "")})
    await session.flush()
    return await _one(session, row)


async def escalate(session, actor: Actor, kind: str, case_id: str, reason: str) -> dict:
    await _works(session, actor, kind)
    cid = _case_uuid(case_id)
    if not await _exists(session, kind, cid):
        raise NotFound("Case not found")
    row = await _row(session, kind, cid)
    row.escalated, row.escalation_reason, row.escalated_at = True, reason.strip(), clock.now()
    row.updated_by, row.updated_at = actor.identity_id, clock.now()
    record_audit(session, "admin.case.escalated", object_type="CaseAssignment", object_id=row.id,
                 details={"kind": kind, "caseId": str(cid), "reason": reason.strip()})
    await session.flush()
    return await _one(session, row)


async def de_escalate(session, actor: Actor, kind: str, case_id: str) -> dict:
    await _works(session, actor, kind)
    cid = _case_uuid(case_id)
    row = await session.scalar(select(CaseAssignment).where(CaseAssignment.kind == kind, CaseAssignment.case_id == str(cid))
                               .with_for_update())
    if row is None or not row.escalated:
        raise Conflict("This case is not escalated", code="NOT_ESCALATED")
    row.escalated, row.escalation_reason, row.escalated_at = False, None, None
    row.updated_by, row.updated_at = actor.identity_id, clock.now()
    record_audit(session, "admin.case.de_escalated", object_type="CaseAssignment", object_id=row.id,
                 details={"kind": kind, "caseId": str(cid)})
    await session.flush()
    return await _one(session, row)


async def assignable_staff(session, actor: Actor, kind: str) -> list[dict]:
    await _works(session, actor, kind)
    out = []
    for s, _ in await identity_facade.staff_with_roles(session, WORKERS[kind]):
        roles = await identity_facade.live_platform_roles(session, s.id) & WORKERS[kind]  # in force now, account active
        if roles:
            out.append({"id": s.id, "name": s.display_name, "email": s.email, "roles": sorted(roles), "you": s.id == actor.identity_id})
    return out


# ---- HTTP -------------------------------------------------------------------------------------------------------------

router = APIRouter(tags=["admin"])


class AssignmentOut(BaseModel):
    kind: str
    caseId: str
    ownerId: uuid.UUID | None
    ownerName: str | None
    escalated: bool
    escalationReason: str | None
    escalatedAt: datetime | None
    updatedBy: uuid.UUID | None
    updatedByName: str | None
    updatedAt: datetime | None


class AssignIn(BaseModel):
    ownerId: uuid.UUID | None  # null releases the case
    note: str | None = Field(default=None, max_length=500)


class EscalateIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


class AssignableStaffOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    roles: list[str]
    you: bool


@router.get("/v1/admin/assignments", response_model=list[AssignmentOut])
async def assignments(actor: CurrentActor, session: DbSession, kinds: str | None = Query(None, description="Comma-separated case kinds"),
                      ownerId: uuid.UUID | None = None, mine: bool = False):
    """Staff: who owns which case, and which cases are escalated, for the kinds the person works."""
    wanted = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    return await list_assignments(session, actor, wanted, ownerId, mine)


@router.get("/v1/admin/assignable-staff", response_model=list[AssignableStaffOut])
async def staff_for_kind(kind: CaseKind, actor: CurrentActor, session: DbSession):
    """Staff who can own a case of this kind."""
    return await assignable_staff(session, actor, kind)


@router.put("/v1/admin/assignments/{kind}/{case_id}", response_model=AssignmentOut)
async def set_owner(kind: CaseKind, case_id: str, body: AssignIn, actor: CurrentActor, session: DbSession):
    """Assign the case to yourself or (Platform Admin / the workstream's role) to someone else, reassign it, or release
    it with ``ownerId: null``. Audited; the new owner is notified."""
    return await assign(session, actor, kind, case_id, body.ownerId, body.note)


@router.post("/v1/admin/assignments/{kind}/{case_id}/escalate", response_model=AssignmentOut)
async def escalate_case(kind: CaseKind, case_id: str, body: EscalateIn, actor: CurrentActor, session: DbSession):
    """Flag the case for senior attention, with a reason. It shows on every work queue's Escalations tab."""
    return await escalate(session, actor, kind, case_id, body.reason)


@router.post("/v1/admin/assignments/{kind}/{case_id}/de-escalate", response_model=AssignmentOut)
async def de_escalate_case(kind: CaseKind, case_id: str, actor: CurrentActor, session: DbSession):
    return await de_escalate(session, actor, kind, case_id)
