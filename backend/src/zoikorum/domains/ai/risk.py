"""Fraud and risk scoring (Trust & Safety: risk scoring from payment and behaviour signals).

Each signal about a person or an organisation is recorded once. The risk score is the weighted sum of the last 30 days
(capped at 100), with the reasons listed. Crossing REVIEW_AT opens an advisory case for Trust & Safety (Level 0): a
person decides; nothing is restricted, and no trust tier changes, because of a score.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.ai.models import RiskObservation
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

WINDOW = timedelta(days=30)
REVIEW_AT = 60
# (weight per occurrence, most points from this signal in the window, plain-language label)
WEIGHTS = {
    "LOGIN_FAILURE": (2, 20, "failed sign-ins"),
    "DISPUTE": (10, 30, "disputes opened"),
    "MESSAGE_FLAG": (8, 24, "messages flagged"),
    "PAYMENT_FAILED": (8, 32, "failed payments"),
    "CHARGEBACK": (30, 60, "chargebacks"),
    "FUNDING_REVERSED": (20, 40, "escrow funding taken back"),
    "DUPLICATE_ACCOUNT": (25, 50, "suspected duplicate accounts"),
    "DISPUTE_PATTERN": (20, 20, "disputes repeatedly decided against them"),
}
SCORE_FLAG = "SCORE_FLAG"  # recorded when a review was opened, so one is opened at most once per window


async def score(session: AsyncSession, subject_type: str, subject_id: uuid.UUID) -> dict:
    since = clock.now() - WINDOW
    counts = dict((await session.execute(select(RiskObservation.kind, func.count()).where(
        RiskObservation.subject_type == subject_type, RiskObservation.identity_id == subject_id,
        RiskObservation.created_at >= since, RiskObservation.kind != SCORE_FLAG).group_by(RiskObservation.kind))).all())
    parts = []
    for kind, n in sorted(counts.items()):
        weight, cap, label = WEIGHTS.get(kind, (5, 15, kind.replace("_", " ").lower()))
        parts.append({"signal": kind, "label": label, "count": n, "points": min(cap, weight * n)})
    total = min(100, sum(p["points"] for p in parts))
    return {"subjectType": subject_type, "subjectId": subject_id, "score": total, "reviewAt": REVIEW_AT,
            "windowDays": WINDOW.days, "signals": sorted(parts, key=lambda p: -p["points"])}


async def observe(session: AsyncSession, event_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID, kind: str, at) -> None:
    """Record one signal, then open an advisory review if the score has just crossed the line."""
    if await session.scalar(select(RiskObservation.id).where(RiskObservation.source_event_id == event_id)):
        return
    session.add(RiskObservation(source_event_id=event_id, identity_id=subject_id, kind=kind, subject_type=subject_type, created_at=at))
    await session.flush()
    result = await score(session, subject_type, subject_id)
    if result["score"] < REVIEW_AT:
        return
    if await session.scalar(select(RiskObservation.id).where(
            RiskObservation.subject_type == subject_type, RiskObservation.identity_id == subject_id,
            RiskObservation.kind == SCORE_FLAG, RiskObservation.created_at >= clock.now() - WINDOW)):
        return
    session.add(RiskObservation(source_event_id=uuid.uuid4(), identity_id=subject_id, kind=SCORE_FLAG, subject_type=subject_type,
                                created_at=clock.now()))
    reasons = ", ".join(f"{p['count']} {p['label']}" for p in result["signals"][:3])
    record_event(session, E.RISK_FLAG_RAISED, aggregate_type="Organization" if subject_type == "ORGANIZATION" else "Identity",
                 aggregate_id=subject_id, payload={"subjectType": subject_type, "subjectId": subject_id,
                                                   **({"identityId": subject_id} if subject_type == "IDENTITY" else {"organizationId": subject_id}),
                                                   "reasonCode": "RISK_SCORE_HIGH", "riskScore": result["score"],
                                                   "summary": f"Risk score {result['score']} in {WINDOW.days} days: {reasons}.",
                                                   "advisoryOnly": True, "sourceEventId": event_id})


async def top(session: AsyncSession, actor: Actor, limit: int = 25) -> list[dict]:
    """Trust & Safety: the highest risk scores now."""
    actor.require_platform_role(PlatformRole.TS_ANALYST, PlatformRole.RISK_LEAD, PlatformRole.PLATFORM_ADMIN)
    since = clock.now() - WINDOW
    subjects = (await session.execute(select(RiskObservation.subject_type, RiskObservation.identity_id).where(
        RiskObservation.created_at >= since, RiskObservation.kind != SCORE_FLAG).distinct())).all()
    scored = [await score(session, t, i) for t, i in subjects]
    return sorted(scored, key=lambda r: -r["score"])[:limit]


async def explain(session: AsyncSession, actor: Actor, subject_type: str, subject_id: uuid.UUID) -> dict:
    actor.require_platform_role(PlatformRole.TS_ANALYST, PlatformRole.RISK_LEAD, PlatformRole.PLATFORM_ADMIN)
    return await score(session, subject_type, subject_id)
