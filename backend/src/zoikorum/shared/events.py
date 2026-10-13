"""Event envelope, outbox writer and subscriber registry.

Publishing (inside a domain command):

    record_event(session, E.PROPOSAL_ACCEPTED, aggregate_type="Proposal",
                 aggregate_id=p.id, payload={...})

The row lands in platform.outbox in the SAME transaction as the state change
(outbox pattern). The relay (shared/relay.py) delivers it to subscribers.

Subscribing (in a domain's handlers.py):

    @subscribe(E.PROPOSAL_ACCEPTED, consumer="contract.generate_from_proposal")
    async def on_proposal_accepted(session, event): ...

Every handler runs in its own transaction with inbox de-duplication, so it
MUST be safe to receive the same event twice (at-least-once delivery).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.shared import clock, context
from zoikorum.shared.event_catalog import ALL_EVENTS, domain_of
from zoikorum.shared.money import Money
from zoikorum.shared.platform_models import OutboxEvent


class EventMetadata(BaseModel):
    """Who/what caused the event - needed for audit-grade records (Handbook 11.2)."""

    model_config = ConfigDict(populate_by_name=True)

    actorId: str | None = None
    actorType: str = "system"
    authStrength: str | None = None
    policyVersion: str | None = None


class EventEnvelope(BaseModel):
    """Architecture 6.2 envelope standard."""

    model_config = ConfigDict(frozen=True)

    eventId: uuid.UUID
    eventType: str
    occurredAt: datetime
    producedBy: str
    correlationId: str
    causationId: str | None = None
    aggregateType: str
    aggregateId: str
    schemaVersion: str = "1"
    tenantId: str | None = None
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    payload: dict[str, Any]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Money):
        return value.to_dict()
    return to_jsonable_python(value, fallback=str)


def record_event(
    session: AsyncSession,
    event_type: str,
    *,
    aggregate_type: str,
    aggregate_id: Any,
    payload: dict[str, Any],
    tenant_id: Any = None,
    policy_version: str | None = None,
) -> EventEnvelope:
    """Append a domain event to the outbox in the caller's transaction."""
    if event_type not in ALL_EVENTS:
        raise ValueError(f"Unknown event type {event_type!r}; add it to shared/event_catalog.py first")
    ctx = context.current()
    envelope = EventEnvelope(
        eventId=uuid.uuid4(),
        eventType=event_type,
        occurredAt=clock.now(),
        producedBy=f"{domain_of(event_type)}-service",
        correlationId=ctx.correlation_id,
        causationId=ctx.causation_id,
        aggregateType=aggregate_type,
        aggregateId=str(aggregate_id),
        tenantId=str(tenant_id) if tenant_id is not None else ctx.tenant_id,
        metadata=EventMetadata(
            actorId=ctx.actor_id,
            actorType=ctx.actor_type,
            authStrength=ctx.auth_strength,
            policyVersion=policy_version,
        ),
        payload={k: _jsonable(v) for k, v in payload.items()},
    )
    session.add(
        OutboxEvent(
            event_id=envelope.eventId,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=envelope.aggregateId,
            tenant_id=envelope.tenantId,
            envelope=envelope.model_dump(mode="json"),
        )
    )
    return envelope


def record_audit(
    session: AsyncSession,
    action: str,
    *,
    object_type: str,
    object_id: Any,
    details: dict[str, Any] | None = None,
    evidence_hash: str | None = None,
    policy_version: str | None = None,
    tenant_id: Any = None,
) -> EventEnvelope:
    """Explicit audit-only entry for actions that are not domain events
    (e.g. evidence access, operator reads, export downloads)."""
    from zoikorum.shared.event_catalog import E

    return record_event(
        session,
        E.AUDIT_ENTRY_REQUESTED,
        aggregate_type=object_type,
        aggregate_id=object_id,
        payload={"action": action, "details": details or {}, "evidenceHash": evidence_hash},
        tenant_id=tenant_id,
        policy_version=policy_version,
    )


Handler = Callable[[AsyncSession, EventEnvelope], Awaitable[None]]

ALL = "*"


@dataclass(frozen=True)
class Subscription:
    consumer: str
    event_type: str  # exact type or "*" for every event
    handler: Handler


class SubscriberRegistry:
    def __init__(self) -> None:
        self._subs: dict[str, Subscription] = {}

    def subscribe(self, event_type: str, *, consumer: str) -> Callable[[Handler], Handler]:
        if event_type != ALL and event_type not in ALL_EVENTS:
            raise ValueError(f"Unknown event type {event_type!r}")

        def deco(fn: Handler) -> Handler:
            key = f"{consumer}|{event_type}"
            self._subs[key] = Subscription(consumer=consumer, event_type=event_type, handler=fn)
            return fn

        return deco

    def for_event(self, event_type: str) -> list[Subscription]:
        return [s for s in self._subs.values() if s.event_type in (event_type, ALL)]

    def by_consumer(self, consumer: str, event_type: str) -> Subscription | None:
        return self._subs.get(f"{consumer}|{event_type}") or self._subs.get(f"{consumer}|{ALL}")

    def all(self) -> list[Subscription]:
        return list(self._subs.values())


registry = SubscriberRegistry()
subscribe = registry.subscribe
