"""Reviews the person wrote (shared/privacy.py). The rating stays on the professional's record; the name is removed."""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.review.models import Review
from zoikorum.shared import privacy
from zoikorum.shared.ddl import ERASED_NAME


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    return {"reviewsWritten": await privacy.rows(session, Review, Review.reviewer_identity_id == identity_id)}


async def erase(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    await privacy.allow_name_erasure(session)
    renamed = (await session.execute(update(Review).where(Review.reviewer_identity_id == identity_id,
                                                          Review.reviewer_name != ERASED_NAME)
                                     .values(reviewer_name=ERASED_NAME))).rowcount
    return {"reviewsAnonymised": renamed}


privacy.register("review", export=export, erase=erase,
                 retained="Ratings you gave stay on the professional's verified record, shown as from \"Deleted user\".")
