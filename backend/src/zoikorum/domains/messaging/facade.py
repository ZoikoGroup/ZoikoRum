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
