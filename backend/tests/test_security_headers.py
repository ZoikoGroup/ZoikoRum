"""Security headers on every API response (shared/http.py SecurityHeadersMiddleware)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient

from prodsettings import PRODUCTION
from zoikorum.config import Settings
from zoikorum.shared import http


def app_with_headers() -> FastAPI:
    app = FastAPI()
    http.install(app)

    @app.get("/plain")
    async def plain():
        return {"ok": True}

    @app.get("/document")
    async def document():  # stored files set their own, stricter policy
        return Response(b"%PDF-", media_type="application/pdf",
                        headers={"Content-Security-Policy": "sandbox", "Cache-Control": "no-store"})

    return app


async def get(app, path, **headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, headers=headers)


@pytest.mark.unit
async def test_every_response_carries_security_headers():
    r = await get(app_with_headers(), "/plain")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "camera=()" in r.headers["permissions-policy"]
    assert "strict-transport-security" not in r.headers  # local and test run over plain HTTP
    assert "cache-control" not in r.headers  # public reads may be cached


@pytest.mark.unit
async def test_signed_in_responses_are_never_cached_and_own_headers_win():
    app = app_with_headers()
    r = await get(app, "/plain", Authorization="Bearer x")
    assert r.headers["cache-control"] == "no-store"
    doc = await get(app, "/document")
    assert doc.headers["content-security-policy"] == "sandbox"  # not replaced by the API policy
    assert doc.headers.get_list("content-security-policy") == ["sandbox"]


@pytest.mark.unit
async def test_errors_and_docs(monkeypatch):
    app = app_with_headers()
    missing = await get(app, "/nowhere")
    assert missing.status_code == 404 and missing.headers["x-frame-options"] == "DENY"
    docs = await get(app, "/docs")
    assert "content-security-policy" not in docs.headers  # the interactive docs need their scripts


@pytest.mark.unit
async def test_hsts_outside_development(monkeypatch):
    monkeypatch.setattr(http, "get_settings", lambda: Settings(_env_file=None, **PRODUCTION, rate_limit_enabled=False))
    r = await get(app_with_headers(), "/plain")
    assert r.headers["strict-transport-security"].startswith("max-age=63072000")


@pytest.mark.unit
@pytest.mark.parametrize("override, message", [
    ({"jwt_secret": "dev-only-secret-change-me-32-bytes-minimum!!"}, "ZK_JWT_SECRET"),
    ({"field_encryption_key": "short"}, "ZK_FIELD_ENCRYPTION_KEY"),
    ({"webhook_secret": "dev-webhook-secret"}, "ZK_WEBHOOK_SECRET"),
    ({"frontend_url": "http://app.zoikorum.test"}, "https"),
])
def test_production_refuses_development_secrets(override, message):
    with pytest.raises(ValueError, match=message):
        Settings(_env_file=None, **(PRODUCTION | override))
    Settings(_env_file=None, **PRODUCTION)  # real values start


@pytest.mark.unit
def test_configuration_errors_never_show_values():
    with pytest.raises(ValueError) as refused:
        Settings(_env_file=None, **(PRODUCTION | {"jwt_secret": "short-SECRET-VALUE"}))
    assert "short-SECRET-VALUE" not in str(refused.value) and "ZK_JWT_SECRET" in str(refused.value)
