"""Support facade - the interface other domains use.

A help request already has a native owner (``assigned_to``: set when an agent first answers). Staff case ownership
(admin/assignments.py) reads and writes that field here, so the support screen and the work queue show the same owner.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.support.models import SupportRequest

OPEN = ("OPEN", "WAITING_ON_YOU")


async def request_exists(session: AsyncSession, request_id: uuid.UUID) -> bool:
    return await session.get(SupportRequest, request_id) is not None


async def set_assignee(session: AsyncSession, request_id: uuid.UUID, owner_id: uuid.UUID | None) -> uuid.UUID | None:
    """Set (or clear) the request's owner. Returns the previous owner."""
    r = await session.get(SupportRequest, request_id, with_for_update=True)
    if r is None:
        return None
    previous, r.assigned_to = r.assigned_to, owner_id
    return previous


async def open_assignees(session: AsyncSession) -> dict[uuid.UUID, uuid.UUID]:
    """Owner of every open request that has one."""
    rows = (await session.execute(select(SupportRequest.id, SupportRequest.assigned_to).where(
        SupportRequest.status.in_(OPEN), SupportRequest.assigned_to.is_not(None)))).all()
    return dict(rows)


# ---- Staff console search (admin/search.py) --------------------------------------------------------------------------

async def staff_search_requests(session: AsyncSession, term: str, exact_id: uuid.UUID | None, limit: int) -> list[dict]:
    """Help requests whose reference or subject contains ``term`` (or whose id is ``exact_id``), newest first:
    [{"id", "reference", "subject", "topic", "status", "requesterIdentityId"}]. Message bodies are never searched."""
    from sqlalchemy import func, or_

    like = "%" + term.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    match = [func.lower(SupportRequest.reference).like(like, escape="\\"), func.lower(SupportRequest.subject).like(like, escape="\\")]
    if exact_id:
        match.append(SupportRequest.id == exact_id)
    rows = (await session.scalars(select(SupportRequest).where(or_(*match))
                                  .order_by(SupportRequest.created_at.desc(), SupportRequest.id).limit(limit))).all()
    return [{"id": r.id, "reference": r.reference, "subject": r.subject, "topic": r.topic, "status": r.status,
             "requesterIdentityId": r.requester_identity_id} for r in rows]
