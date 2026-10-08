"""Trust facade - read-only interface other domains use.

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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.trust.models import TrustProfile
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.dispute import facade as dispute_facade


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
    return (await get_trust_many(session, [professional_id]))[professional_id]


async def get_trust_many(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, TrustSnapshot]:
    rows = {p.professional_id: p for p in (await session.scalars(
        select(TrustProfile).where(TrustProfile.professional_id.in_(ids)))).all()} if ids else {}
    out = {}
    for pid in ids:
        p = rows.get(pid)
        delivery = await contract_facade.delivery_stats(session, pid)
        disputes = await dispute_facade.outcome_stats(session, pid)
        denominator = delivery["engagements"]
        out[pid] = (TrustSnapshot(pid, p.tier, p.score, dict(p.dimensions), tuple(p.flags), tuple(p.explanation),
                                  completed_contracts=delivery["completed"],
                                  on_time_rate_bps=round(delivery["onTime"] * 10000 / delivery["milestonesWithDueDate"]) if delivery["milestonesWithDueDate"] else None,
                                  dispute_rate_bps=round(disputes["resolvedDisputedContracts"] * 10000 / denominator) if denominator else None,
                                  updated_at=p.recomputed_at) if p else TrustSnapshot(pid, "C", 0))
    return out
