"""Tasks on an engagement: a shared checklist of who does what by when (buyer and professional both see and tick it).

Tasks organise the work; they are not contract terms, so adding or ticking one never needs re-signing. Each change is
recorded in the audit trail.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.contract.models import Contract, EngagementTask, Milestone
from zoikorum.domains.contract.service import _viewer
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.events import record_audit

MAX_TASKS = 200


class TaskIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    owner: Literal["BUYER", "PROFESSIONAL"]
    dueDate: date | None = None
    milestoneId: uuid.UUID | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    owner: Literal["BUYER", "PROFESSIONAL"] | None = None
    dueDate: date | None = None
    done: bool | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    contractId: uuid.UUID
    milestoneId: uuid.UUID | None
    title: str
    owner: str
    dueDate: date | None
    done: bool
    doneAt: datetime | None
    overdue: bool
    createdAt: datetime


def _out(t: EngagementTask) -> TaskOut:
    return TaskOut(id=t.id, contractId=t.contract_id, milestoneId=t.milestone_id, title=t.title, owner=t.owner, dueDate=t.due_date,
                   done=t.done_at is not None, doneAt=t.done_at,
                   overdue=t.done_at is None and t.due_date is not None and t.due_date < clock.now().date(), createdAt=t.created_at)


async def _party(session: AsyncSession, actor: Actor, contract_id: uuid.UUID, *, write: bool = False) -> Contract:
    c = await session.get(Contract, contract_id)
    if c is None:
        raise NotFound("Contract not found")
    side = await _viewer(session, actor, c)
    if write and side not in ("BUYER", "PROFESSIONAL"):
        raise Forbidden("Only the buyer and the professional can change the task list")
    if write and c.status not in ("PENDING_SIGNATURE", "ACTIVE", "DISPUTED"):
        raise Conflict("The engagement has ended; its task list is read-only", code="CONTRACT_CLOSED")
    return c


def _audit(session: AsyncSession, c: Contract, t: EngagementTask, what: str) -> None:
    record_audit(session, f"contract.task_{what}", object_type="EngagementTask", object_id=t.id, tenant_id=c.organization_id,
                 details={"contractId": str(c.id), "title": t.title, "owner": t.owner})


async def list_tasks(session: AsyncSession, actor: Actor, contract_id: uuid.UUID) -> list[TaskOut]:
    await _party(session, actor, contract_id)
    rows = (await session.scalars(select(EngagementTask).where(EngagementTask.contract_id == contract_id)
                                  .order_by(EngagementTask.done_at.is_not(None), EngagementTask.due_date.asc().nulls_last(),
                                            EngagementTask.created_at))).all()
    return [_out(t) for t in rows]


async def add(session: AsyncSession, actor: Actor, contract_id: uuid.UUID, body: TaskIn) -> TaskOut:
    c = await _party(session, actor, contract_id, write=True)
    if body.milestoneId and (m := await session.get(Milestone, body.milestoneId)) is not None and m.contract_id != c.id:
        raise ValidationFailed("That milestone belongs to another engagement")
    if (await session.scalar(select(func.count()).select_from(EngagementTask).where(EngagementTask.contract_id == c.id)) or 0) >= MAX_TASKS:
        raise Conflict(f"An engagement can have up to {MAX_TASKS} tasks", code="TOO_MANY_TASKS")
    t = EngagementTask(contract_id=c.id, milestone_id=body.milestoneId, title=body.title.strip(), owner=body.owner,
                       due_date=body.dueDate, created_by=actor.identity_id)
    session.add(t)
    await session.flush()
    _audit(session, c, t, "added")
    return _out(t)


async def update(session: AsyncSession, actor: Actor, task_id: uuid.UUID, body: TaskPatch) -> TaskOut:
    t = await session.get(EngagementTask, task_id, with_for_update=True)
    if t is None:
        raise NotFound("Task not found")
    c = await _party(session, actor, t.contract_id, write=True)
    if body.title is not None:
        t.title = body.title.strip()
    if body.owner is not None:
        t.owner = body.owner
    if "dueDate" in body.model_fields_set:
        t.due_date = body.dueDate
    if body.done is not None and body.done != (t.done_at is not None):
        t.done_at, t.done_by = (clock.now(), actor.identity_id) if body.done else (None, None)
    _audit(session, c, t, "done" if body.done else "updated")
    return _out(t)


async def remove(session: AsyncSession, actor: Actor, task_id: uuid.UUID) -> None:
    t = await session.get(EngagementTask, task_id, with_for_update=True)
    if t is None:
        raise NotFound("Task not found")
    c = await _party(session, actor, t.contract_id, write=True)
    _audit(session, c, t, "removed")
    await session.delete(t)
