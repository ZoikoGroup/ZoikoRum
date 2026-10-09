"""Request budgets per caller, shared across API servers through Redis (shared/ratelimit.py)."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from zoikorum.config import Settings
from zoikorum.shared import http, ratelimit

REDIS_URL = os.environ.get("ZK_TEST_REDIS_URL", "redis://localhost:6380/15")


async def redis_or_skip():
    from redis.asyncio import Redis

    client = Redis.from_url(REDIS_URL, socket_timeout=0.5, socket_connect_timeout=0.5)
    try:
        await client.ping()
    except Exception:  # noqa: BLE001
        pytest.skip("Redis is not running (docker compose up -d redis)")
    return client


@pytest.mark.unit
async def test_memory_buckets_allow_the_burst_then_refuse():
    buckets = ratelimit.MemoryBuckets()
    assert [await buckets.take("k", 60, 3) for _ in range(4)] == [True, True, True, False]
    assert await buckets.take("other", 60, 3)  # each caller has its own budget


@pytest.mark.unit
def test_bucket_keys_never_contain_the_token():
    key = ratelimit.bucket_key("user", "Bearer eyJhbGciOi.secret-signature")
    assert key.startswith("zk:rl:user:") and "secret" not in key and "Bearer" not in key


async def test_two_servers_share_one_budget():
    await redis_or_skip()
    key = ratelimit.bucket_key("user", str(uuid.uuid4()))
    server_a = ratelimit.RedisBuckets(REDIS_URL, ratelimit.MemoryBuckets())
    server_b = ratelimit.RedisBuckets(REDIS_URL, ratelimit.MemoryBuckets())
    taken = [await (server_a if i % 2 else server_b).take(key, 60, 4) for i in range(6)]
    assert taken == [True, True, True, True, False, False]  # 4 in total, not 4 per server


async def test_redis_outage_falls_back_to_this_process_budget():
    class Down:
        def register_script(self, _):
            async def run(**_):
                raise ConnectionError("redis down")
            return run

    buckets = ratelimit.RedisBuckets(REDIS_URL, ratelimit.MemoryBuckets(), client=Down())
    assert [await buckets.take("k", 60, 2) for _ in range(3)] == [True, True, False]  # still limited, never down


async def test_middleware_refuses_over_the_budget(monkeypatch):
    monkeypatch.setattr(http, "get_settings", lambda: Settings(_env_file=None, rate_limit_enabled=True))
    monkeypatch.setattr(ratelimit, "get_buckets", lambda: shared)
    monkeypatch.setattr(http.RateLimitMiddleware, "LIMITS", {"anonymous": (60, 2), "user": (60, 3)})
    shared = ratelimit.MemoryBuckets()
    app = FastAPI()
    http.install(app)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        anonymous = [(await client.get("/ping")).status_code for _ in range(3)]
        signed_in = [(await client.get("/ping", headers={"Authorization": "Bearer a"})).status_code for _ in range(4)]
        other = (await client.get("/ping", headers={"Authorization": "Bearer b"})).status_code
    assert anonymous == [200, 200, 429] and signed_in == [200, 200, 200, 429] and other == 200
