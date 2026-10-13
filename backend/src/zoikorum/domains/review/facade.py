import uuid
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from zoikorum.domains.review.models import Review


async def rating_stats(session: AsyncSession, professional_id: uuid.UUID) -> dict:
    count, average = (await session.execute(select(func.count(Review.id), func.avg(Review.rating)).where(Review.professional_id == professional_id))).one()
    return {"reviewCount": count, "averageRating": round(float(average), 2) if average is not None else None}
