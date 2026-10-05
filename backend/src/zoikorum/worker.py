"""Background worker: outbox relay, consumer retries, durable timers.

Run:  python -m zoikorum.worker
Scale horizontally - every loop uses SELECT ... FOR UPDATE SKIP LOCKED.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from zoikorum.main import load_domains
from zoikorum.shared import clock
from zoikorum.shared.db import session_factory
from zoikorum.shared.relay import fire_due_timers, relay_once, retry_failures, schedule_timer

log = logging.getLogger("zoikorum.worker")


async def _bootstrap_timers() -> None:
    sf = session_factory()
    async with sf() as s, s.begin():
        first = clock.now() + timedelta(hours=1)
        await schedule_timer(s, "audit.chain_validation", first.strftime("%Y%m%d%H"), first)


async def run(poll_seconds: float = 0.5) -> None:
    load_domains()
    await _bootstrap_timers()
    sf = session_factory()
    log.info("worker started")
    while True:
        try:
            n = await relay_once(sf)
            n += await fire_due_timers(sf)
            n += await retry_failures(sf)
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
            n = 0
        if n == 0:
            await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
