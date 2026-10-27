"""Read cache (Architecture 7.x): hot, rarely changing reads served from Redis instead of the database.

Used for the capability taxonomy, trust tiers, policy profile reads and search facets. Every entry lives in a
*namespace* and is dropped by explicit invalidation when the data changes (the owning domain calls ``invalidate`` in
the same place it records the change), with ``ZK_CACHE_TTL_SECONDS`` as a backstop.

* Invalidation bumps the namespace's generation number, which is part of every key; old entries are never read again
  and expire on their own. One INCR, however many keys the namespace holds.
* With ``ZK_REDIS_URL`` all API processes and workers share the cache. Without it (development) each process has its
  own small in-memory cache. If Redis fails, the read goes to the database (the loader) and a warning is logged at most
  once a minute: a cache outage slows the API down, it never breaks it. Invalidation while Redis is down is applied
  locally, and the TTL bounds how stale another process can be.
* Values are JSON. Never cache personal data or anything whose visibility depends on who asks.
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from functools import lru_cache
from typing import Any, Awaitable, Callable

log = logging.getLogger("zoikorum.cache")
PREFIX = "zk:c:"
MEMORY_ENTRIES = 2000


class MemoryCache:
    """One process's cache (development, tests, or the fallback while Redis is down). Least recently used goes first."""

    def __init__(self, max_entries: int = MEMORY_ENTRIES):
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._generations: dict[str, int] = {}
        self._max = max_entries

    async def get(self, key: str) -> str | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        if hit[0] < time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return hit[1]

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = (time.monotonic() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    async def get_many(self, keys: list[str]) -> list[str | None]:
        return [await self.get(k) for k in keys]

    async def generation(self, namespace: str) -> int:
        return self._generations.get(namespace, 0)

    async def bump(self, namespace: str) -> None:
        self._generations[namespace] = self._generations.get(namespace, 0) + 1

    def clear(self) -> None:
        self._data.clear()
        self._generations.clear()


class RedisCache:
    def __init__(self, url: str, fallback: MemoryCache, client=None):
        if client is None:
            from redis.asyncio import Redis

            client = Redis.from_url(url, socket_timeout=0.25, socket_connect_timeout=0.25)
        self._redis, self._fallback, self._warned_at = client, fallback, 0.0

    def _warn(self, exc: Exception) -> None:
        if time.monotonic() - self._warned_at > 60:
            self._warned_at = time.monotonic()
            log.warning("read cache unavailable, reading from the database", extra={"fields": {"error": type(exc).__name__}})

    async def get(self, key: str) -> str | None:
        try:
            value = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001 - any Redis failure: the caller loads from the database
            self._warn(exc)
            return None
        return value.decode() if isinstance(value, bytes) else value

    async def get_many(self, keys: list[str]) -> list[str | None]:
        try:
            values = await self._redis.mget(keys)
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)
            return [None] * len(keys)
        return [v.decode() if isinstance(v, bytes) else v for v in values]

    async def set(self, key: str, value: str, ttl: int) -> None:
        try:
            await self._redis.set(key, value, ex=ttl)
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)

    async def generation(self, namespace: str) -> int:
        try:
            value = await self._redis.get(f"{PREFIX}gen:{namespace}")
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)
            return -1  # "unknown": the caller skips the cache entirely
        return int(value or 0)

    async def bump(self, namespace: str) -> None:
        await self._fallback.bump(namespace)
        try:
            await self._redis.incr(f"{PREFIX}gen:{namespace}")
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)


@lru_cache
def get_cache() -> MemoryCache | RedisCache:
    from zoikorum.config import get_settings

    memory = MemoryCache()
    url = get_settings().redis_url
    return RedisCache(url, memory) if url else memory


def _enabled() -> bool:
    from zoikorum.config import get_settings

    return get_settings().cache_enabled


async def cached(namespace: str, key: str, loader: Callable[[], Awaitable[Any]], ttl: int | None = None) -> Any:
    """The cached JSON value of ``namespace``/``key``, or ``loader()``'s result (then stored). The loader's value must be
    JSON-serialisable (dates become strings: cache what the API returns, not ORM objects)."""
    from zoikorum.config import get_settings

    if not _enabled():
        return await loader()
    cache = get_cache()
    generation = await cache.generation(namespace)
    if generation < 0:
        return await loader()
    full = f"{PREFIX}{namespace}:{generation}:{key}"
    hit = await cache.get(full)
    if hit is not None:
        try:
            return json.loads(hit)
        except ValueError:
            pass
    value = _encode(await loader())
    await cache.set(full, json.dumps(value, separators=(",", ":")), ttl or get_settings().cache_ttl_seconds)
    return value


def _encode(value: Any) -> Any:
    """The JSON form FastAPI would send (ids and times as strings), so a cache hit and a miss answer identically."""
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)


async def cached_many(namespace: str, keys: list[str], loader: Callable[[list[str]], Awaitable[dict[str, Any]]],
                      ttl: int | None = None) -> dict[str, Any]:
    """Per-key cache for batch reads: one round trip for the hits, ``loader(missing keys)`` for the rest."""
    from zoikorum.config import get_settings

    if not keys:
        return {}
    if not _enabled():
        return _encode(await loader(keys))
    cache = get_cache()
    generation = await cache.generation(namespace)
    if generation < 0:
        return _encode(await loader(keys))
    full = {k: f"{PREFIX}{namespace}:{generation}:{k}" for k in keys}
    out: dict[str, Any] = {}
    for k, hit in zip(keys, await cache.get_many([full[k] for k in keys])):
        if hit is not None:
            try:
                out[k] = json.loads(hit)
            except ValueError:
                pass
    missing = [k for k in keys if k not in out]
    if missing:
        loaded = _encode(await loader(missing))
        for k, v in loaded.items():
            out[k] = v
            await cache.set(full[k], json.dumps(v, separators=(",", ":")), ttl or get_settings().cache_ttl_seconds)
    return out


async def invalidate(*namespaces: str) -> None:
    """Drop every entry of these namespaces (call it where the data changes)."""
    cache = get_cache()
    for namespace in namespaces:
        await cache.bump(namespace)


# Namespaces in use (one place, so writers and readers agree).
TAXONOMY = "taxonomy"
TRUST_TIERS = "trust-tiers"
POLICY_PROFILES = "policy-profiles"
SEARCH_FACETS = "search-facets"


# ---- Invalidation on events (after the change has committed; writers also invalidate at once, in their own process) ---

def _register_invalidation() -> None:
    from zoikorum.shared.event_catalog import E
    from zoikorum.shared.events import subscribe

    rules = {
        TAXONOMY: (E.TAXONOMY_UPDATED, E.TAXONOMY_SUGGESTION_RESOLVED),
        TRUST_TIERS: (E.TRUST_SCORE_RECOMPUTED, E.TRUST_TIER_CHANGED, E.TRUST_SIGNAL_ADDED, E.TRUST_SIGNAL_REVOKED,
                      E.TRUST_PROFILE_FLAGGED),
        POLICY_PROFILES: (E.POLICY_CREATED, E.POLICY_DRAFT_UPDATED, E.POLICY_VERSION_ACTIVATED),
        SEARCH_FACETS: (E.PROFILE_PUBLISHED, E.PROFILE_UNPUBLISHED, E.PROFILE_SUSPENDED, E.PROFILE_REINSTATED, E.PROFILE_UPDATED,
                        E.TRUST_TIER_CHANGED, E.TAXONOMY_UPDATED),
    }
    for namespace, events in rules.items():
        for event_type in events:
            async def _drop(session, event, _ns=namespace):  # noqa: ARG001 - the event only says "it changed"
                await invalidate(_ns)

            subscribe(event_type, consumer=f"platform.cache_invalidate.{namespace}")(_drop)


_register_invalidation()
