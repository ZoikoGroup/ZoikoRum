"""Structured logs with correlation ids, optional error reporting, and the readiness check."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from zoikorum.shared import context, observability, schema_guard


def record(msg="request", **fields) -> logging.LogRecord:
    r = logging.LogRecord("zoikorum.http", logging.INFO, __file__, 1, msg, None, None)
    r.fields = fields
    return r


@pytest.mark.unit
def test_json_lines_carry_fields_and_the_correlation_id():
    with context.use_context(context.ExecutionContext(correlation_id="cid-123", actor_type="anonymous")):
        line = json.loads(observability.JsonFormatter().format(record(method="GET", status=200)))
    assert line["msg"] == "request" and line["level"] == "INFO" and line["logger"] == "zoikorum.http"
    assert line["correlationId"] == "cid-123" and line["method"] == "GET" and line["status"] == 200 and line["ts"]


@pytest.mark.unit
def test_text_lines_are_readable():
    line = observability.TextFormatter().format(record(route="/v1/me", ms=4.2))
    assert "INFO" in line and "request" in line and "route=/v1/me" in line and "ms=4.2" in line


@pytest.mark.unit
def test_error_reporting_is_off_without_a_dsn():
    assert observability.init_error_reporting(None, "production", "api@1") is False


def readiness_engine(monkeypatch, current: set[str] | Exception):
    connection = AsyncMock()
    if isinstance(current, Exception):
        connection.scalar.side_effect = current
    else:
        connection.scalar.return_value = bool(current)
        connection.execute.return_value = SimpleNamespace(scalars=lambda: current)
    scope = AsyncMock()
    scope.__aenter__.return_value = connection
    monkeypatch.setattr(schema_guard, "get_engine", lambda: SimpleNamespace(connect=lambda: scope))


@pytest.mark.unit
async def test_ready_only_when_the_database_answers_and_is_migrated(monkeypatch):
    from zoikorum.main import create_app

    app = create_app()

    async def ready():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/ready")

    readiness_engine(monkeypatch, schema_guard.expected_heads())
    assert (await ready()).json()["status"] == "ready"
    readiness_engine(monkeypatch, {"old-revision"})
    r = await ready()
    assert r.status_code == 503 and r.json()["reason"] == "migrations not current"
    readiness_engine(monkeypatch, ConnectionError("down"))
    r = await ready()
    assert r.status_code == 503 and r.json()["reason"] == "database unavailable"
