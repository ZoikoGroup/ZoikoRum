"""Messaging facade - CONTRACT. Signatures and DTOs are fixed; implement bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


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
    """context_type: PROPOSAL_REQUEST | CONTRACT | DISPUTE. Used as dispute evidence."""
    raise NotImplementedError
