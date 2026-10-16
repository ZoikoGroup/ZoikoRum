"""Messaging facade - CONTRACT. Signatures and DTOs are fixed; implement bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.messaging.models import Attachment, Message, Thread


@dataclass(frozen=True)
class MessageExport:
    id: uuid.UUID
    thread_id: uuid.UUID
    sender_identity_id: uuid.UUID | None  # None for system messages
    body: str
    sent_at: datetime
    attachment_hashes: tuple[str, ...]
    content_hash: str


async def export_thread(session: AsyncSession, context_type: str, context_id: uuid.UUID) -> list[MessageExport]:
    """Return the immutable, ordered conversation record for dispute evidence."""
    if context_type not in {"PROPOSAL_REQUEST", "CONTRACT", "DISPUTE"}:
        raise ValueError(f"Unsupported messaging context type: {context_type}")

    thread = await session.scalar(
        select(Thread).where(Thread.context_type == context_type, Thread.context_id == context_id)
    )
    if thread is None:
        return []

    messages = list(
        (
            await session.scalars(
                select(Message).where(Message.thread_id == thread.id).order_by(Message.sequence)
            )
        ).all()
    )
    attachment_ids = {
        uuid.UUID(attachment_id)
        for message in messages
        for attachment_id in message.attachment_ids
    }
    attachments = {
        attachment.id: attachment
        for attachment in (
            await session.scalars(select(Attachment).where(Attachment.id.in_(attachment_ids)))
        ).all()
    } if attachment_ids else {}

    export: list[MessageExport] = []
    for message in messages:
        hashes: list[str] = []
        for attachment_id in message.attachment_ids:
            attachment = attachments.get(uuid.UUID(attachment_id))
            if attachment is None or attachment.thread_id != thread.id:
                raise RuntimeError(
                    f"Message {message.id} references missing or mismatched attachment {attachment_id}"
                )
            hashes.append(attachment.sha256)
        export.append(
            MessageExport(
                id=message.id,
                thread_id=message.thread_id,
                sender_identity_id=message.sender_identity_id,
                body=message.body,
                sent_at=message.created_at,
                attachment_hashes=tuple(hashes),
                content_hash=message.content_hash,
            )
        )
    return export


async def message_for_report(session: AsyncSession, actor, message_id: uuid.UUID) -> tuple[uuid.UUID, str] | None:
    """(sender, short excerpt) of a message the reporter can read in one of their conversations; None otherwise."""
    from zoikorum.domains.messaging import service
    from zoikorum.shared.errors import DomainError

    m = await session.get(Message, message_id)
    if m is None or m.sender_identity_id is None:
        return None
    try:
        await service.checked_thread(session, actor, m.thread_id)
    except DomainError:
        return None
    return m.sender_identity_id, m.body[:300]


async def files_for_contexts(session: AsyncSession, contexts: list[tuple[str, uuid.UUID]]):
    """Files shared in these conversations (each version is its own file)."""
    from sqlalchemy import or_

    from zoikorum.shared.uploads import FileRef

    if not contexts:
        return []
    threads = (await session.scalars(select(Thread).where(or_(*[
        (Thread.context_type == t) & (Thread.context_id == i) for t, i in contexts])))).all()
    if not threads:
        return []
    rows = (await session.scalars(select(Attachment).where(Attachment.thread_id.in_([t.id for t in threads]))
                                  .order_by(Attachment.created_at))).all()
    return [FileRef("Messages", f"{a.name} (v{a.file_version})" if a.file_version > 1 else a.name, a.sha256, a.size_bytes,
                    a.created_at, f"/v1/threads/{a.thread_id}/attachments/{a.id}") for a in rows]


async def upcoming_meetings(session: AsyncSession, org_ids: list[uuid.UUID], professional_id: uuid.UUID | None,
                            days: int = 180) -> list[dict]:
    """Scheduled meetings in the person's conversations, for their calendar feed."""
    from datetime import timedelta

    from sqlalchemy import or_

    from zoikorum.domains.messaging.models import Meeting
    from zoikorum.shared import clock

    who = []
    if org_ids:
        who.append(Thread.organization_id.in_(org_ids))
    if professional_id:
        who.append(Thread.professional_id == professional_id)
    if not who:
        return []
    now = clock.now()
    rows = (await session.execute(select(Meeting, Thread).join(Thread, Thread.id == Meeting.thread_id).where(
        or_(*who), Meeting.status == "SCHEDULED", Meeting.starts_at >= now - timedelta(days=1),
        Meeting.starts_at <= now + timedelta(days=days)))).all()
    return [{"uid": f"meeting-{m.id}", "start": m.starts_at, "end": m.starts_at + timedelta(minutes=m.duration_minutes),
             "title": m.title, "detail": f"{t.title} - join: {m.join_url}", "url": m.join_url} for m, t in rows]
