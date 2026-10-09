"""HTTP edge concerns: correlation IDs, Problem Details, rate limiting, pagination."""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Generic, TypeVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import ProgrammingError
from starlette.middleware.base import BaseHTTPMiddleware

from zoikorum.config import get_settings
from zoikorum.shared import context
from zoikorum.shared.errors import DomainError, RateLimited, ValidationFailed, VersionConflict, ServiceUnavailable

log = logging.getLogger("zoikorum.http")

PROBLEM_BASE = "https://docs.zoikorum.com/errors/"


def problem(err: DomainError) -> JSONResponse:
    body = {
        "type": PROBLEM_BASE + err.code.lower().replace("_", "-"),
        "title": err.title,
        "status": err.status,
        "detail": err.detail,
        "code": err.code,
        "correlationId": context.current().correlation_id,
    }
    if err.extra:
        body["extra"] = err.extra
    return JSONResponse(body, status_code=err.status, media_type="application/problem+json")


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cid = request.headers.get("X-Correlation-Id") or context.new_correlation_id()
        with context.use_context(context.ExecutionContext(correlation_id=cid, actor_type="anonymous")):
            started = time.perf_counter()
            response = await call_next(request)
            response.headers["X-Correlation-Id"] = cid
            log.info(
                json.dumps(
                    {
                        "msg": "request",
                        "correlationId": cid,
                        "method": request.method,
                        "route": request.url.path,
                        "status": response.status_code,
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                )
            )
            return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket per caller (Architecture 7.4). In-memory for one node;
    swap the bucket store for Redis when running more than one replica."""

    LIMITS = {"anonymous": (60, 120), "user": (300, 600)}

    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])

    async def dispatch(self, request: Request, call_next):
        if not get_settings().rate_limit_enabled:
            return await call_next(request)
        auth = request.headers.get("Authorization")
        kind = "user" if auth else "anonymous"
        key = (auth[-24:] if auth else (request.client.host if request.client else "unknown"))
        rate_per_min, burst = self.LIMITS[kind]
        tokens, last = self._buckets[key]
        now = time.monotonic()
        tokens = burst if last == 0 else min(burst, tokens + (now - last) * rate_per_min / 60)
        if tokens < 1:
            self._buckets[key] = [tokens, now]
            return problem(RateLimited())
        self._buckets[key] = [tokens - 1, now]
        return await call_next(request)


def install(app: FastAPI) -> None:
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CorrelationMiddleware)

    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        return problem(exc)

    @app.exception_handler(ProgrammingError)
    async def _database_schema(_: Request, exc: ProgrammingError):
        if getattr(exc.orig, "sqlstate", None) not in {"42P01", "42703"}:
            raise exc
        log.error("Database schema mismatch; correlationId=%s; sqlstate=%s",
                  context.current().correlation_id, getattr(exc.orig, "sqlstate", None))
        return problem(ServiceUnavailable(
            "Zoikorum is temporarily unavailable while a database update is required. Please contact support.",
            code="DATABASE_SCHEMA_OUTDATED"))

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, __: StaleDataError):
        return problem(VersionConflict())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = json.loads(json.dumps(exc.errors(), default=str))
        first = errors[0] if errors else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:]) or "request"
        reason = str(first.get("msg", "is invalid")).removeprefix("Value error, ")
        err = ValidationFailed(f"{field}: {reason}" if errors else "Request is invalid", extra={"errors": errors})
        return problem(err)


# ---------------------------------------------------------------------------
# Cursor pagination (Handbook 18.3) - never return unbounded collections.
# ---------------------------------------------------------------------------

T = TypeVar("T")
MAX_PAGE = 100


class Page(BaseModel, Generic[T]):
    items: list[T]
    nextCursor: str | None = None


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "i": str(row_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["i"])
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed("Invalid cursor") from exc


def clamp_limit(limit: int | None) -> int:
    return max(1, min(limit or 20, MAX_PAGE))


def paginate(stmt: Any, model: Any, cursor: str | None, limit: int | None):
    """Keyset pagination on (created_at DESC, id DESC). Returns (stmt, limit)."""
    from sqlalchemy import and_, or_

    lim = clamp_limit(limit)
    pos = decode_cursor(cursor)
    if pos:
        t, i = pos
        stmt = stmt.where(or_(model.created_at < t, and_(model.created_at == t, model.id < i)))
    return stmt.order_by(model.created_at.desc(), model.id.desc()).limit(lim + 1), lim


def page_of(rows: list, lim: int, to_dto) -> dict:
    items = rows[:lim]
    nxt = encode_cursor(items[-1].created_at, items[-1].id) if len(rows) > lim and items else None
    return {"items": [to_dto(r) for r in items], "nextCursor": nxt}
