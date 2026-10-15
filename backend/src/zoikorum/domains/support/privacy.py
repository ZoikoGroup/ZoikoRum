"""Help requests the person opened and what they wrote (shared/privacy.py)."""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.support.models import SupportMessage, SupportRequest
from zoikorum.shared import privacy


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    return {"supportRequests": await privacy.rows(session, SupportRequest, SupportRequest.requester_identity_id == identity_id),
            "supportMessages": await privacy.rows(session, SupportMessage, SupportMessage.author_identity_id == identity_id)}


async def erase(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    """The person's own words are removed; the request record (reference, dates) stays for the support history."""
    removed = (await session.execute(update(SupportMessage).where(
        SupportMessage.author_identity_id == identity_id, SupportMessage.from_staff.is_(False))
        .values(body="[removed at the person's request]"))).rowcount
    subjects = (await session.execute(update(SupportRequest).where(SupportRequest.requester_identity_id == identity_id)
                                      .values(subject="[removed]", context={}))).rowcount
    return {"supportMessagesRemoved": removed, "supportRequestsAnonymised": subjects}


privacy.register("support", export=export, erase=erase,
                 retained="Support request references and dates are kept; what you wrote is removed.")
