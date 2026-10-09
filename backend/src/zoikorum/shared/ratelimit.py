"""Request budgets per caller (Architecture 7.4): a token bucket per signed-in session or per client address.

With ``ZK_REDIS_URL`` every API process and server shares one bucket per caller; the take is one atomic Redis script,
so two servers can never both spend the last token. Without it (local development) each process keeps its own buckets.
If Redis is unavailable the request is not refused for that reason: this process's own buckets apply instead and a
warning is logged (at most once a minute), so a cache outage never takes the API down.
Bucket keys are one-way hashes: no token or address is stored as such.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from functools import lru_cache
from typing import Protocol

log = logging.getLogger("zoikorum.ratelimit")

# Atomic token bucket. KEYS[1] bucket; ARGV: tokens per second, burst. Uses the Redis server clock.
_TAKE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local rate, burst = tonumber(ARGV[1]), tonumber(ARGV[2])
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens, ts = tonumber(data[1]), tonumber(data[2])
if tokens == nil then tokens, ts = burst, now end
tokens = math.min(burst, tokens + (now - ts) * rate)
local allowed = 0
if tokens >= 1 then tokens = tokens - 1; allowed = 1 end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], math.ceil(burst / rate) + 1)
return allowed
"""


def bucket_key(kind: str, identifier: str) -> str:
    return f"zk:rl:{kind}:{hashlib.sha256(identifier.encode()).hexdigest()[:32]}"


class Buckets(Protocol):
    async def take(self, key: str, rate_per_min: float, burst: int) -> bool: ...


class MemoryBuckets:
    """One process's buckets (development, or the fallback while Redis is unavailable)."""

    def __init__(self):
        self._buckets: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])

    async def take(self, key: str, rate_per_min: float, burst: int) -> bool:
        tokens, last = self._buckets[key]
        now = time.monotonic()
        tokens = burst if last == 0 else min(burst, tokens + (now - last) * rate_per_min / 60)
        allowed = tokens >= 1
        self._buckets[key] = [tokens - 1 if allowed else tokens, now]
        return allowed


class RedisBuckets:
    def __init__(self, url: str, fallback: MemoryBuckets, client=None):
        if client is None:
            from redis.asyncio import Redis

            client = Redis.from_url(url, socket_timeout=0.25, socket_connect_timeout=0.25)
        self._redis, self._fallback, self._warned_at = client, fallback, 0.0
        self._script = self._redis.register_script(_TAKE)

    async def take(self, key: str, rate_per_min: float, burst: int) -> bool:
        try:
            return bool(await self._script(keys=[key], args=[rate_per_min / 60, burst]))
        except Exception as exc:  # noqa: BLE001 - any Redis failure: keep serving with this process's budget
            if time.monotonic() - self._warned_at > 60:
                self._warned_at = time.monotonic()
                log.warning("shared rate limits unavailable, using this process's own", extra={"fields": {"error": type(exc).__name__}})
            return await self._fallback.take(key, rate_per_min, burst)


@lru_cache
def get_buckets() -> Buckets:
    from zoikorum.config import get_settings

    memory = MemoryBuckets()
    url = get_settings().redis_url
    return RedisBuckets(url, memory) if url else memory
