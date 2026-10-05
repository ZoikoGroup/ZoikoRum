"""Trust facade - CONTRACT. Signatures and DTOs are fixed; implement bodies.

Dimension keys and values (Homepage wireframe 3.3):
  identity:     VERIFIED | PENDING | NONE
  credentials:  VALIDATED | PARTIAL | PENDING | NOT_APPLICABLE | NONE
  jurisdiction: ELIGIBLE | RESTRICTED | UNKNOWN
  restrictions: CLEAR | FLAGGED | UNKNOWN
  insurance:    VERIFIED | PENDING | NOT_REQUIRED
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class TrustSnapshot:
    professional_id: uuid.UUID
    tier: str  # "A" | "B" | "C"
    score: int  # 0..100, explainable
    dimensions: dict[str, str] = field(default_factory=dict)
    flags: tuple[str, ...] = ()  # active risk flags (reason codes)
    explanation: tuple[str, ...] = ()  # plain-language "why this tier"
    completed_contracts: int = 0
    on_time_rate_bps: int | None = None  # 0..10000
    dispute_rate_bps: int | None = None
    updated_at: datetime | None = None


async def get_trust(session: AsyncSession, professional_id: uuid.UUID) -> TrustSnapshot:
    """Never None: an unknown professional is Tier C with score 0."""
    raise NotImplementedError


async def get_trust_many(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, TrustSnapshot]:
    raise NotImplementedError
