"""Trust domain: recompute tier and score from verification, profile and enforcement facts.

Recompute is synchronous inside the consumer, so adverse changes (failed, expired or revoked checks,
enforcement) take effect within one event delivery. AI risk flags are recorded and shown, never tier-changing.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.marketplace import facade as marketplace_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.trust.models import TierHistory, TrustProfile, TrustSignal
from zoikorum.domains.trust.rules import TIER_LABEL, Check, Facts, evaluate
from zoikorum.domains.trust.schemas import SignalOut, TierChangeOut, TrustHistoryOut, TrustOut
from zoikorum.domains.verification import facade as verification_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import NotFound
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, record_event

OPERATORS = (PlatformRole.TS_ANALYST, PlatformRole.COMPLIANCE_OFFICER, PlatformRole.RISK_LEAD, PlatformRole.PLATFORM_ADMIN)
_ADVERSE = {E.VERIFICATION_FAILED, E.VERIFICATION_EXPIRED, E.VERIFICATION_REVOKED}


def _evt(session: AsyncSession, event_type: str, prof: TrustProfile, **payload) -> None:
    record_event(session, event_type, aggregate_type="TrustProfile", aggregate_id=prof.id,
                 tenant_id=prof.professional_id, payload={"professionalId": prof.professional_id, **payload})


async def _profile(session: AsyncSession, professional_id: uuid.UUID) -> TrustProfile:
    """Get-or-create, locked. Safe under concurrent consumers."""
    await session.execute(pg_insert(TrustProfile).values(
        id=uuid.uuid4(), professional_id=professional_id, tier="C", score=0, dimensions={}, explanation=[],
        flags=[], engagement_suspended=False,
    ).on_conflict_do_nothing(index_elements=["professional_id"]))
    return await session.scalar(select(TrustProfile).where(TrustProfile.professional_id == professional_id).with_for_update())


async def _record_signal(session: AsyncSession, prof: TrustProfile, event: EventEnvelope, signal_type: str,
                         summary: str, adverse: bool) -> bool:
    """Returns False when this event was already recorded (at-least-once delivery)."""
    res = await session.execute(pg_insert(TrustSignal).values(
        id=uuid.uuid4(), professional_id=prof.professional_id, source_event_id=event.eventId,
        source_event_type=event.eventType, signal_type=signal_type, adverse=adverse, summary=summary[:300],
    ).on_conflict_do_nothing(index_elements=["professional_id", "source_event_id"]))
    if res.rowcount:
        _evt(session, E.TRUST_SIGNAL_ADDED, prof, signalType=signal_type, sourceEvent=event.eventType, adverse=adverse)
    return bool(res.rowcount)


async def recompute(session: AsyncSession, prof: TrustProfile, source_event_type: str) -> None:
    pro = await professional_facade.get_professional(session, prof.professional_id)
    if pro is None:
        return
    checks = await verification_facade.get_checks(session, "PROFESSIONAL", pro.id)
    specs = await marketplace_facade.get_specializations(session, list(pro.specializations))
    result = evaluate(Facts(
        checks=tuple(Check(c.verification_type, c.status, c.jurisdiction, c.specialization) for c in checks),
        credential_required=frozenset(s for s, i in specs.items() if i.requires_credential),
        regulated=any(i.regulated for i in specs.values()),
        licensed=frozenset(pro.licensed_jurisdictions), served=frozenset(pro.jurisdictions_served),
        engagement_suspended=prof.engagement_suspended,
    ))
    old_tier = prof.tier
    changed = (result.tier, result.score, result.dimensions, list(result.explanation)) != (
        prof.tier, prof.score, prof.dimensions, prof.explanation)
    prof.tier, prof.score, prof.dimensions, prof.explanation = result.tier, result.score, result.dimensions, list(result.explanation)
    prof.recomputed_at = clock.now()
    if changed:
        _evt(session, E.TRUST_SCORE_RECOMPUTED, prof, score=result.score, tier=result.tier, dimensions=result.dimensions)
    if result.tier != old_tier:
        reasons = list(result.explanation)
        session.add(TierHistory(professional_id=prof.professional_id, from_tier=old_tier, to_tier=result.tier,
                                reasons=reasons, source_event_type=source_event_type))
        _evt(session, E.TRUST_TIER_CHANGED, prof, fromTier=old_tier, toTier=result.tier, reasons=reasons)
    await session.flush()


# ---- Event consumers -----------------------------------------------------------

async def on_professional_registered(session: AsyncSession, event: EventEnvelope) -> None:
    prof = await _profile(session, uuid.UUID(str(event.payload["professionalId"])))
    await recompute(session, prof, event.eventType)


async def on_verification(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    if p.get("subjectType") != "PROFESSIONAL":
        return
    prof = await _profile(session, uuid.UUID(str(p["subjectId"])))
    outcome = event.eventType.split(".")[-2].replace("_", " ")  # "started", "completed", "needs info" ...
    await _record_signal(session, prof, event, "VERIFICATION", f"{p.get('label')}: {outcome}", event.eventType in _ADVERSE)
    await recompute(session, prof, event.eventType)


async def on_profile_changed(session: AsyncSession, event: EventEnvelope) -> None:
    """Specializations or jurisdictions changed: credential and insurance requirements may change."""
    p = event.payload
    if event.eventType == E.PROFILE_UPDATED and "specializations" not in p.get("changes", []):
        return
    prof = await _profile(session, uuid.UUID(str(p["professionalId"])))
    await recompute(session, prof, event.eventType)


async def on_enforcement(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    if p.get("subjectType") != "PROFESSIONAL" or p.get("action") != "ENGAGEMENT_SUSPENSION":
        return
    prof = await _profile(session, uuid.UUID(str(p["subjectId"])))
    applied = event.eventType == E.ENFORCEMENT_ACTION_APPLIED
    summary = f"Engagement suspension {'applied' if applied else 'reversed'} ({p.get('reasonCode')})"
    if await _record_signal(session, prof, event, "ENFORCEMENT", summary, applied):
        prof.engagement_suspended = applied
    await recompute(session, prof, event.eventType)


async def on_risk_flag(session: AsyncSession, event: EventEnvelope) -> None:
    """Risk flags are recorded for Trust & Safety review; they never change the tier."""
    p = event.payload
    if p.get("subjectType") != "PROFESSIONAL":
        return
    prof = await _profile(session, uuid.UUID(str(p["subjectId"])))
    codes = [str(c) for c in p.get("reasonCodes", [])]
    if await _record_signal(session, prof, event, "RISK_FLAG", f"Risk flag: {', '.join(codes)}", True):
        prof.flags = sorted(set(prof.flags) | set(codes))
        for code in codes:
            _evt(session, E.TRUST_PROFILE_FLAGGED, prof, flag=code, reasonCode=code)


# ---- Queries -------------------------------------------------------------------

def _out(professional_id: uuid.UUID, prof: TrustProfile | None) -> TrustOut:
    tier = prof.tier if prof else "C"
    return TrustOut(professionalId=professional_id, tier=tier, tierLabel=TIER_LABEL[tier], score=prof.score if prof else 0,
                    dimensions=prof.dimensions if prof else {}, explanation=prof.explanation if prof else [],
                    updatedAt=prof.recomputed_at if prof else None)


async def _require_visible(session: AsyncSession, actor: Actor | None, professional_id: uuid.UUID, *, owner_only: bool) -> None:
    pro = await professional_facade.get_professional(session, professional_id)
    own = bool(actor and pro and pro.identity_id == actor.identity_id)
    if actor and not own and actor.has_platform_role(*OPERATORS):
        actor.require_platform_role(*OPERATORS)  # also enforces an MFA session
        return
    if pro is None or (not own and (owner_only or pro.status != "PUBLISHED")):
        raise NotFound("Professional not found")


async def get_trust(session: AsyncSession, actor: Actor | None, professional_id: uuid.UUID) -> TrustOut:
    """Public for published profiles: tier, dimensions and the plain-language explanation."""
    await _require_visible(session, actor, professional_id, owner_only=False)
    prof = await session.scalar(select(TrustProfile).where(TrustProfile.professional_id == professional_id))
    return _out(professional_id, prof)


async def history(session: AsyncSession, actor: Actor, professional_id: uuid.UUID) -> TrustHistoryOut:
    await _require_visible(session, actor, professional_id, owner_only=True)
    changes = (await session.scalars(select(TierHistory).where(TierHistory.professional_id == professional_id)
                                     .order_by(TierHistory.created_at.desc()).limit(50))).all()
    signals = (await session.scalars(select(TrustSignal).where(TrustSignal.professional_id == professional_id)
                                     .order_by(TrustSignal.created_at.desc()).limit(50))).all()
    prof = await session.scalar(select(TrustProfile).where(TrustProfile.professional_id == professional_id))
    return TrustHistoryOut(
        tierChanges=[TierChangeOut(fromTier=h.from_tier, toTier=h.to_tier, reasons=h.reasons, at=h.created_at) for h in changes],
        signals=[SignalOut(type=s.signal_type, adverse=s.adverse, summary=s.summary, at=s.created_at) for s in signals],
        flags=list(prof.flags) if prof else [],
    )
