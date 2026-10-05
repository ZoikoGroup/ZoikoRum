"""Alembic environment: one migration chain covering every domain schema.

Usage (from backend/):
    alembic upgrade head
    alembic revision --autogenerate -m "describe change"
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from zoikorum.config import get_settings
from zoikorum.main import load_domains
from zoikorum.shared.db import DOMAIN_SCHEMAS, Base

load_domains()
config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in DOMAIN_SCHEMAS
    return True


def _configure(connection=None, **kw):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        version_table_schema="platform",
        compare_type=True,
        **kw,
    )


def run_offline() -> None:
    _configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection) -> None:
    connection.execute(text('CREATE SCHEMA IF NOT EXISTS "platform"'))
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = async_engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(_run_sync)
        await conn.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
