"""Shared kernel guarantees: money, state machines, outbox/inbox, retries, timers."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from zoikorum.shared import clock
from zoikorum.shared.errors import InvalidStateTransition, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event, registry
from zoikorum.shared.money import Money
from zoikorum.shared.platform_models import ConsumerFailure, InboxEntry, OutboxEvent
from zoikorum.shared.relay import fire_due_timers, on_timer, relay_once, retry_failures, schedule_timer
from zoikorum.shared.state_machine import StateMachine


def test_money_rejects_floats_negatives_and_mixed_currency():
    with pytest.raises(ValidationFailed):
        Money(10.5, "USD")  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        Money(-1, "USD")
    with pytest.raises(ValidationFailed):
        Money(1, "USD") + Money(1, "EUR")
    assert Money(100_000, "USD").percentage_bps(1000) == Money(10_000, "USD")
    assert Money(5, "USD").percentage_bps(1000) == Money(1, "USD")  # half-up


def test_state_machine_blocks_invalid_transitions():
    sm = StateMachine("Proposal", {"DRAFT": ["SUBMITTED"], "SUBMITTED": ["ACCEPTED"], "ACCEPTED": []})
    sm.assert_can("DRAFT", "SUBMITTED")
    with pytest.raises(InvalidStateTransition):
        sm.assert_can("DRAFT", "ACCEPTED")
    assert sm.is_terminal("ACCEPTED")


def test_unknown_event_types_are_rejected():
    with pytest.raises(ValueError):
        record_event(None, "zoikorum.made.up.event.v1", aggregate_type="X", aggregate_id="1", payload={})  # type: ignore[arg-type]


async def test_outbox_delivers_once_per_consumer_even_if_relayed_twice(sf):
    seen: list[str] = []

    @registry.subscribe(E.TAXONOMY_UPDATED, consumer="test.kernel_once")
    async def _h(session, env):
        seen.append(str(env.eventId))

    async with sf() as s, s.begin():
        env = record_event(s, E.TAXONOMY_UPDATED, aggregate_type="Taxonomy", aggregate_id="t1", payload={"v": 1})
    assert await relay_once(sf) == 1
    # Simulate a crash after delivery but before marking published: replay the row.
    async with sf() as s, s.begin():
        row = await s.scalar(select(OutboxEvent).where(OutboxEvent.event_id == env.eventId))
        row.published_at = None
    await relay_once(sf)
    assert seen == [str(env.eventId)]
    async with sf() as s:
        assert await s.scalar(select(func.count()).select_from(InboxEntry).where(InboxEntry.consumer == "test.kernel_once")) == 1


async def test_failing_consumer_retries_then_dead_letters(sf):
    calls = {"n": 0}

    @registry.subscribe(E.LISTING_VIEWED, consumer="test.kernel_flaky")
    async def _h(session, env):
        calls["n"] += 1
        raise RuntimeError("downstream unavailable")

    async with sf() as s, s.begin():
        record_event(s, E.LISTING_VIEWED, aggregate_type="Listing", aggregate_id="p1", payload={})
    await relay_once(sf)
    for _ in range(10):
        clock.advance(timedelta(hours=1))
        await retry_failures(sf)
    async with sf() as s:
        f = await s.scalar(select(ConsumerFailure).where(ConsumerFailure.consumer == "test.kernel_flaky"))
    assert f.status == "DEAD"
    assert f.attempts == 5 and calls["n"] == 5


async def test_timers_fire_once_and_can_be_moved(sf):
    fired: list[str] = []

    @on_timer("test.kernel_timer")
    async def _h(session, key, payload):
        fired.append(key)

    t0 = clock.now()
    async with sf() as s, s.begin():
        await schedule_timer(s, "test.kernel_timer", "k1", t0 + timedelta(days=1))
        await schedule_timer(s, "test.kernel_timer", "k1", t0 + timedelta(days=2))  # moved, not duplicated
    assert await fire_due_timers(sf, now=t0 + timedelta(days=1, hours=1)) == 0
    assert await fire_due_timers(sf, now=t0 + timedelta(days=2, hours=1)) == 1
    assert await fire_due_timers(sf, now=t0 + timedelta(days=3)) == 0
    assert fired == ["k1"]
