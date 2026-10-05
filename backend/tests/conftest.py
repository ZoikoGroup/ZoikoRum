"""Test harness: a real Postgres database, every domain schema, append-only
triggers, and helpers for users and event draining.

Set ZK_TEST_DATABASE (default zoikorum_test) to isolate parallel test runs.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import tempfile
import uuid
from datetime import datetime, timezone

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

os.environ.setdefault("ZK_ENV", "test")
os.environ.setdefault("ZK_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("ZK_STORAGE_DIR", tempfile.mkdtemp(prefix="zk-storage-"))  # uploads never touch the repo

ADMIN_URL = os.environ.get("ZK_TEST_ADMIN_URL", "postgresql+asyncpg://zoikorum:zoikorum@localhost:5434/zoikorum")
TEST_DB = os.environ.get("ZK_TEST_DATABASE", "zoikorum_test")
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
os.environ["ZK_DATABASE_URL"] = TEST_URL

from zoikorum.main import create_app, load_domains  # noqa: E402
from zoikorum.shared import clock, ddl  # noqa: E402
from zoikorum.shared.db import DOMAIN_SCHEMAS, Base, configure_engine, session_factory  # noqa: E402
from zoikorum.shared.relay import drain as _drain  # noqa: E402

LOADED_DOMAINS: list[str] = []


@pytest.fixture(scope="session")
async def engine():
    admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB})
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin.dispose()

    eng = create_async_engine(TEST_URL, pool_size=20)
    global LOADED_DOMAINS
    LOADED_DOMAINS = load_domains()
    async with eng.begin() as conn:
        for schema in DOMAIN_SCHEMAS:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        for schema in DOMAIN_SCHEMAS:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.run_sync(Base.metadata.create_all)
        tables = {f"{t.schema}.{t.name}" for t in Base.metadata.sorted_tables}
        for stmt in ddl.all_statements(tables):
            await conn.execute(text(stmt))
    configure_engine(eng)
    yield eng
    await eng.dispose()


@pytest.fixture(autouse=True)
async def clean_db(engine):
    clock.set_now(None)
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' AND table_schema = ANY(:s)"), {"s": list(DOMAIN_SCHEMAS)})
        tables = ", ".join(f'"{a}"."{b}"' for a, b in rows.all())
    async with engine.begin() as conn:
        await conn.execute(text("SET session_replication_role = replica"))  # bypass append-only triggers
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await conn.execute(text("SET session_replication_role = DEFAULT"))
    # Reference data (e.g. the capability taxonomy) that migrations load in real databases.
    async with session_factory()() as s, s.begin():
        for d in LOADED_DOMAINS:
            if importlib.util.find_spec(f"zoikorum.domains.{d}.seed"):
                await importlib.import_module(f"zoikorum.domains.{d}.seed").seed(s)
    yield
    clock.set_now(None)


@pytest.fixture(scope="session")
def app(engine):
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def sf(engine):
    return session_factory()


@pytest.fixture
def drain(sf):
    async def _run():
        return await _drain(sf)

    return _run


class User:
    def __init__(self, client: AsyncClient, data: dict, email: str, password: str):
        self.client = client
        self.id = uuid.UUID(data["user"]["id"])
        self.user = data["user"]
        self.email = email
        self.password = password
        self.access = data["tokens"]["accessToken"]
        self.refresh_token = data["tokens"]["refreshToken"]
        self.confirm_token = data.get("emailConfirmationToken")
        self.totp_secret: str | None = None

    @property
    def h(self) -> dict:
        return {"Authorization": f"Bearer {self.access}"}

    def idem(self, key: str | None = None) -> dict:
        return {**self.h, "Idempotency-Key": key or str(uuid.uuid4())}

    async def refresh(self) -> None:
        """Pick up new token claims (org/professional links) after events drained."""
        r = await self.client.post("/v1/auth/refresh", json={"refreshToken": self.refresh_token})
        assert r.status_code == 200, r.text
        self.access, self.refresh_token = r.json()["accessToken"], r.json()["refreshToken"]

    async def enable_mfa(self) -> None:
        r = await self.client.post("/v1/auth/mfa/enroll", headers=self.h)
        assert r.status_code == 200, r.text
        self.totp_secret = r.json()["secret"]
        r = await self.client.post("/v1/auth/mfa/verify", headers=self.h, json={"totpCode": self.totp()})
        assert r.status_code == 204, r.text

    def totp(self) -> str:
        assert self.totp_secret
        return pyotp.TOTP(self.totp_secret).at(clock.now())

    async def step_up(self) -> None:
        if not self.totp_secret:
            await self.enable_mfa()
        r = await self.client.post("/v1/auth/step-up", headers=self.h, json={"totpCode": self.totp()})
        assert r.status_code == 200, r.text
        self.access, self.refresh_token = r.json()["accessToken"], r.json()["refreshToken"]


@pytest.fixture
def make_user(client, sf):
    async def _make(
        name: str = "user", *, platform_roles: tuple[str, ...] = (), country: str = "US",
        account_type: str = "BUYER", organization: str | None = None,
    ) -> User:
        email = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
        password = "correct-horse-battery-staple"
        r = await client.post(
            "/v1/auth/register",
            json={"email": email, "password": password, "displayName": name.title(), "country": country,
                  "accountType": account_type, "organizationName": organization, "acceptTerms": True},
        )
        assert r.status_code == 201, r.text
        user = User(client, r.json(), email, password)
        if platform_roles:
            # Bootstrap operator roles directly (the API requires an existing admin).
            async with sf() as s, s.begin():
                await s.execute(
                    text("UPDATE identity.identities SET platform_roles = :r WHERE id = :i"),
                    {"r": list(platform_roles), "i": user.id},
                )
            await user.refresh()
        return user

    return _make


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)
