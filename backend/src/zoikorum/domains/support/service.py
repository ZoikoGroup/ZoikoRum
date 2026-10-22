"""Help requests (no dead ends: every failure has a support path - professional onboarding, buyer dashboard and
dispute documents). The person describes the problem with its context (page, engagement, error reference); a support
agent answers in the request's conversation. Support agents have no authority over money, verification or enforcement:
they explain and route to the right workflow.
"""

from __future__ import annotations

import uuid

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.support.models import SupportMessage, SupportRequest
from zoikorum.domains.support.schemas import SupportMessageOut, SupportReplyIn, SupportRequestIn, SupportRequestOut
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.errors import Conflict, NotFound, RateLimited
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

OPEN = ("OPEN", "WAITING_ON_YOU")
MAX_OPEN = 10


def _evt(session: AsyncSession, kind: str, r: SupportRequest, **extra) -> None:
    record_event(session, kind, aggregate_type="SupportRequest", aggregate_id=r.id,
                 payload={"requestId": r.id, "reference": r.reference, "identityId": r.requester_identity_id,
                          "topic": r.topic, **extra})


async def _out(session: AsyncSession, r: SupportRequest, staff: bool, with_messages: bool) -> SupportRequestOut:
    msgs = (await session.scalars(select(SupportMessage).where(SupportMessage.request_id == r.id)
                                  .order_by(SupportMessage.created_at))).all() if with_messages else []
    ids = {m.author_identity_id for m in msgs} | {r.requester_identity_id} | ({r.assigned_to} if r.assigned_to else set())
    people = await identity_facade.get_identities(session, list(ids))
    name = lambda i: people[i].display_name if i in people else "Deleted user"  # noqa: E731
    return SupportRequestOut(
        id=r.id, reference=r.reference, topic=r.topic, subject=r.subject, status=r.status, context=r.context,
        firstResponseDueAt=r.first_response_due_at, firstRespondedAt=r.first_responded_at,
        overdue=r.first_responded_at is None and r.status in OPEN and r.first_response_due_at < clock.now(),
        resolvedAt=r.resolved_at, requesterName=name(r.requester_identity_id) if staff else None,
        assignedTo=r.assigned_to if staff else None, assignedToName=name(r.assigned_to) if staff and r.assigned_to else None,
        messages=[SupportMessageOut(id=m.id, fromStaff=m.from_staff,
                                    authorName=("Zoikorum support" if m.from_staff and not staff else name(m.author_identity_id)),
                                    body=m.body, createdAt=m.created_at) for m in msgs],
        createdAt=r.created_at, updatedAt=r.updated_at)


async def open_request(session: AsyncSession, actor: Actor, body: SupportRequestIn) -> SupportRequestOut:
    open_count = len((await session.scalars(select(SupportRequest.id).where(
        SupportRequest.requester_identity_id == actor.identity_id, SupportRequest.status.in_(OPEN)))).all())
    if open_count >= MAX_OPEN:
        raise RateLimited("You have several open requests. Reply in one of them, or wait for an answer.")
    context = body.context.model_dump(mode="json", exclude_none=True)
    if body.context.contractId:  # only an engagement the person is part of is attached
        c = await contract_facade.get_contract(session, body.context.contractId)
        if c is None:
            context.pop("contractId")
        else:
            context["engagement"] = c.reference
    r = SupportRequest(reference="ZK-SUP-" + uuid.uuid4().hex[:8].upper(), requester_identity_id=actor.identity_id,
                       topic=body.topic, subject=body.subject.strip(), context=context, status="OPEN",
                       first_response_due_at=clock.add_business_days(clock.now(), 1))
    session.add(r)
    await session.flush()
    session.add(SupportMessage(request_id=r.id, author_identity_id=actor.identity_id, body=body.message.strip()))
    _evt(session, E.SUPPORT_REQUEST_OPENED, r)
    await session.flush()
    return await _out(session, r, False, True)


async def _mine(session: AsyncSession, actor: Actor, request_id: uuid.UUID, lock: bool = False) -> SupportRequest:
    r = await session.get(SupportRequest, request_id, with_for_update=lock)
    if r is None or r.requester_identity_id != actor.identity_id:
        raise NotFound("Support request not found")
    return r


async def my_requests(session: AsyncSession, actor: Actor) -> list[SupportRequestOut]:
    rows = (await session.scalars(select(SupportRequest).where(SupportRequest.requester_identity_id == actor.identity_id)
                                  .order_by(SupportRequest.updated_at.desc()).limit(100))).all()
    return [await _out(session, r, False, False) for r in rows]


async def get_mine(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> SupportRequestOut:
    return await _out(session, await _mine(session, actor, request_id), False, True)


async def reply_mine(session: AsyncSession, actor: Actor, request_id: uuid.UUID, body: SupportReplyIn) -> SupportRequestOut:
    r = await _mine(session, actor, request_id, lock=True)
    session.add(SupportMessage(request_id=r.id, author_identity_id=actor.identity_id, body=body.message.strip()))
    r.status, r.resolved_at = "OPEN", None  # a reply re-opens a resolved request
    await session.flush()
    return await _out(session, r, False, True)


async def resolve_mine(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> SupportRequestOut:
    r = await _mine(session, actor, request_id, lock=True)
    r.status, r.resolved_at = "RESOLVED", clock.now()
    await session.flush()
    return await _out(session, r, False, True)


# ---- Support agents ------------------------------------------------------------------------------------------------

async def queue(session: AsyncSession, actor: Actor, status: str | None = None) -> list[SupportRequestOut]:
    """Open requests first, late first-answers on top, then oldest."""
    actor.require_capability(Cap.SUPPORT_READ)
    stmt = select(SupportRequest)
    stmt = stmt.where(SupportRequest.status == status) if status else stmt.where(SupportRequest.status.in_(OPEN))
    late = case((SupportRequest.first_responded_at.is_(None) & (SupportRequest.first_response_due_at < clock.now()), 0), else_=1)
    rows = (await session.scalars(stmt.order_by(late, SupportRequest.created_at).limit(200))).all()
    return [await _out(session, r, True, False) for r in rows]


async def get_for_agent(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> SupportRequestOut:
    actor.require_capability(Cap.SUPPORT_READ)
    r = await session.get(SupportRequest, request_id)
    if r is None:
        raise NotFound("Support request not found")
    return await _out(session, r, True, True)


async def agent_reply(session: AsyncSession, actor: Actor, request_id: uuid.UUID, body: SupportReplyIn) -> SupportRequestOut:
    actor.require_capability(Cap.SUPPORT_REPLY)
    r = await session.get(SupportRequest, request_id, with_for_update=True)
    if r is None:
        raise NotFound("Support request not found")
    if r.requester_identity_id == actor.identity_id:
        raise Conflict("Someone else answers your own request", code="OWN_REQUEST")
    session.add(SupportMessage(request_id=r.id, author_identity_id=actor.identity_id, from_staff=True, body=body.message.strip()))
    r.assigned_to = r.assigned_to or actor.identity_id
    r.first_responded_at = r.first_responded_at or clock.now()
    if body.resolve:
        r.status, r.resolved_at = "RESOLVED", clock.now()
        _evt(session, E.SUPPORT_REQUEST_RESOLVED, r)
    else:
        r.status = "WAITING_ON_YOU"
        _evt(session, E.SUPPORT_REQUEST_ANSWERED, r)
    await session.flush()
    return await _out(session, r, True, True)
