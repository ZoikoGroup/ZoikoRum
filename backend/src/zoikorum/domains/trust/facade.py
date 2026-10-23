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


async def tier_kpis(session: AsyncSession, since, until) -> dict:
    """Professionals per trust tier now, and tier moves in the period (verification throughput)."""
    from sqlalchemy import func

    from zoikorum.domains.trust.models import TierHistory

    now = dict((await session.execute(select(TrustProfile.tier, func.count()).group_by(TrustProfile.tier))).all())
    moves = (await session.execute(select(TierHistory.from_tier, TierHistory.to_tier, func.count()).where(
        TierHistory.created_at >= since, TierHistory.created_at < until).group_by(TierHistory.from_tier, TierHistory.to_tier))).all()
    return {"tiersNow": now, "reachedB": sum(n for f, t, n in moves if t == "B" and f == "C"),
            "reachedA": sum(n for f, t, n in moves if t == "A"), "downgrades": sum(n for f, t, n in moves if (f, t) in (("A", "B"), ("A", "C"), ("B", "C")))}


# ---- Staff admin console: tier and verification dimensions without the delivery statistics get_trust_many adds -------

DEFAULT_DIMENSIONS = {"identity": "NONE", "credentials": "NONE", "jurisdiction": "UNKNOWN"}


async def tiers_and_dimensions(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, dict[str, str]]]:
    """Per professional: (tier, dimensions). A professional not yet assessed is Tier C with nothing verified. Display
    reads only (staff console): served from the read cache, dropped on every trust change. Decisions (payouts, policy)
    use get_trust, which always reads the database."""
    from zoikorum.shared import cache

    async def load(keys: list[str]) -> dict[str, list]:
        wanted = [uuid.UUID(k) for k in keys]
        rows = dict((await session.execute(select(TrustProfile.professional_id, TrustProfile).where(
            TrustProfile.professional_id.in_(wanted)))).all())
        return {str(pid): [rows[pid].tier, {**DEFAULT_DIMENSIONS, **rows[pid].dimensions}] if pid in rows
                else ["C", dict(DEFAULT_DIMENSIONS)] for pid in wanted}

    found = await cache.cached_many(cache.TRUST_TIERS, [str(i) for i in ids], load)
    return {pid: (found[str(pid)][0], dict(found[str(pid)][1])) for pid in ids}


async def professionals_in_tiers(session: AsyncSession, tiers: tuple[str, ...]) -> list[uuid.UUID]:
    """Professionals with a trust profile in one of these tiers (those without a profile count as C: see the caller)."""
    return list((await session.scalars(select(TrustProfile.professional_id).where(TrustProfile.tier.in_(tiers)))).all())


async def admin_counts(session: AsyncSession) -> dict[str, int]:
    """Professionals in Tier A and Tier B, and those whose identity is verified."""
    from sqlalchemy import func

    tiers = dict((await session.execute(select(TrustProfile.tier, func.count()).group_by(TrustProfile.tier))).all())
    verified = await session.scalar(select(func.count()).select_from(TrustProfile).where(
        TrustProfile.dimensions["identity"].astext == "VERIFIED")) or 0
    return {"A": tiers.get("A", 0), "B": tiers.get("B", 0), "identityVerified": verified}


async def tier_trend(session: AsyncSession, since, until, points: int = 60) -> list[dict]:
    """Professionals per tier at the end of each interval of the period, rebuilt from the tier history (board brief:
    trust-tier trend). Only professionals with a tier record so far are counted; a professional is in the tier they
    moved from until their first recorded move."""
    from datetime import timedelta

    from zoikorum.domains.trust.models import TierHistory

    rows = (await session.execute(select(TierHistory.professional_id, TierHistory.from_tier, TierHistory.to_tier, TierHistory.created_at)
                                  .where(TierHistory.created_at < until).order_by(TierHistory.created_at, TierHistory.id))).all()
    if not rows:
        return []
    start = max(since, rows[0][3].replace(hour=0, minute=0, second=0, microsecond=0))
    step = timedelta(days=max(1, -(-(until - start).days // points)))
    state: dict = {}
    out, i, edge = [], 0, start + step
    while True:
        edge = min(edge, until)
        while i < len(rows) and rows[i][3] < edge:
            pid, _, to_tier, _ = rows[i]
            state[pid] = to_tier
            i += 1
        counts = {"A": 0, "B": 0, "C": 0}
        for tier in state.values():
            counts[tier] = counts.get(tier, 0) + 1
        out.append({"date": edge.isoformat(), **counts})
        if edge >= until:
            return out
        edge += step
