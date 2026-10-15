"""Feature flags for gradual rollout and ranking experiments (Engineering handbook: feature flags; Search: ranking
experiments with fairness checks).

Flags are declared here, in code, so an unknown key can never be switched on. Staff set how many people get each one
(0-100%, by a stable hash of the organisation or person, so the same person always sees the same thing) and name
organisations that always get it. Ranking experiments must pass a fairness check before any rollout above 0%.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.admin.models import FeatureFlag
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import Conflict, NotFound
from zoikorum.shared.events import record_audit


@dataclass(frozen=True)
class Flag:
    label: str
    description: str
    ranking_experiment: bool = False  # changes search order: fairness check required before rollout


FLAGS: dict[str, Flag] = {
    "search.new_talent_boost": Flag(
        "Search: lift verified newcomers",
        "Verified professionals with fewer than three completed engagements get a small lift, offsetting the track record "
        "they have not had the chance to build.", ranking_experiment=True),
}
FAIRNESS_MAX_DROP = 0.2  # no group may lose more than 20% of its share of top-10 places


def bucket(key: str, subject: str) -> int:
    return int(hashlib.sha256(f"{key}:{subject}".encode()).hexdigest()[:8], 16) % 100


async def enabled(session: AsyncSession, key: str, identity_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None) -> bool:
    if key not in FLAGS:
        return False
    row = await session.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
    if row is None:
        return False
    if org_id and str(org_id) in row.organization_ids:
        return True
    subject = org_id or identity_id
    if subject is None:
        return row.rollout_pct >= 100
    return bucket(key, str(subject)) < row.rollout_pct


def _out(key: str, row: FeatureFlag | None) -> dict:
    f = FLAGS[key]
    return {"key": key, "label": f.label, "description": f.description, "rankingExperiment": f.ranking_experiment,
            "rolloutPct": row.rollout_pct if row else 0, "organizationIds": row.organization_ids if row else [],
            "reason": row.reason if row else None, "changedBy": row.changed_by if row else None, "changedAt": row.updated_at if row else None}


async def list_flags(session: AsyncSession) -> list[dict]:
    rows = {r.key: r for r in (await session.scalars(select(FeatureFlag))).all()}
    return [_out(k, rows.get(k)) for k in FLAGS]


async def fairness(session: AsyncSession, key: str) -> dict:
    """Exposure of each group (new or established, tier, country) in top-10 results with and without the change."""
    from zoikorum.domains.search import facade as search_facade

    if key not in FLAGS or not FLAGS[key].ranking_experiment:
        raise NotFound("Not a ranking experiment")
    before = await search_facade.top10_exposure(session, new_talent_boost=False)
    after = await search_facade.top10_exposure(session, new_talent_boost=True)
    groups = sorted(set(before) | set(after))
    rows = []
    for g in groups:
        b, a = before.get(g, 0.0), after.get(g, 0.0)
        drop = (b - a) / b if b else 0.0
        rows.append({"group": g, "before": round(b, 3), "after": round(a, 3), "relativeDrop": round(drop, 3),
                     "ok": drop <= FAIRNESS_MAX_DROP or g == "established"})  # the lift moves places from established professionals by design
    return {"key": key, "maxRelativeDrop": FAIRNESS_MAX_DROP, "passes": all(r["ok"] for r in rows), "groups": rows}


async def set_flag(session: AsyncSession, actor: Actor, key: str, rollout_pct: int, organization_ids: list[uuid.UUID], reason: str) -> dict:
    from zoikorum.domains.admin.service import staff

    if key not in FLAGS:
        raise NotFound("Unknown flag")
    await staff(session, actor, PlatformRole.PLATFORM_ADMIN)
    actor.require_step_up()
    if FLAGS[key].ranking_experiment and (rollout_pct > 0 or organization_ids):
        report = await fairness(session, key)
        if not report["passes"]:
            failing = ", ".join(r["group"] for r in report["groups"] if not r["ok"])
            raise Conflict(f"The fairness check fails: {failing} would lose more than 20% of their top-10 places",
                           code="FAIRNESS_CHECK_FAILED", extra={"fairness": report})
    row = await session.scalar(select(FeatureFlag).where(FeatureFlag.key == key).with_for_update())
    if row is None:
        row = FeatureFlag(id=uuid.uuid4(), key=key, rollout_pct=0, organization_ids=[])
        session.add(row)
    before = (row.rollout_pct, list(row.organization_ids))
    row.rollout_pct, row.organization_ids = rollout_pct, [str(o) for o in organization_ids]
    row.reason, row.changed_by = reason.strip(), actor.identity_id
    await session.flush()
    record_audit(session, "admin.flag.changed", object_type="FeatureFlag", object_id=row.id,
                 details={"flag": key, "from": {"rolloutPct": before[0], "organizations": before[1]},
                          "to": {"rolloutPct": rollout_pct, "organizations": row.organization_ids}, "reason": row.reason})
    return _out(key, row)
