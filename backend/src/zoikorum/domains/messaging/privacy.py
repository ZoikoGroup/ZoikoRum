"""Messages the person sent (shared/privacy.py). The conversation stays for the other party; the name is removed."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.messaging.models import Message, ReadPosition
from zoikorum.shared import privacy
from zoikorum.shared.ddl import ERASED_NAME


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    return {"messagesSent": await privacy.rows(session, Message, Message.sender_identity_id == identity_id)}


async def erase(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    await privacy.allow_name_erasure(session)
    renamed = (await session.execute(update(Message).where(Message.sender_identity_id == identity_id,
                                                           Message.sender_name != ERASED_NAME)
                                     .values(sender_name=ERASED_NAME))).rowcount
    await session.execute(delete(ReadPosition).where(ReadPosition.identity_id == identity_id))
    return {"messagesAnonymised": renamed}


privacy.register("messaging", export=export, erase=erase,
                 retained="Messages in engagement conversations stay for the other party, shown as from \"Deleted user\".")
