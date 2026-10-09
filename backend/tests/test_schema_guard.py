"""Prevent schema drift from becoming per-page HTTP 500 errors."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import ProgrammingError

from zoikorum.main import load_domains
from zoikorum.shared import schema_guard
from zoikorum.shared.http import install


def test_guard_includes_messaging_and_merged_profile_columns():
    load_domains()
    missing = schema_guard.missing_columns(set())
    assert "professional.professionals.weekly_hours" in missing
    assert "messaging.threads.id" in missing
    (head,) = schema_guard.expected_heads()  # one migration head, which includes the dev + messaging merge
    script = ScriptDirectory(str(Path(schema_guard.__file__).resolve().parents[3] / "alembic"))
    assert "f1360ce42a96" in {r.revision for r in script.iterate_revisions(head, "base")}


@pytest.mark.unit
@pytest.mark.parametrize("current", [set(), {"e0259bc31d85"}])
async def test_outdated_database_cannot_start(monkeypatch, current):
    connection = AsyncMock()
    connection.scalar.return_value = bool(current)
    connection.execute.return_value = SimpleNamespace(scalars=lambda: current)
    scope = AsyncMock()
    scope.__aenter__.return_value = connection
    monkeypatch.setattr(schema_guard, "get_engine", lambda: SimpleNamespace(connect=lambda: scope))
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        await schema_guard.ensure_schema_current()


@pytest.mark.unit
@pytest.mark.parametrize("missing", [[], ["messaging.threads.id"]])
async def test_migration_marker_alone_is_not_enough(monkeypatch, missing):
    connection = AsyncMock()
    connection.scalar.return_value = True
    connection.execute.side_effect = [SimpleNamespace(scalars=lambda: schema_guard.expected_heads()), SimpleNamespace(all=lambda: [])]
    scope = AsyncMock()
    scope.__aenter__.return_value = connection
    monkeypatch.setattr(schema_guard, "get_engine", lambda: SimpleNamespace(connect=lambda: scope))
    monkeypatch.setattr(schema_guard, "missing_columns", lambda rows: missing)
    if missing:
        with pytest.raises(RuntimeError, match="messaging.threads.id"):
            await schema_guard.ensure_schema_current()
    else:
        await schema_guard.ensure_schema_current()


@pytest.mark.unit
@pytest.mark.parametrize("sqlstate", ["42P01", "42703"])
async def test_schema_errors_are_safe_structured_responses(sqlstate):
    app = FastAPI()
    install(app)
    @app.get("/broken")
    async def broken():
        original = Exception("sensitive query or customer data")
        original.sqlstate = sqlstate
        raise ProgrammingError("private SQL", {}, original)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/broken")
    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_SCHEMA_OUTDATED"
    assert response.json()["correlationId"]
    assert "sensitive" not in response.text and "private SQL" not in response.text


@pytest.mark.unit
async def test_api_startup_runs_guard_before_serving(monkeypatch):
    from zoikorum import main
    guard = AsyncMock(side_effect=RuntimeError("Database migrations are not current"))
    monkeypatch.setattr(schema_guard, "ensure_schema_current", guard)
    monkeypatch.setattr(main, "dispose_engine", AsyncMock())
    app = main.create_app()
    with pytest.raises(RuntimeError, match="migrations are not current"):
        async with app.router.lifespan_context(app):
            pytest.fail("API started with an outdated database")
    guard.assert_awaited_once()


@pytest.mark.unit
async def test_worker_checks_schema_before_bootstrapping_timers(monkeypatch):
    from zoikorum import worker
    guard = AsyncMock(side_effect=RuntimeError("Database migrations are not current"))
    bootstrap = AsyncMock()
    monkeypatch.setattr(schema_guard, "ensure_schema_current", guard)
    monkeypatch.setattr(worker, "_bootstrap_timers", bootstrap)
    with pytest.raises(RuntimeError, match="migrations are not current"):
        await worker.run()
    guard.assert_awaited_once()
    bootstrap.assert_not_awaited()
