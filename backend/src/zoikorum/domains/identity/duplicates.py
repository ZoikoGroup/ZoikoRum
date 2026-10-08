"""Duplicate-account handling (Onboarding s.20: "Duplicate account suspected -> merge flow with support path").

Detection is evidence-based: the same identity document (identical SHA-256) submitted from two different accounts.
The person sees a notice and can ask for the accounts to be merged (or say it is not them); a Platform Admin or
Trust & Safety analyst decides with a fresh two-step confirmation. A confirmed duplicate is closed (suspended) with a
note pointing to the account that is kept; support moves anything that needs moving. Nothing is merged automatically.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity.models import DuplicateSuspicion, Identity
from zoikorum.domains.identity.schemas import DuplicateAnswerIn, DuplicateOut, DuplicateResolveIn
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import Conflict, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

RESOLVERS = (PlatformRole.PLATFORM_ADMIN, PlatformRole.TS_ANALYST)


def _evt(session: AsyncSession, event_type: str, d: DuplicateSuspicion, **extra) -> None:
    record_event(session, event_type, aggregate_type="DuplicateSuspicion", aggregate_id=d.id, tenant_id=d.identity_id,
                 payload={"suspicionId": d.id, "identityId": d.identity_id, "otherIdentityId": d.other_identity_id, "signal": d.signal, **extra})


async def suspect(session: AsyncSession, identity_id: uuid.UUID, other_identity_id: uuid.UUID, signal: str) -> None:
    """Consumer side: record one open suspicion per pair of accounts (idempotent, either order)."""
    if identity_id == other_identity_id:
        return
    existing = await session.scalar(select(DuplicateSuspicion.id).where(or_(
        (DuplicateSuspicion.identity_id == identity_id) & (DuplicateSuspicion.other_identity_id == other_identity_id),
        (DuplicateSuspicion.identity_id == other_identity_id) & (DuplicateSuspicion.other_identity_id == identity_id))))
    if existing:
        return
    d = DuplicateSuspicion(identity_id=identity_id, other_identity_id=other_identity_id, signal=signal, status="OPEN")
    session.add(d)
    await session.flush()
    _evt(session, E.DUPLICATE_ACCOUNT_SUSPECTED, d)


async def _names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, Identity]:
    return {i.id: i for i in (await session.scalars(select(Identity).where(Identity.id.in_(ids)))).all()}


def _out(d: DuplicateSuspicion, people: dict[uuid.UUID, Identity], staff: bool) -> DuplicateOut:
    me, other = people.get(d.identity_id), people.get(d.other_identity_id)
    return DuplicateOut(
        id=d.id, signal=d.signal, status=d.status, userAnswer=d.user_answer, userNote=d.user_note, resolutionNote=d.resolution_note,
        createdAt=d.created_at, resolvedAt=d.resolved_at,
        account=me.email if staff and me else None, accountName=me.display_name if staff and me else None,
        otherAccount=(other.email if staff else _mask(other.email)) if other else None,
        otherAccountName=other.display_name if staff and other else None,
        identityId=d.identity_id if staff else None, otherIdentityId=d.other_identity_id if staff else None)


def _mask(email: str) -> str:
    """The person sees which of their accounts is meant without exposing the full address."""
    local, _, domain = email.partition("@")
    return f"{local[:2]}{'•' * max(1, len(local) - 2)}@{domain}"


async def mine(session: AsyncSession, actor: Actor) -> list[DuplicateOut]:
    rows = (await session.scalars(select(DuplicateSuspicion).where(
        or_(DuplicateSuspicion.identity_id == actor.identity_id, DuplicateSuspicion.other_identity_id == actor.identity_id),
        DuplicateSuspicion.status.in_(("OPEN", "ANSWERED"))))).all()
    out = []
    for d in rows:
        # Show it from the viewer's side: "you" first, the other account second.
        if d.other_identity_id == actor.identity_id:
            d = DuplicateSuspicion(id=d.id, identity_id=d.other_identity_id, other_identity_id=d.identity_id, signal=d.signal,
                                   status=d.status, user_answer=d.user_answer, user_note=d.user_note, created_at=d.created_at)
        out.append(_out(d, await _names(session, {d.identity_id, d.other_identity_id}), staff=False))
    return out


async def answer(session: AsyncSession, actor: Actor, suspicion_id: uuid.UUID, body: DuplicateAnswerIn) -> DuplicateOut:
    d = await session.get(DuplicateSuspicion, suspicion_id, with_for_update=True)
    if d is None or actor.identity_id not in (d.identity_id, d.other_identity_id):
        raise NotFound("Not found")
    if d.status not in ("OPEN", "ANSWERED"):
        raise Conflict("This has already been resolved by support", code="ALREADY_RESOLVED")
    d.status, d.user_answer, d.user_note = "ANSWERED", body.answer, (body.note or "").strip() or None
    _evt(session, E.DUPLICATE_ACCOUNT_ANSWERED, d, answer=body.answer)
    await session.flush()
    return _out(d, await _names(session, {d.identity_id, d.other_identity_id}), staff=False)


async def queue(session: AsyncSession, actor: Actor) -> list[DuplicateOut]:
    actor.require_platform_role(*RESOLVERS)
    rows = (await session.scalars(select(DuplicateSuspicion).where(DuplicateSuspicion.status.in_(("OPEN", "ANSWERED")))
                                  .order_by(DuplicateSuspicion.created_at).limit(200))).all()
    people = await _names(session, {i for d in rows for i in (d.identity_id, d.other_identity_id)})
    return [_out(d, people, staff=True) for d in rows]


async def resolve(session: AsyncSession, actor: Actor, suspicion_id: uuid.UUID, body: DuplicateResolveIn) -> DuplicateOut:
    """Support decision. CONFIRMED closes the duplicate account (``keepIdentityId`` stays); NOT_DUPLICATE dismisses."""
    actor.require_platform_role(*RESOLVERS)
    actor.require_step_up()
    d = await session.get(DuplicateSuspicion, suspicion_id, with_for_update=True)
    if d is None:
        raise NotFound("Not found")
    if d.status not in ("OPEN", "ANSWERED"):
        raise Conflict("This has already been resolved", code="ALREADY_RESOLVED")
    if actor.identity_id in (d.identity_id, d.other_identity_id):
        raise ValidationFailed("You cannot resolve a case about your own account", code="SELF_REVIEW")
    d.resolved_by, d.resolved_at, d.resolution_note = actor.identity_id, clock.now(), body.note.strip()
    if body.outcome == "NOT_DUPLICATE":
        d.status = "NOT_DUPLICATE"
    else:
        if body.keepIdentityId not in (d.identity_id, d.other_identity_id):
            raise ValidationFailed("Choose which of the two accounts to keep", code="KEEP_ACCOUNT_REQUIRED")
        closed = d.other_identity_id if body.keepIdentityId == d.identity_id else d.identity_id
        d.status, d.kept_identity_id = "MERGED", body.keepIdentityId
        from zoikorum.domains.identity.service import set_status

        await set_status(session, closed, "SUSPENDED", f"DUPLICATE_OF:{body.keepIdentityId}")
    _evt(session, E.DUPLICATE_ACCOUNT_RESOLVED, d, outcome=d.status, keptIdentityId=d.kept_identity_id)
    await session.flush()
    return _out(d, await _names(session, {d.identity_id, d.other_identity_id}), staff=True)
