"""Audit facade. Other domains WRITE audit entries via
``shared.events.record_audit`` (outbox), never by calling this module.
This facade exposes read-only activity timelines (e.g. engagement activity log)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.audit.models import AuditRecord


@dataclass(frozen=True)
class TimelineEntry:
    occurred_at: datetime
    action: str
    actor_id: str | None
    object_type: str
    object_id: str
    hash: str


async def timeline_for_objects(session: AsyncSession, object_ids: list[str], limit: int = 500) -> list[TimelineEntry]:
    if not object_ids:
        return []
    rows = (
        await session.scalars(
            select(AuditRecord).where(AuditRecord.object_id.in_(object_ids)).order_by(AuditRecord.seq).limit(limit)
        )
    ).all()
    return [TimelineEntry(r.occurred_at, r.action, r.actor_id, r.object_type, r.object_id, r.hash) for r in rows]


async def replay_events(session: AsyncSession, after_seq: int, limit: int = 500) -> list:
    from zoikorum.shared.event_catalog import ALL_EVENTS
    from zoikorum.shared.events import EventEnvelope, EventMetadata
    rows = (await session.scalars(select(AuditRecord).where(AuditRecord.seq > after_seq).order_by(AuditRecord.seq).limit(limit))).all()
    return [(r.seq, EventEnvelope(eventId=r.source_event_id, eventType=r.action if r.action in ALL_EVENTS else "zoikorum.audit.entry.requested.v1",
        occurredAt=r.occurred_at, producedBy="audit-replay", correlationId=r.correlation_id,
        aggregateType=r.object_type, aggregateId=r.object_id, tenantId=r.tenant_id,
        metadata=EventMetadata(actorId=r.actor_id, actorType=r.actor_type, authStrength=r.auth_strength, policyVersion=r.policy_version),
        payload=r.details)) for r in rows]
