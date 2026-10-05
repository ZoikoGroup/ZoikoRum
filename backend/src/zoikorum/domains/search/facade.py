"""Search facade - read-only interface other domains use."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.search import service


async def count_eligible(session: AsyncSession, eligibility: dict[str, Any]) -> int:
    """Number of discoverable professionals matching a policy eligibility filter
    ({"minTier","requiredDimensions","jurisdictions","categories"}). Powers the
    policy builder's live impact preview ("This policy allows 214 professionals")."""
    return await service.count_eligible(session, eligibility)
