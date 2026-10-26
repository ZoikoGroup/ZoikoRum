"""Read cache (shared/cache.py): hits, namespace invalidation, batch reads, and a safe fall-back to the database when
Redis fails; the taxonomy and trust tier reads use it and are dropped when the data changes."""

from __future__ import annotations

import pytest

from zoikorum.shared import cache


class DownRedis:
    async def get(self, *_):
        raise ConnectionError("down")

    async def mget(self, *_):
        raise ConnectionError("down")

    async def set(self, *_, **__):
        raise ConnectionError("down")

    async def incr(self, *_):
        raise ConnectionError("down")


class DictRedis:
    def __init__(self):
        self.data = {}

    async def get(self, k):
        return self.data.get(k)

    async def mget(self, keys):
        return [self.data.get(k) for k in keys]

    async def set(self, k, v, ex=None):
        self.data[k] = v.encode()

    async def incr(self, k):
        self.data[k] = str(int(self.data.get(k, b"0")) + 1).encode()


@pytest.fixture
def fresh(monkeypatch):
    memory = cache.MemoryCache()
    monkeypatch.setattr(cache, "get_cache", lambda: memory)
    return memory


@pytest.mark.unit
async def test_cached_until_invalidated(fresh):
    loads = []

    async def loader():
        loads.append(1)
        return {"n": len(loads)}

    assert await cache.cached("ns", "k", loader) == {"n": 1}
    assert await cache.cached("ns", "k", loader) == {"n": 1}
    await cache.invalidate("ns")
    assert await cache.cached("ns", "k", loader) == {"n": 2}
    assert await cache.cached("other", "k", loader) == {"n": 3}


@pytest.mark.unit
async def test_cached_many_loads_only_misses(fresh):
    asked = []

    async def loader(keys):
        asked.append(sorted(keys))
        return {k: k.upper() for k in keys}

    assert await cache.cached_many("ns", ["a", "b"], loader) == {"a": "A", "b": "B"}
    assert await cache.cached_many("ns", ["a", "c"], loader) == {"a": "A", "c": "C"}
    assert asked == [["a", "b"], ["c"]]


@pytest.mark.unit
async def test_redis_shared_and_failure_falls_back_to_the_loader(monkeypatch):
    shared = DictRedis()
    a, b = cache.RedisCache("redis://x", cache.MemoryCache(), client=shared), cache.RedisCache("redis://x", cache.MemoryCache(), client=shared)
    calls = []

    async def loader():
        calls.append(1)
        return [len(calls)]

    monkeypatch.setattr(cache, "get_cache", lambda: a)
    assert await cache.cached("ns", "k", loader) == [1]
    monkeypatch.setattr(cache, "get_cache", lambda: b)
    assert await cache.cached("ns", "k", loader) == [1]  # another server's entry
    await cache.invalidate("ns")
    assert await cache.cached("ns", "k", loader) == [2]

    down = cache.RedisCache("redis://x", cache.MemoryCache(), client=DownRedis())
    monkeypatch.setattr(cache, "get_cache", lambda: down)
    assert await cache.cached("ns", "k", loader) == [3]  # no error: the database answers
    assert await cache.cached_many("ns", ["x"], lambda keys: _dict(keys)) == {"x": 1}
    await cache.invalidate("ns")  # never raises


async def _dict(keys):
    return {k: 1 for k in keys}


@pytest.mark.unit
async def test_disabled_cache_always_loads(fresh, monkeypatch):
    from zoikorum.config import get_settings

    monkeypatch.setattr(get_settings(), "cache_enabled", False)
    n = []

    async def loader():
        n.append(1)
        return len(n)

    assert await cache.cached("ns", "k", loader) == 1 and await cache.cached("ns", "k", loader) == 2


async def test_taxonomy_is_cached_and_dropped_on_change(client, sf):
    from sqlalchemy import update

    from zoikorum.domains.marketplace.models import TaxonomyNode

    first = (await client.get("/v1/taxonomy")).json()
    async with sf() as s, s.begin():  # a change behind the API's back is not seen while cached ...
        await s.execute(update(TaxonomyNode).where(TaxonomyNode.level == "CATEGORY").values(name="Renamed"))
    assert (await client.get("/v1/taxonomy")).json() == first
    await cache.invalidate(cache.TAXONOMY)  # ... and is once the change is announced (TAXONOMY_UPDATED does this)
    assert {c["name"] for c in (await client.get("/v1/taxonomy")).json()["categories"]} == {"Renamed"}


async def test_trust_tier_reads_are_cached_per_professional(sf):
    import uuid

    from zoikorum.domains.trust import facade

    pid = uuid.uuid4()
    async with sf() as s:
        assert (await facade.tiers_and_dimensions(s, [pid]))[pid][0] == "C"
        assert (await facade.tiers_and_dimensions(s, [pid, pid]))[pid][1]["identity"] == "NONE"
