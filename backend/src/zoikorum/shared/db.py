"""Database plumbing: one Postgres schema per bounded context (ADR-001).

Rules (enforced by tests/test_architecture.py and code review):
  * A domain's tables live in its own schema, e.g. ``proposal.proposals``.
  * Only the owning domain writes to its schema. No cross-schema joins or FKs.
  * Every table has a UUID PK, created_at, and updated_at where mutable.
  * State-machine aggregates carry a ``version`` column for optimistic locking.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends
from sqlalchemy import BigInteger, DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from zoikorum.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Every bounded context gets its own schema. Add new domains here.
DOMAIN_SCHEMAS = (
    "platform",  # outbox / inbox / idempotency / timers - infrastructure only
    "identity",
    "buyer",
    "firm",
    "professional",
    "marketplace",
    "search",
    "proposal",
    "contract",
    "escrow",
    "payments",
    "verification",
    "trust",
    "policy",
    "dispute",
    "audit",
    "messaging",
    "notification",
    "ai",
    "admin",
    "analytics",
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=utcnow
    )


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=utcnow, onupdate=utcnow
    )


class Versioned:
    """Optimistic concurrency (Handbook 18.4).

    SQLAlchemy bumps ``version`` on every UPDATE and raises StaleDataError on a
    lost update; the API layer maps that to 409 VERSION_CONFLICT. Expose
    ``version`` as the resource ETag and honour ``If-Match`` where multiple
    actors edit the same aggregate.
    """

    version: Mapped[int] = mapped_column(BigInteger, nullable=False)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict:
        return {"version_id_col": cls.__table__.c.version}


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(s.database_url, pool_size=s.db_pool_size, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=True)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def configure_engine(engine: AsyncEngine) -> None:
    """Used by tests to point the app at a dedicated test database."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=True)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def _transactional_session() -> AsyncIterator[AsyncSession]:
    """One request = one transaction. Commits before the response is sent."""
    async with session_factory()() as session:
        async with session.begin():
            yield session


# scope="function" -> commit happens BEFORE the HTTP response is returned, so a
# client never sees 2xx for a write that later failed to commit.
DbSession = Annotated[AsyncSession, Depends(_transactional_session, scope="function")]
