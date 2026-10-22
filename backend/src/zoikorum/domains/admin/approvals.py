"""Maker-checker approvals for privileged staff actions (staff admin console, P0).

One staff member asks for a privileged action and says why; a *different* person holding the role the action needs
approves or rejects it. Approving carries the action out at once through the owning domain's facade and records
APPLIED, or FAILED with the reason: nothing is ever reported as done before it is. Asking and deciding both need a
fresh two-step confirmation. A request nobody decides expires after ZK_APPROVAL_EXPIRY_HOURS. Every step is an event
(so it is in the audit trail); approvers are told about new requests and the requester about the outcome.

    REQUESTED -> APPLIED | FAILED            approved by someone else, then carried out (or it could not be)
    REQUESTED -> REJECTED | EXPIRED | CANCELLED (by the requester)

Who may approve (never the requester, nor the person a role change is about):
    GRANT_PLATFORM_ROLE, REVOKE_PLATFORM_ROLE   Platform Admin
    SWITCH_CHANGE                               the switch's own authority (money: Platform Admin or Financial Ops)
    FINANCIAL_EXCEPTION_RESOLVE                 Financial Operations or Platform Admin
    DEAD_LETTER_REPLAY_FINANCIAL                Financial Operations (only they may replay money events)
    AUDIT_EXPORT                                Compliance Officer or Legal
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.admin import switches
from zoikorum.domains.admin.models import ApprovalRequest
from zoikorum.domains.audit import facade as audit_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.payments import facade as payments_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.errors import Conflict, DomainError, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event
from zoikorum.shared.relay import cancel_timer, schedule_timer

EXPIRY_TIMER = "admin.approval_expiry"
OPEN = "REQUESTED"
CLOSED_WITHOUT_ACTION = ("REJECTED", "EXPIRED", "CANCELLED")
KINDS = ("GRANT_PLATFORM_ROLE", "REVOKE_PLATFORM_ROLE", "SWITCH_CHANGE", "FINANCIAL_EXCEPTION_RESOLVE",
         "DEAD_LETTER_REPLAY_FINANCIAL", "AUDIT_EXPORT")
PA, FO = PlatformRole.PLATFORM_ADMIN, PlatformRole.FINANCIAL_OPS


# ---- Payload of each kind ----------------------------------------------------------------------------------------------

class GrantPayload(BaseModel):
    identityId: uuid.UUID
    role: str
    expiresAt: datetime | None = None  # just-in-time: the role ends then; empty means permanent


class RevokePayload(BaseModel):
    identityId: uuid.UUID
    role: str


class SwitchPayload(BaseModel):
    key: str
    paused: bool


class ResolvePayload(BaseModel):
    itemKind: Literal["PAYOUT", "REFUND", "CHARGEBACK_LOSS"]
    itemId: uuid.UUID
    outcome: Literal["RECOVERED", "WRITTEN_OFF", "SETTLED_OUTSIDE"]
    note: str = Field(min_length=5, max_length=1000)


class ReplayPayload(BaseModel):
    failureId: uuid.UUID


class ExportPayload(BaseModel):
    scope: dict[str, Any] = Field(default_factory=dict)  # tenantId, objectType, objectId, correlationId, since, until
    format: Literal["json", "csv"] = "json"
    exportId: uuid.UUID | None = None  # set when the request is recorded


PAYLOADS: dict[str, type[BaseModel]] = {
    "GRANT_PLATFORM_ROLE": GrantPayload, "REVOKE_PLATFORM_ROLE": RevokePayload, "SWITCH_CHANGE": SwitchPayload,
    "FINANCIAL_EXCEPTION_RESOLVE": ResolvePayload, "DEAD_LETTER_REPLAY_FINANCIAL": ReplayPayload, "AUDIT_EXPORT": ExportPayload,
}


@dataclass
class _Plan:
    payload: BaseModel
    summary: str
    target_key: str
    approvers: tuple[str, ...]


def _label(role: str) -> str:
    return role.replace("_", " ").title()


async def _staff(session: AsyncSession, actor: Actor, cap: str, message: str) -> None:
    """The actor holds ``cap`` now (a stale token or an expired just-in-time role does not count)."""
    from zoikorum.domains.admin.service import staff

    try:
        await staff(session, actor, cap)
    except Forbidden as exc:
        raise Forbidden(message, code=exc.code) from exc


async def _approver(session: AsyncSession, actor: Actor, roles: tuple[str, ...], message: str) -> None:
    """Four eyes: the decider holds one of the approver roles recorded on the request, now. Deliberately role-based:
    the request names the roles whose holders may approve it (the same ones it notified)."""
    try:
        actor.require_platform_role(*roles)
        if not set(roles).intersection(await identity_facade.live_platform_roles(session, actor.identity_id)):
            raise Forbidden("Your staff authority has changed")
    except Forbidden as exc:
        raise Forbidden(message, code=exc.code) from exc


async def _failure(session: AsyncSession, failure_id: uuid.UUID):
    from zoikorum.shared.platform_models import ConsumerFailure

    row = await session.get(ConsumerFailure, failure_id)
    if row is None:
        raise NotFound("Delivery failure not found")
    if row.status != "DEAD":
        raise Conflict("Only dead-lettered deliveries can be replayed", code="NOT_DEAD_LETTERED")
    if not row.financial:
        raise Conflict("This delivery does not move money: replay it directly", code="NOT_FINANCIAL")
    return row


async def _plan(session: AsyncSession, actor: Actor, kind: str, p: BaseModel) -> _Plan:
    """Checks the requester's authority and that the action could be carried out; says who may approve it."""
    if isinstance(p, (GrantPayload, RevokePayload)):
        grant = isinstance(p, GrantPayload)
        await _staff(session, actor, Cap.IAM_REQUEST, "Only a Platform Admin can ask for a staff role change")
        expires = p.expiresAt if grant else None
        who = await identity_facade.check_platform_role_change(session, actor.identity_id, p.identityId, p.role, grant, expires)
        if grant:
            until = f" until {expires:%d %b %Y %H:%M} UTC" if expires else " (permanent)"
            summary = f"Grant {_label(p.role)} to {who.display_name} ({who.email}){until}"
        else:
            summary = f"Remove {_label(p.role)} from {who.display_name} ({who.email})"
        return _Plan(p, summary, f"ROLE:{p.identityId}:{p.role}", (PA,))
    if isinstance(p, SwitchPayload):
        roles = await switches.check_authority(session, actor, p.key)
        label = switches.SWITCHES[p.key].label
        return _Plan(p, f"{'Pause' if p.paused else 'Switch back on'}: {label}", f"SWITCH:{p.key}", roles)
    if isinstance(p, ResolvePayload):
        await _staff(session, actor, Cap.PAYMENTS_OPS, "Only Financial Operations can close a financial exception")
        await payments_facade.check_ops_resolution(session, p.itemKind, p.itemId)
        summary = f"Close {_label(p.itemKind).lower()} {str(p.itemId)[:8]} as {_label(p.outcome).lower()}"
        return _Plan(p, summary, f"OPS:{p.itemKind}:{p.itemId}", (FO, PA))
    if isinstance(p, ReplayPayload):
        await _staff(session, actor, Cap.DLQ_REPLAY, "Only a Platform Admin or Financial Operations can ask for a replay")
        row = await _failure(session, p.failureId)
        return _Plan(p, f"Replay money event {row.event_type} to {row.consumer}", f"DLQ:{p.failureId}", (FO,))
    if isinstance(p, ExportPayload):
        await _staff(session, actor, Cap.AUDIT_EXPORT, "Audit exports require compliance, legal or Platform Admin authority")
        scope = ", ".join(f"{k} {v}" for k, v in sorted(p.scope.items()) if v) or "the whole trail"
        return _Plan(p, f"Audit export ({p.format.upper()}) of {scope}"[:300], "EXPORT:",
                     (PlatformRole.COMPLIANCE_OFFICER, PlatformRole.LEGAL))
    raise ValidationFailed("Unknown kind of request", code="UNKNOWN_APPROVAL_KIND")


def _subject(r: ApprovalRequest) -> uuid.UUID | None:
    """The person a role change is about: they never approve it."""
    return uuid.UUID(r.payload["identityId"]) if r.kind in ("GRANT_PLATFORM_ROLE", "REVOKE_PLATFORM_ROLE") else None


def _event(session: AsyncSession, kind: str, r: ApprovalRequest, recipients: list[uuid.UUID], message: str) -> None:
    record_event(session, kind, aggregate_type="ApprovalRequest", aggregate_id=r.id,
                 payload={"approvalRequestId": r.id, "kind": r.kind, "summary": r.summary, "status": r.status,
                          "requestedBy": r.requested_by, "decidedBy": r.decided_by, "recipientIdentityIds": recipients,
                          "message": message})


# ---- Commands ----------------------------------------------------------------------------------------------------------

async def request(session: AsyncSession, actor: Actor, kind: str, payload: dict, justification: str) -> dict:
    """Records a privileged action for a second person to approve. Nothing changes until it is approved."""
    model = PAYLOADS.get(kind)
    if model is None:
        raise ValidationFailed("Unknown kind of request", code="UNKNOWN_APPROVAL_KIND")
    try:
        p = model.model_validate(payload)
    except ValidationError as exc:
        raise ValidationFailed("The request details are not valid for this kind of action",
                               extra={"errors": jsonable_encoder(exc.errors(include_url=False, include_context=False))}) from exc
    if len((justification or "").strip()) < 10:
        raise ValidationFailed("Say why this is needed (at least 10 characters): the approver reads it", code="JUSTIFICATION_REQUIRED")
    plan = await _plan(session, actor, kind, p)
    actor.require_step_up()
    if plan.target_key != "EXPORT:":
        now = clock.now()
        pending = await session.scalar(select(ApprovalRequest.id).where(
            ApprovalRequest.target_key == plan.target_key, ApprovalRequest.status == OPEN, ApprovalRequest.expires_at > now))
        if pending:
            raise Conflict("A request for this is already waiting for approval", code="APPROVAL_ALREADY_PENDING",
                           extra={"approvalRequestId": str(pending)})
    if isinstance(p, ExportPayload):
        p.exportId = await audit_facade.open_export(session, actor.identity_id, p.scope, p.format)
        plan.target_key = f"EXPORT:{p.exportId}"
    now = clock.now()
    r = ApprovalRequest(kind=kind, payload=p.model_dump(mode="json"), summary=plan.summary[:300], target_key=plan.target_key,
                        justification=justification.strip(), requested_by=actor.identity_id, requested_at=now,
                        expires_at=now + timedelta(hours=get_settings().approval_expiry_hours),
                        approver_roles=list(plan.approvers), status=OPEN)
    session.add(r)
    await session.flush()
    await schedule_timer(session, EXPIRY_TIMER, str(r.id), r.expires_at)
    approvers = [i for i in await identity_facade.staff_holding(session, plan.approvers)
                 if i != actor.identity_id and i != _subject(r)]
    _event(session, E.STAFF_APPROVAL_REQUESTED, r, approvers,
           f"{r.summary}. Requested because: {r.justification} Approve or reject it before {r.expires_at:%d %b %Y %H:%M} UTC.")
    return await out(session, actor, r)


async def _apply(session: AsyncSession, r: ApprovalRequest) -> dict:
    """Carries out an approved request through the owning domain. Raises DomainError when it cannot be done."""
    p = PAYLOADS[r.kind].model_validate(r.payload)
    if isinstance(p, (GrantPayload, RevokePayload)):
        roles = await identity_facade.apply_platform_role_change(
            session, p.identityId, p.role, isinstance(p, GrantPayload), getattr(p, "expiresAt", None), r.requested_by, r.decided_by)
        return {"platformRoles": roles}
    if isinstance(p, SwitchPayload):
        s = await switches.apply_switch(session, p.key, p.paused, r.justification[:500], r.requested_by)
        return {"key": s["key"], "paused": s["paused"]}
    if isinstance(p, ResolvePayload):
        await payments_facade.apply_ops_resolution(session, p.itemKind, p.itemId, p.outcome, p.note, r.requested_by, r.decided_by)
        return {"itemKind": p.itemKind, "itemId": str(p.itemId), "outcome": p.outcome}
    if isinstance(p, ReplayPayload):
        from zoikorum.shared.db import session_factory
        from zoikorum.shared.relay import replay_dead_letter

        await _failure(session, p.failureId)
        ok = await replay_dead_letter(session_factory(), p.failureId, authorised_by=str(r.decided_by), financial_ops=True)
        if not ok:
            raise Conflict("The delivery failed again; it stays in the dead-letter queue", code="REPLAY_FAILED")
        return {"replayed": True}
    if isinstance(p, ExportPayload):
        return jsonable_encoder(await audit_facade.complete_export(session, p.exportId))
    raise ValidationFailed("Unknown kind of request", code="UNKNOWN_APPROVAL_KIND")


async def _close_side_effects(session: AsyncSession, r: ApprovalRequest, status: str) -> None:
    """A request that ends without its action leaves nothing half-made (a requested audit export is closed too)."""
    await cancel_timer(session, EXPIRY_TIMER, str(r.id))
    if r.kind == "AUDIT_EXPORT" and r.payload.get("exportId"):
        await audit_facade.close_export(session, uuid.UUID(r.payload["exportId"]), status)


async def _get(session: AsyncSession, request_id: uuid.UUID, lock: bool = False) -> ApprovalRequest:
    r = await session.get(ApprovalRequest, request_id, with_for_update=lock)
    if r is None:
        raise NotFound("Approval request not found")
    return r


async def decide(session: AsyncSession, actor: Actor, request_id: uuid.UUID, approve: bool, note: str | None) -> dict:
    """An independent approver approves (the action is carried out now) or rejects (nothing changes)."""
    r = await _get(session, request_id, lock=True)
    await _approver(session, actor, tuple(r.approver_roles),
                    "Approving this needs one of: " + ", ".join(_label(x) for x in r.approver_roles))
    actor.require_step_up()
    if r.status != OPEN:
        raise Conflict(f"This request is already {r.status.lower()}", code="APPROVAL_NOT_PENDING")
    if r.expires_at <= clock.now():
        raise Conflict("This request expired before it was decided; ask again if it is still needed", code="APPROVAL_EXPIRED")
    if actor.identity_id == r.requested_by:
        raise Forbidden("Another staff member must approve a request you made", code="FOUR_EYES")
    if actor.identity_id == _subject(r):
        raise Forbidden("Another administrator must decide a change to your own staff roles", code="FOUR_EYES")
    note = (note or "").strip() or None
    if not approve and (note is None or len(note) < 5):
        raise ValidationFailed("Say why you are rejecting it (at least 5 characters)", code="NOTE_REQUIRED")
    now = clock.now()
    r.decided_by, r.decided_at, r.decision_note = actor.identity_id, now, note
    if not approve:
        r.status = "REJECTED"
        await _close_side_effects(session, r, "REJECTED")
        _event(session, E.STAFF_APPROVAL_REJECTED, r, [r.requested_by],
               f"{r.summary}: rejected" + (f". Reason: {note}" if note else "."))
        return await out(session, actor, r)
    await session.flush()
    try:
        async with session.begin_nested():  # a failed action leaves no partial change behind
            result = await _apply(session, r)
    except DomainError as exc:
        await session.refresh(r)
        r.status, r.apply_error = "FAILED", str(exc.detail or exc.title)[:1000]
        await _close_side_effects(session, r, "FAILED")
        _event(session, E.STAFF_APPROVAL_FAILED, r, [r.requested_by],
               f"{r.summary}: approved, but it could not be carried out: {r.apply_error}")
    else:
        r.status, r.applied_at, r.result = "APPLIED", clock.now(), jsonable_encoder(result)
        await cancel_timer(session, EXPIRY_TIMER, str(r.id))
        _event(session, E.STAFF_APPROVAL_APPLIED, r, [r.requested_by], f"{r.summary}: approved and carried out.")
    return await out(session, actor, r)


async def cancel(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> dict:
    """The requester withdraws a request that is still waiting."""
    r = await _get(session, request_id, lock=True)
    if r.requested_by != actor.identity_id:
        raise Forbidden("Only the person who asked can cancel this request", code="NOT_REQUESTER")
    if r.status != OPEN:
        raise Conflict(f"This request is already {r.status.lower()}", code="APPROVAL_NOT_PENDING")
    r.status = "CANCELLED"
    await _close_side_effects(session, r, "CANCELLED")
    _event(session, E.STAFF_APPROVAL_CANCELLED, r, [], f"{r.summary}: cancelled by the requester.")
    return await out(session, actor, r)


async def expire(session: AsyncSession, request_id: uuid.UUID) -> None:
    """Timer (and lazily on reads): a request nobody decided in time expires; its action is never carried out."""
    r = await session.get(ApprovalRequest, request_id, with_for_update=True)
    if r is None or r.status != OPEN or r.expires_at > clock.now():
        return
    r.status = "EXPIRED"
    await _close_side_effects(session, r, "EXPIRED")
    _event(session, E.STAFF_APPROVAL_EXPIRED, r, [r.requested_by],
           f"{r.summary}: nobody decided it within {get_settings().approval_expiry_hours} hours, so nothing was changed.")


async def _expire_overdue(session: AsyncSession) -> None:
    ids = (await session.scalars(select(ApprovalRequest.id).where(
        ApprovalRequest.status == OPEN, ApprovalRequest.expires_at <= clock.now()).limit(200))).all()
    for request_id in ids:
        await expire(session, request_id)


# ---- Reads -------------------------------------------------------------------------------------------------------------

async def _viewer(session: AsyncSession, actor: Actor) -> frozenset[str]:
    await _staff(session, actor, Cap.APPROVALS_READ, "Approval requests are for staff")
    return await identity_facade.live_platform_roles(session, actor.identity_id)


def _can_decide(r: ApprovalRequest, actor: Actor, roles: frozenset[str]) -> bool:
    return (r.status == OPEN and r.expires_at > clock.now() and actor.identity_id not in (r.requested_by, _subject(r))
            and bool(roles.intersection(r.approver_roles)))


async def out(session: AsyncSession, actor: Actor, r: ApprovalRequest, roles: frozenset[str] | None = None,
              people: dict | None = None) -> dict:
    if roles is None:
        roles = await identity_facade.live_platform_roles(session, actor.identity_id)
    if people is None:
        people = await identity_facade.get_identities(session, [i for i in (r.requested_by, r.decided_by) if i])

    def person(i):
        if i is None:
            return None
        p = people.get(i)
        return {"id": i, "displayName": p.display_name if p else None, "email": p.email if p else None}

    return {"id": r.id, "kind": r.kind, "status": r.status, "summary": r.summary, "payload": r.payload,
            "justification": r.justification, "requestedBy": person(r.requested_by), "requestedAt": r.requested_at,
            "expiresAt": r.expires_at, "approverRoles": list(r.approver_roles), "decidedBy": person(r.decided_by),
            "decidedAt": r.decided_at, "decisionNote": r.decision_note, "appliedAt": r.applied_at,
            "applyError": r.apply_error, "result": r.result, "canDecide": _can_decide(r, actor, roles),
            "canCancel": r.status == OPEN and r.requested_by == actor.identity_id}


async def get(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> dict:
    roles = await _viewer(session, actor)
    await expire(session, request_id)
    return await out(session, actor, await _get(session, request_id), roles)


async def list_requests(session: AsyncSession, actor: Actor, status: str | None, kind: str | None, mine: bool,
                        awaiting_me: bool, limit: int, offset: int) -> list[dict]:
    """Staff see every request (the approval trail is shared); filter to their own, or to those they can decide."""
    roles = await _viewer(session, actor)
    await _expire_overdue(session)
    stmt = select(ApprovalRequest)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    if kind:
        stmt = stmt.where(ApprovalRequest.kind == kind)
    if mine:
        stmt = stmt.where(ApprovalRequest.requested_by == actor.identity_id)
    if awaiting_me:
        stmt = stmt.where(ApprovalRequest.status == OPEN, ApprovalRequest.requested_by != actor.identity_id)
    rows = list((await session.scalars(stmt.order_by(ApprovalRequest.requested_at.desc()).limit(500 if awaiting_me else limit)
                                       .offset(0 if awaiting_me else offset))).all())
    if awaiting_me:
        rows = [r for r in rows if _can_decide(r, actor, roles)][offset:offset + limit]
    people = await identity_facade.get_identities(session, list({i for r in rows for i in (r.requested_by, r.decided_by) if i}))
    return [await out(session, actor, r, roles, people) for r in rows]


async def summary(session: AsyncSession, actor: Actor) -> dict:
    """Approvals page KPIs: waiting for me, my open requests, applied and rejected or expired in the last 7 days."""
    roles = await _viewer(session, actor)
    await _expire_overdue(session)
    open_rows = (await session.scalars(select(ApprovalRequest).where(ApprovalRequest.status == OPEN))).all()
    week = clock.now() - timedelta(days=7)

    async def count(*where) -> int:
        return await session.scalar(select(func.count()).select_from(ApprovalRequest).where(*where)) or 0

    return {"awaitingMe": sum(1 for r in open_rows if _can_decide(r, actor, roles)),
            "myOpen": sum(1 for r in open_rows if r.requested_by == actor.identity_id),
            "applied7d": await count(ApprovalRequest.status == "APPLIED", ApprovalRequest.applied_at >= week),
            "rejectedOrExpired7d": await count(ApprovalRequest.status.in_(("REJECTED", "EXPIRED")),
                                               ApprovalRequest.updated_at >= week),
            "failed7d": await count(ApprovalRequest.status == "FAILED", ApprovalRequest.updated_at >= week)}
