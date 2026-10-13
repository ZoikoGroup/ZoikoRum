"""Reference data loaded by migrations and the test harness."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.marketplace.service import seed_default_taxonomy


async def seed(session: AsyncSession) -> None:
    await seed_default_taxonomy(session)
