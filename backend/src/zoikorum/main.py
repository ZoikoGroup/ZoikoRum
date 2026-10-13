"""FastAPI application factory for the Zoikorum modular monolith.

Each domain in ``zoikorum.domains.DOMAINS`` contributes:
  * ``api.router``  - mounted on the app
  * ``handlers``    - imported so its @subscribe / @on_timer registrations run
  * ``models``      - imported so its tables join the shared metadata
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from zoikorum.config import get_settings
from zoikorum.domains import DOMAINS
from zoikorum.shared import http, observability
from zoikorum.shared import platform_models  # noqa: F401 - registers platform tables
from zoikorum.shared.db import dispose_engine

log = logging.getLogger("zoikorum")


def _maybe_import(module: str):
    if importlib.util.find_spec(module) is None:
        return None
    return importlib.import_module(module)


def load_domains() -> list[str]:
    """Import models + handlers for every domain. Returns the loaded domain names."""
    import os

    # ZK_DOMAINS=identity,audit,proposal limits loading (isolated test runs).
    allow = {d.strip() for d in os.environ.get("ZK_DOMAINS", "").split(",") if d.strip()}
    loaded = []
    for d in DOMAINS:
        if allow and d not in allow:
            continue
        base = f"zoikorum.domains.{d}"
        if importlib.util.find_spec(base) is None:
            continue
        _maybe_import(f"{base}.models")
        _maybe_import(f"{base}.handlers")
        _maybe_import(f"{base}.privacy")  # personal-data export/erasure (shared/privacy.py)
        loaded.append(d)
    return loaded


@asynccontextmanager
async def lifespan(_: FastAPI):
    from zoikorum.shared.schema_guard import ensure_schema_current
    try:
        await ensure_schema_current()
        yield
    finally:
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    observability.setup("api")
    if settings.env not in ("local", "development", "test") and settings.rate_limit_enabled and not settings.redis_url:
        log.warning("ZK_REDIS_URL is not set: rate limits are counted per API process, not across servers")
    app = FastAPI(
        title="Zoikorum API",
        version="1.0.0",
        description="Governed professional services marketplace - backend platform API.",
        lifespan=lifespan,
    )
    http.install(app)
    async def validate_actor(actor, path, method):
        from zoikorum.domains.identity import facade as identity
        from zoikorum.domains.admin import facade as admin
        from zoikorum.shared.db import session_factory
        from zoikorum.shared.errors import Forbidden
        allow_restricted = path.startswith("/v1/enforcement-cases") or (path == "/v1/me" and method == "GET") or (path == "/v1/auth/logout" and method == "POST")
        async with session_factory()() as session:
            actor = await identity.validate_session_actor(session, actor, allow_restricted=allow_restricted)
            restrictions = await admin.active_restrictions(session, "IDENTITY", actor.identity_id)
            if set(restrictions).intersection({"SUSPEND_ACCOUNT", "OFFBOARD"}) and not allow_restricted:
                raise Forbidden("This account is restricted", code="ACCOUNT_NOT_ACTIVE")
            return actor
    app.state.actor_validator = validate_actor
    for d in load_domains():
        api = _maybe_import(f"zoikorum.domains.{d}.api")
        if api is not None and hasattr(api, "router"):
            app.include_router(api.router)

    @app.get("/health", tags=["platform"])
    async def health() -> dict:
        """Liveness: the process is up."""
        return {"status": "ok", "service": settings.service_name}

    @app.get("/ready", tags=["platform"])
    async def ready() -> JSONResponse:
        """Readiness: the database answers and is migrated. 503 tells the load balancer to send traffic elsewhere."""
        from zoikorum.shared.schema_guard import readiness

        problem = await readiness()
        if problem:
            return JSONResponse({"status": "not_ready", "reason": problem}, status_code=503)
        return JSONResponse({"status": "ready", "service": settings.service_name})

    return app


app = create_app()
