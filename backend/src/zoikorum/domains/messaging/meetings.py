"""Meetings in a conversation: a title, a time, a length and a video link.

The link is the person's own (Zoom, Teams, Google Meet: any https address) or, when they leave it empty, a new room on
the configured video service (ZK_MEETING_BASE_URL, Jitsi Meet by default; long random room names). Scheduling or
cancelling posts a message in the conversation, so it is part of the record; meetings also appear in each person's
private calendar feed.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.identity import facade as identity
from zoikorum.domains.messaging.models import Meeting
from zoikorum.domains.messaging.service import append_message, checked_thread
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.errors import NotFound, ValidationFailed


class MeetingIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    startsAt: datetime
    durationMinutes: int = Field(ge=15, le=480)
    joinUrl: str | None = Field(default=None, max_length=500)


class MeetingOut(BaseModel):
    id: uuid.UUID
    threadId: uuid.UUID
    title: str
    startsAt: datetime
    durationMinutes: int
    joinUrl: str
    status: str
    createdAt: datetime


def _out(m: Meeting) -> MeetingOut:
    return MeetingOut(id=m.id, threadId=m.thread_id, title=m.title, startsAt=m.starts_at, durationMinutes=m.duration_minutes,
                      joinUrl=m.join_url, status=m.status, createdAt=m.created_at)


def _link(given: str | None) -> str:
    if given and given.strip():
        url = given.strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValidationFailed("The meeting link must be an https address", code="MEETING_LINK_INVALID")
        return url
    base = get_settings().meeting_base_url
    if not base:
        raise ValidationFailed("Paste the meeting link (Zoom, Teams or Google Meet)", code="MEETING_LINK_REQUIRED")
    return base.rstrip("/") + "/zoikorum-" + secrets.token_urlsafe(18).replace("_", "").replace("-", "")[:24]


def _when(m: Meeting) -> str:
    return f"{m.starts_at.strftime('%a %d %b %Y, %H:%M')} UTC, {m.duration_minutes} min"


async def schedule(session: AsyncSession, actor: Actor, thread_id: uuid.UUID, body: MeetingIn) -> MeetingOut:
    thread, _ = await checked_thread(session, actor, thread_id, write=True)
    starts = body.startsAt if body.startsAt.tzinfo else body.startsAt.replace(tzinfo=clock.now().tzinfo)
    if starts < clock.now() - timedelta(minutes=5):
        raise ValidationFailed("A meeting cannot start in the past", code="MEETING_IN_PAST")
    m = Meeting(thread_id=thread.id, title=body.title.strip(), starts_at=starts, duration_minutes=body.durationMinutes,
                join_url=_link(body.joinUrl), created_by=actor.identity_id, status="SCHEDULED")
    session.add(m)
    await session.flush()
    account = await identity.get_identity(session, actor.identity_id)
    await append_message(session, thread, f"Meeting scheduled: {m.title}\n{_when(m)}\nJoin: {m.join_url}",
                         sender=actor.identity_id, name=account.display_name)
    return _out(m)


async def list_for_thread(session: AsyncSession, actor: Actor, thread_id: uuid.UUID) -> list[MeetingOut]:
    thread, _ = await checked_thread(session, actor, thread_id)
    rows = (await session.scalars(select(Meeting).where(
        Meeting.thread_id == thread.id, Meeting.starts_at >= clock.now() - timedelta(days=1)).order_by(Meeting.starts_at))).all()
    return [_out(m) for m in rows]


async def cancel(session: AsyncSession, actor: Actor, meeting_id: uuid.UUID) -> MeetingOut:
    m = await session.get(Meeting, meeting_id, with_for_update=True)
    if m is None:
        raise NotFound("Meeting not found")
    thread, _ = await checked_thread(session, actor, m.thread_id, write=True)
    if m.status != "CANCELLED":
        m.status = "CANCELLED"
        account = await identity.get_identity(session, actor.identity_id)
        await append_message(session, thread, f"Meeting cancelled: {m.title} ({_when(m)})", sender=actor.identity_id,
                             name=account.display_name)
    return _out(m)
