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


LIST_PARAMS = {"spec", "tier", "verified"}


async def count_new_matches(session: AsyncSession, params: dict[str, str], published_after) -> int:
    """How many professionals matching a saved search's filters were published after the given time."""
    from zoikorum.domains.search.schemas import SearchParams

    values: dict[str, Any] = {k: ([x for x in v.split(",") if x] if k in LIST_PARAMS else v) for k, v in params.items()}
    p = SearchParams(**{k: v for k, v in values.items() if k in SearchParams.model_fields}, publishedAfter=published_after, limit=1)
    return (await service.search(session, None, p)).total
