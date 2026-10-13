"""HTTP edge concerns: correlation IDs, Problem Details, rate limiting, pagination."""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Annotated, Any, Generic, TypeVar

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import ProgrammingError
from starlette.middleware.base import BaseHTTPMiddleware

from zoikorum.config import get_settings
from zoikorum.shared import context, metrics, observability, ratelimit
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
            observability.tag_current_span(correlation_id=cid)
            started = time.perf_counter()
            response = await call_next(request)
            response.headers["X-Correlation-Id"] = cid
            elapsed = time.perf_counter() - started
            log.info("request", extra={"fields": {
                "method": request.method, "route": request.url.path, "status": response.status_code,
                "ms": round(elapsed * 1000, 1)}})
            if request.url.path != "/metrics":
                metrics.observe_request(request.method, getattr(request.scope.get("route"), "path", None),
                                        response.status_code, elapsed)
            return response


class SecurityHeadersMiddleware:
    """Security headers on every API response (OWASP secure headers). Pure ASGI, so streaming responses pass through.
    A response that sets its own header keeps it (stored documents use ``Content-Security-Policy: sandbox``); the
    interactive API docs keep their scripts. HSTS is sent only where the API is served over HTTPS (not local/test)."""

    ALWAYS = {
        b"x-content-type-options": b"nosniff",
        b"x-frame-options": b"DENY",
        b"referrer-policy": b"no-referrer",
        b"permissions-policy": b"camera=(), microphone=(), geolocation=(), payment=()",
        b"cross-origin-opener-policy": b"same-origin",
    }
    API_CSP = b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        signed_in = any(name == b"authorization" for name, _ in scope.get("headers", []))
        https = get_settings().env not in ("local", "development", "test")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                wanted = dict(self.ALWAYS)
                if not path.startswith(self.DOCS_PATHS):
                    wanted[b"content-security-policy"] = self.API_CSP
                if signed_in:
                    wanted[b"cache-control"] = b"no-store"  # personal data is never cached by browsers or proxies
                if https:
                    wanted[b"strict-transport-security"] = b"max-age=63072000; includeSubDomains"
                headers += [(name, value) for name, value in wanted.items() if name not in present]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def caller_key(request: Request) -> tuple[str, str]:
    """("user", identity id) for a valid access token, else ("anonymous", client address). An unverified header never
    names a bucket: a made-up token would otherwise get a fresh budget on every request."""
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        from zoikorum.shared.auth import decode_access_token

        try:
            return "user", str(decode_access_token(auth[7:]).identity_id)
        except DomainError:
            pass
    return "anonymous", request.client.host if request.client else "unknown"


async def enforce_budget(kind: str, identifier: str, rate_per_min: int, burst: int, message: str) -> None:
    """A specific budget on top of the general one (sign-in per email, AI calls per person, ...)."""
    if get_settings().rate_limit_enabled and not await ratelimit.get_buckets().take(
            ratelimit.bucket_key(kind, identifier), rate_per_min, burst):
        raise RateLimited(message)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket per caller (Architecture 7.4): per signed-in session, or per client address (behind the load
    balancer uvicorn takes it from X-Forwarded-For). Shared across servers through Redis when ZK_REDIS_URL is set
    (shared/ratelimit.py)."""

    LIMITS = {"anonymous": (60, 120), "user": (300, 600)}  # (requests per minute, burst)

    async def dispatch(self, request: Request, call_next):
        if not get_settings().rate_limit_enabled:
            return await call_next(request)
        kind, identifier = caller_key(request)
        rate_per_min, burst = self.LIMITS[kind]
        if not await ratelimit.get_buckets().take(ratelimit.bucket_key(kind, identifier), rate_per_min, burst):
            return problem(RateLimited())
        return await call_next(request)


def install(app: FastAPI) -> None:
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)  # outermost: also covers rate-limit and error responses

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


def paginate(stmt: Any, model: Any, cursor: str | None, limit: int | None, *, oldest_first: bool = False):
    """Keyset pagination on (created_at, id): newest first, or oldest first for work queues. Returns (stmt, limit)."""
    from sqlalchemy import and_, or_

    lim = clamp_limit(limit)
    pos = decode_cursor(cursor)
    if pos:
        t, i = pos
        if oldest_first:
            stmt = stmt.where(or_(model.created_at > t, and_(model.created_at == t, model.id > i)))
        else:
            stmt = stmt.where(or_(model.created_at < t, and_(model.created_at == t, model.id < i)))
    order = (model.created_at, model.id) if oldest_first else (model.created_at.desc(), model.id.desc())
    return stmt.order_by(*order).limit(lim + 1), lim


def next_cursor(rows: list, lim: int, key=lambda r: r) -> str | None:
    """The cursor for the page after ``rows[:lim]`` (``rows`` holds one extra row when there is one)."""
    if len(rows) <= lim or not lim:
        return None
    last = key(rows[lim - 1])
    return encode_cursor(last.created_at, last.id)


def page_of(rows: list, lim: int, to_dto) -> dict:
    return {"items": [to_dto(r) for r in rows[:lim]], "nextCursor": next_cursor(rows, lim)}


# ---- Optimistic concurrency (Engineering Handbook 18.4) -------------------------------------------------------------

IfMatch = Annotated[str | None, Header(alias="If-Match", description="The version you last saw (the resource's `version`). "
                                       "Refused with 409 VERSION_CONFLICT if someone changed it since.")]


def expect_version(if_match: str | None, current: int, what: str) -> None:
    """Refuse an edit made on an old copy: two people editing the same thing must not silently overwrite each other.
    Without the header the edit goes ahead (older clients)."""
    raw = (if_match or "").strip().removeprefix("W/").strip('"')
    if raw.isdigit() and int(raw) != current:
        raise VersionConflict(f"{what} was changed by someone else while you were editing. Reload to see the changes, "
                              "then make yours again.")
