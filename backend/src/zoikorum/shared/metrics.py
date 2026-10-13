"""Metrics in Prometheus format (Engineering Handbook 24.1 SLIs, 28 "logs, metrics, traces exist").

Served at GET /metrics, only with ``Authorization: Bearer <ZK_METRICS_TOKEN>`` (no token configured: 404).

* Request latency per route template (never raw paths, which would carry ids): the search and proposal SLOs.
* Calls to the built-in AI prompts, by outcome.
* Read from the database on each scrape, so every API process reports the same values: how far behind the worker is
  (unpublished events, overdue timers), consumer retries and dead letters, plus what domains register (e.g. the latest
  reconciliation result).
* Circuit breaker states of this process.

With several web processes per container (uvicorn --workers), set PROMETHEUS_MULTIPROC_DIR to an empty directory so the
counters of all processes are added up (the Dockerfile does).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from datetime import datetime

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.shared import clock
from zoikorum.shared.platform_models import ConsumerFailure, OutboxEvent, Timer

REQUEST_SECONDS = Histogram(
    "zk_http_request_duration_seconds", "API request duration by route template and status class",
    ["method", "route", "status"], buckets=(0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5, 10))
AI_CALLS = Counter("zk_ai_calls_total", "Calls to the built-in AI prompts by outcome", ["prompt", "outcome"])

# (name, help, value) gauges a domain contributes, read on each scrape: async fn(session) -> list[tuple[str, str, float]]
GaugeSource = Callable[[AsyncSession], Awaitable[list[tuple[str, str, float]]]]
_sources: list[GaugeSource] = []


def gauge_source(fn: GaugeSource) -> GaugeSource:
    """Decorator for a domain's scrape-time gauges (domains register; the shared kernel never imports them)."""
    _sources.append(fn)
    return fn


def observe_request(method: str, route: str | None, status: int, seconds: float) -> None:
    REQUEST_SECONDS.labels(method, route or "unmatched", f"{status // 100}xx").observe(seconds)


def _age(since: datetime | None) -> float:
    return max(0.0, (clock.now() - since).total_seconds()) if since else 0.0


async def worker_backlog(session: AsyncSession) -> dict:
    """How far behind the background worker is. A growing ``oldestUnpublishedSeconds`` means events (and so emails,
    payments follow-ups, search updates) are waiting: the worker is down or too slow."""
    now = clock.now()
    unpublished, oldest = (await session.execute(
        select(func.count(), func.min(OutboxEvent.created_at)).where(OutboxEvent.published_at.is_(None)))).one()
    overdue, oldest_due = (await session.execute(
        select(func.count(), func.min(Timer.fire_at)).where(Timer.fired_at.is_(None), Timer.cancelled_at.is_(None),
                                                           Timer.fire_at <= now))).one()
    failures = dict((await session.execute(
        select(ConsumerFailure.status, func.count()).where(ConsumerFailure.status.in_(("RETRYING", "DEAD")))
        .group_by(ConsumerFailure.status))).all())
    dead_financial = await session.scalar(select(func.count()).select_from(ConsumerFailure).where(
        ConsumerFailure.status == "DEAD", ConsumerFailure.financial.is_(True))) or 0
    return {"unpublishedEvents": unpublished, "oldestUnpublishedSeconds": round(_age(oldest), 1),
            "overdueTimers": overdue, "oldestOverdueTimerSeconds": round(_age(oldest_due), 1),
            "retryingDeliveries": failures.get("RETRYING", 0), "deadLetters": failures.get("DEAD", 0),
            "deadFinancialLetters": dead_financial}


class _ScrapeGauges:
    """A collector holding the values read for one scrape."""

    def __init__(self, gauges: list[GaugeMetricFamily]):
        self.gauges = gauges

    def collect(self):
        yield from self.gauges


def _gauge(name: str, help_text: str, value: float, labels: dict[str, str] | None = None) -> GaugeMetricFamily:
    g = GaugeMetricFamily(name, help_text, labels=list(labels or {}))
    g.add_metric(list((labels or {}).values()), value)
    return g


async def render(session: AsyncSession) -> tuple[bytes, str]:
    from zoikorum.shared.circuit import all_breakers

    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        process = CollectorRegistry()
        multiprocess.MultiProcessCollector(process)
        body = generate_latest(process)
    else:
        from prometheus_client import REGISTRY

        body = generate_latest(REGISTRY)

    b = await worker_backlog(session)
    gauges = [
        _gauge("zk_outbox_unpublished_events", "Events not yet handed to their consumers", b["unpublishedEvents"]),
        _gauge("zk_outbox_oldest_unpublished_seconds", "Age of the oldest event waiting for the worker",
               b["oldestUnpublishedSeconds"]),
        _gauge("zk_timers_overdue", "Timers (deadlines, reminders) past due and not yet fired", b["overdueTimers"]),
        _gauge("zk_timers_oldest_overdue_seconds", "How long the most overdue timer has waited", b["oldestOverdueTimerSeconds"]),
        _gauge("zk_consumer_deliveries_retrying", "Event deliveries waiting for a retry", b["retryingDeliveries"]),
        _gauge("zk_consumer_dead_letters", "Event deliveries that need an operator", b["deadLetters"]),
        _gauge("zk_consumer_dead_letters_financial", "Dead letters about money (need Financial Operations)",
               b["deadFinancialLetters"]),
    ]
    state = GaugeMetricFamily("zk_circuit_open", "1 while a partner's circuit breaker is open in this process", labels=["breaker"])
    for breaker in all_breakers():
        state.add_metric([breaker.name], 1.0 if breaker.state == "OPEN" else 0.0)
    gauges.append(state)
    for source in _sources:
        for name, help_text, value in await source(session):
            gauges.append(_gauge(name, help_text, value))
    scrape = CollectorRegistry()
    scrape.register(_ScrapeGauges(gauges))
    return body + generate_latest(scrape), CONTENT_TYPE_LATEST
