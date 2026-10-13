"""Daily clean-up of the platform's own bookkeeping rows, so these tables stay small and fast.

Removed after ZK_IDEMPOTENCY_RETENTION_DAYS (default 30): replayed-request records (platform.idempotency_keys); clients
retry within minutes, not weeks.

Removed after ZK_EVENT_RETENTION_DAYS (default 30, at least 7):
* events already handed to every consumer (platform.outbox rows with published_at);
* the matching "already handled" markers (platform.inbox): an event older than this is never delivered again;
* deliveries that failed and later succeeded (platform.consumer_failures RESOLVED). Dead letters stay until an
  operator deals with them.

Never touched: business records, the audit trail, the money ledger, timers (a timer key must stay unique for good).
Deletes run in batches, so a large backlog is worked off over several days without long locks.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.shared import clock
from zoikorum.shared.platform_models import ConsumerFailure, IdempotencyRecord, InboxEntry, OutboxEvent
from zoikorum.shared.relay import on_timer, schedule_timer

log = logging.getLogger("zoikorum.housekeeping")
TIMER = "platform.housekeeping"
BATCH = 5000
MAX_BATCHES = 20  # per table per day


def next_run(now: datetime) -> datetime:
    """Daily at 02:30 UTC (after the 01:00 reconciliation)."""
    today = datetime.combine(now.date(), time(2, 30), tzinfo=timezone.utc)
    return today if now < today else today + timedelta(days=1)


async def bootstrap(session: AsyncSession) -> None:
    nxt = next_run(clock.now())
    await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)


async def _purge(session: AsyncSession, key, where) -> int:
    removed = 0
    for _ in range(MAX_BATCHES):
        ids = select(key).where(where).limit(BATCH).scalar_subquery()
        n = (await session.execute(delete(key.class_).where(key.in_(ids)))).rowcount or 0
        removed += n
        if n < BATCH:
            break
    return removed


async def clean_up(session: AsyncSession) -> dict[str, int]:
    s = get_settings()
    now = clock.now()
    requests_before = now - timedelta(days=s.idempotency_retention_days)
    events_before = now - timedelta(days=s.event_retention_days)
    removed = {
        "idempotencyKeys": await _purge(session, IdempotencyRecord.scope, IdempotencyRecord.created_at < requests_before),
        "publishedEvents": await _purge(session, OutboxEvent.seq, OutboxEvent.published_at < events_before),
        "handledMarkers": await _purge(session, InboxEntry.id, InboxEntry.created_at < events_before),
        "resolvedFailures": await _purge(session, ConsumerFailure.id, (ConsumerFailure.status == "RESOLVED")
                                         & (ConsumerFailure.created_at < events_before)),
    }
    log.info("housekeeping removed %s", removed)
    return removed


@on_timer(TIMER)
async def _daily(session: AsyncSession, key: str, payload: dict) -> None:
    await clean_up(session)
    nxt = next_run(clock.now())
    await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)  # re-arms itself
