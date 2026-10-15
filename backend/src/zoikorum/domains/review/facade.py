import uuid
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from zoikorum.domains.review.models import Review


async def rating_stats(session: AsyncSession, professional_id: uuid.UUID) -> dict:
    count, average = (await session.execute(select(func.count(Review.id), func.avg(Review.rating)).where(Review.professional_id == professional_id))).one()
    return {"reviewCount": count, "averageRating": round(float(average), 2) if average is not None else None}


async def review_author(session: AsyncSession, review_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(reviewer identity, reviewed professional) of a published review, for reports about it."""
    from zoikorum.domains.review.models import Review

    r = await session.get(Review, review_id)
    return (r.reviewer_identity_id, r.professional_id) if r else None
