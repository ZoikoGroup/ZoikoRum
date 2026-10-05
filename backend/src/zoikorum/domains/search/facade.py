"""Search facade - CONTRACT. Signatures are fixed; implement bodies."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def count_eligible(session: AsyncSession, eligibility: dict[str, Any]) -> int:
    """Number of discoverable professionals matching a policy eligibility filter
    ({"minTier","requiredDimensions","jurisdictions","categories"}). Powers the
    policy builder's live impact preview ("This policy allows 214 professionals")."""
    raise NotImplementedError
