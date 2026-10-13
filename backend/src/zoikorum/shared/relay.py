"""Outbox relay, consumer delivery (inbox + retry + DLQ) and durable timers.

Delivery semantics: at-least-once. Each subscriber processes an event in its own
transaction; the inbox row is inserted in that same transaction, so a replayed
event is a no-op for consumers that already succeeded (Handbook 12.4 / 21.2).

The in-process bus is the default for the modular monolith. A Kafka adapter
can replace ``publish`` without changing any domain code: producers keep
writing to the outbox, consumers keep using ``deliver``.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zoikorum.config import get_settings
from zoikorum.shared import clock, context
from zoikorum.shared.event_catalog import FINANCIAL_EVENTS
from zoikorum.shared.events import EventEnvelope, Subscription, registry
from zoikorum.shared.platform_models import ConsumerFailure, InboxEntry, OutboxEvent, Timer

log = logging.getLogger("zoikorum.relay")

_BACKOFF_SECONDS = (5, 30, 120, 600, 1800)


def _consumer_context(env: EventEnvelope, consumer: str) -> context.ExecutionContext:
    # Downstream events keep the correlation id; their causation is this event.
    return context.ExecutionContext(
        correlation_id=env.correlationId,
        causation_id=str(env.eventId),
        actor_id=f"consumer:{consumer}",
        actor_type="system",
        tenant_id=env.tenantId,
    )


async def deliver(sf: async_sessionmaker[AsyncSession], sub: Subscription, env: EventEnvelope) -> bool:
    """Run one subscriber for one event. Returns True on success (or duplicate)."""
    try:
        async with sf() as session:
            async with session.begin():
                inserted = await session.execute(
                    pg_insert(InboxEntry)
                    .values(consumer=sub.consumer, event_id=env.eventId)
                    .on_conflict_do_nothing()
                    .returning(InboxEntry.id)
                )
                if inserted.scalar_one_or_none() is None:
                    return True  # already processed by this consumer
                with context.use_context(_consumer_context(env, sub.consumer)):
                    await sub.handler(session, env)
        await _resolve_failure(sf, sub.consumer, env)
        return True
    except Exception as exc:  # noqa: BLE001 - every consumer failure is recorded
        log.warning("consumer %s failed on %s: %s", sub.consumer, env.eventType, exc)
        await _record_failure(sf, sub.consumer, env, exc)
        return False


async def _record_failure(sf, consumer: str, env: EventEnvelope, exc: Exception) -> None:
    settings = get_settings()
    async with sf() as session, session.begin():
        row = await session.scalar(
            select(ConsumerFailure)
            .where(ConsumerFailure.consumer == consumer, ConsumerFailure.event_id == env.eventId)
            .with_for_update()
        )
        if row is None:
            row = ConsumerFailure(
                consumer=consumer,
                event_id=env.eventId,
                event_type=env.eventType,
                envelope=env.model_dump(mode="json"),
                attempts=0,
                financial=env.eventType in FINANCIAL_EVENTS,
            )
            session.add(row)
        row.attempts += 1
        row.last_error = "".join(traceback.format_exception_only(type(exc), exc))[-4000:]
        if row.attempts >= settings.consumer_max_attempts:
            row.status = "DEAD"
            row.next_attempt_at = None
            log.error("consumer %s dead-lettered event %s", consumer, env.eventId)
        else:
            delay = _BACKOFF_SECONDS[min(row.attempts - 1, len(_BACKOFF_SECONDS) - 1)]
            row.status = "RETRYING"
            row.next_attempt_at = clock.now() + timedelta(seconds=delay)


async def _resolve_failure(sf, consumer: str, env: EventEnvelope) -> None:
    async with sf() as session, session.begin():
        await session.execute(
            update(ConsumerFailure)
            .where(
                ConsumerFailure.consumer == consumer,
                ConsumerFailure.event_id == env.eventId,
                ConsumerFailure.status != "RESOLVED",
            )
            .values(status="RESOLVED", next_attempt_at=None)
        )


async def publish(sf: async_sessionmaker[AsyncSession], env: EventEnvelope) -> None:
    """In-process bus: fan the event out to every matching subscriber."""
    for sub in registry.for_event(env.eventType):
        await deliver(sf, sub, env)


async def relay_once(sf: async_sessionmaker[AsyncSession], batch: int | None = None) -> int:
    """Publish one batch of unpublished outbox events in commit order."""
    batch = batch or get_settings().outbox_batch_size
    async with sf() as session, session.begin():
        rows = (
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.seq)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            await publish(sf, EventEnvelope.model_validate(row.envelope))
            row.published_at = clock.now()
    return len(rows)


async def retry_failures(sf: async_sessionmaker[AsyncSession], now: datetime | None = None) -> int:
    """Re-deliver RETRYING failures whose backoff elapsed. DEAD rows need an operator."""
    now = now or clock.now()
    async with sf() as session:
        rows = (
            await session.scalars(
                select(ConsumerFailure).where(
                    ConsumerFailure.status == "RETRYING", ConsumerFailure.next_attempt_at <= now
                )
            )
        ).all()
    count = 0
    for row in rows:
        env = EventEnvelope.model_validate(row.envelope)
        sub = registry.by_consumer(row.consumer, row.event_type)
        if sub is not None:
            await deliver(sf, sub, env)
            count += 1
    return count


async def replay_dead_letter(
    sf: async_sessionmaker[AsyncSession], failure_id: Any, *, authorised_by: str, financial_ops: bool
) -> bool:
    """Operator-triggered replay. Financial events require FINANCIAL_OPS authority."""
    async with sf() as session:
        row = await session.get(ConsumerFailure, failure_id)
    if row is None or row.status != "DEAD":
        return False
    if row.financial and not financial_ops:
        raise PermissionError("Financial dead letters require FINANCIAL_OPS authorisation")
    sub = registry.by_consumer(row.consumer, row.event_type)
    if sub is None:
        return False
    log.info("dead letter %s replayed by %s", failure_id, authorised_by)
    return await deliver(sf, sub, EventEnvelope.model_validate(row.envelope))


# ---------------------------------------------------------------------------
# Durable timers
# ---------------------------------------------------------------------------

TimerHandler = Callable[[AsyncSession, str, dict], Awaitable[None]]
_timer_handlers: dict[str, TimerHandler] = {}


def on_timer(kind: str) -> Callable[[TimerHandler], TimerHandler]:
    """Register the handler for a timer kind, e.g. ``proposal.expiry``."""

    def deco(fn: TimerHandler) -> TimerHandler:
        _timer_handlers[kind] = fn
        return fn

    return deco


async def schedule_timer(session: AsyncSession, kind: str, key: str, fire_at: datetime, payload: dict | None = None) -> None:
    """Idempotently (re)arm a timer. Re-scheduling an unfired timer moves it."""
    stmt = pg_insert(Timer).values(kind=kind, key=key, fire_at=fire_at, payload=payload or {})
    stmt = stmt.on_conflict_do_update(
        index_elements=[Timer.kind, Timer.key],
        set_={"fire_at": fire_at, "payload": payload or {}, "cancelled_at": None},
        where=Timer.fired_at.is_(None),
    )
    await session.execute(stmt)


async def cancel_timer(session: AsyncSession, kind: str, key: str) -> None:
    await session.execute(
        update(Timer)
        .where(Timer.kind == kind, Timer.key == key, Timer.fired_at.is_(None))
        .values(cancelled_at=clock.now())
    )


async def fire_due_timers(sf: async_sessionmaker[AsyncSession], now: datetime | None = None, limit: int = 200) -> int:
    now = now or clock.now()
    async with sf() as session:
        due_ids = (
            await session.scalars(
                select(Timer.id)
                .where(Timer.fired_at.is_(None), Timer.cancelled_at.is_(None), Timer.fire_at <= now)
                .order_by(Timer.fire_at)
                .limit(limit)
            )
        ).all()
    fired = 0
    for timer_id in due_ids:
        try:
            async with sf() as session, session.begin():
                t = await session.scalar(
                    select(Timer).where(Timer.id == timer_id, Timer.fired_at.is_(None)).with_for_update(skip_locked=True)
                )
                if t is None or t.cancelled_at is not None:
                    continue
                handler = _timer_handlers.get(t.kind)
                ctx = context.ExecutionContext(
                    correlation_id=t.payload.get("correlationId") or context.new_correlation_id(),
                    causation_id=f"timer:{t.id}",
                    actor_id=f"timer:{t.kind}",
                    actor_type="system",
                )
                with context.use_context(ctx):
                    if handler is not None:
                        await handler(session, t.key, t.payload)
                t.fired_at = clock.now()
                fired += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("timer %s failed: %s", timer_id, exc)
            async with sf() as session, session.begin():
                t = await session.get(Timer, timer_id)
                if t is not None:
                    t.attempts += 1
                    t.last_error = str(exc)[-4000:]
                    t.fire_at = now + timedelta(seconds=_BACKOFF_SECONDS[min(t.attempts - 1, 4)])
    return fired


async def drain(sf: async_sessionmaker[AsyncSession], *, max_rounds: int = 100) -> int:
    """Run relay + timers until quiescent. Used by tests and the CLI worker."""
    total = 0
    for _ in range(max_rounds):
        n = await relay_once(sf)
        n += await fire_due_timers(sf)
        total += n
        if n == 0:
            return total
    raise RuntimeError("drain did not reach quiescence - possible event loop between consumers")
