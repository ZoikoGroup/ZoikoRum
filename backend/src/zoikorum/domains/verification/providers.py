"""Verification provider adapter. A real KYC / sanctions / registry provider plugs in behind
``VerificationProvider``; ``FakeProvider`` is deterministic for development and tests.

A provider can say PASS (verified automatically), REVIEW (a compliance officer decides) or FAIL.
AI never decides a verification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from functools import lru_cache
from typing import Protocol

import httpx

from zoikorum.config import get_settings
from zoikorum.shared.circuit import CircuitBreaker
from zoikorum.shared.errors import ServiceUnavailable

log = logging.getLogger("zoikorum.verification")


class VerificationProvider(Protocol):
    async def check(self, verification_type: str, details: dict) -> str:
        """Return PASS | REVIEW | FAIL."""


class FakeProvider:
    """Sanctions screening passes automatically unless the screened name contains "sanction"
    (a potential match, which goes to human review). Everything document-based goes to human review."""

    async def check(self, verification_type: str, details: dict) -> str:
        if verification_type == "RESTRICTIONS":
            return "REVIEW" if "sanction" in str(details.get("name", "")).lower() else "PASS"
        return "REVIEW"


def get_provider() -> VerificationProvider:
    settings = get_settings()
    if settings.verification_provider in ("fake", "simulated") and settings.env in ("local", "test", "development"):
        return FakeProvider()
    if settings.verification_provider in ("manual", "persona", "veriff"):
        return ManualProvider()
    raise ServiceUnavailable("Choose a verification integration or explicit manual review", code="INTEGRATION_NOT_CONFIGURED")


class ManualProvider:
    async def check(self, verification_type, details):
        # An absent external result can never clear screening or verify an identity.
        return "REVIEW"


class PersonaProvider:
    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport
        if not (settings.persona_api_key and settings.persona_template_id and settings.persona_webhook_secret):
            raise ServiceUnavailable("Persona credentials and workflow have not been configured", code="INTEGRATION_NOT_CONFIGURED")

    async def request(self, path, body, key=None):
        headers = {"Authorization": "Bearer " + self.settings.persona_api_key, "Persona-Version": "2025-12-08"}
        if key:
            headers["Idempotency-Key"] = key
        try:
            async with httpx.AsyncClient(base_url="https://api.withpersona.com/api/v1/", timeout=20, transport=self.transport) as client:
                result = await client.post(path, json=body, headers=headers)
            result.raise_for_status()
            return result.json()
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("Identity partner could not complete the request", code="PROVIDER_UNAVAILABLE") from exc

    async def create(self, case_id):
        result = await self.request("inquiries", {"data": {"attributes": {
            "inquiry-template-id": self.settings.persona_template_id, "reference-id": str(case_id)}}}, "inquiry:" + str(case_id))
        return result["data"]["id"]

    async def link(self, inquiry_id):
        result = await self.request("inquiries/" + inquiry_id + "/generate-one-time-link", {})
        return result["meta"]["one-time-link"]


# Veriff decision statuses -> the case outcome (see integration.apply_result).
VERIFF_STATUS = {"approved": "approved", "declined": "declined", "resubmission_requested": "resubmission_requested",
                 "review": "needs_review", "expired": "expired", "abandoned": "expired"}


class VeriffProvider:
    """Veriff Station API. Requests carry X-AUTH-CLIENT (API key) and X-HMAC-SIGNATURE (HMAC-SHA256 with the shared
    secret over the body, or over the session id for reads). Only our case id is sent; the person's details come from
    their own document. ``create`` keeps the session link in ``created_url`` (Veriff links last about a week)."""

    name = "veriff"

    def __init__(self, settings, transport=None):
        if not (settings.veriff_api_key and settings.veriff_shared_secret):
            raise ServiceUnavailable("Veriff credentials have not been configured", code="INTEGRATION_NOT_CONFIGURED")
        self.settings, self.transport = settings, transport
        self.created_url: str | None = None

    def sign(self, payload: bytes) -> str:
        return hmac.new(self.settings.veriff_shared_secret.encode(), payload, hashlib.sha256).hexdigest()

    async def request(self, method, path, signed: bytes, body: bytes | None = None) -> dict:
        headers = {"X-AUTH-CLIENT": self.settings.veriff_api_key, "X-HMAC-SIGNATURE": self.sign(signed),
                   "Content-Type": "application/json"}

        async def send() -> httpx.Response:
            async with httpx.AsyncClient(base_url=self.settings.veriff_base_url, timeout=20, transport=self.transport) as client:
                result = await client.request(method, path, content=body, headers=headers)
            if result.status_code >= 500:
                result.raise_for_status()  # a partner outage counts against the breaker; a 4xx is an answer
            return result

        try:
            result = await _veriff_breaker().acall(send)
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("Identity partner could not complete the request", code="PROVIDER_UNAVAILABLE") from exc
        if result.status_code >= 400:
            log.warning("veriff %s refused with HTTP %s", method, result.status_code)  # usually a wrong key or secret
            raise ServiceUnavailable("Identity partner refused the request", code="PROVIDER_REJECTED")
        return result.json()

    async def create(self, case_id):
        body = json.dumps({"verification": {"callback": self.return_url(case_id), "vendorData": str(case_id)}}).encode()
        session = (await self.request("POST", "/v1/sessions", body, body))["verification"]
        self.created_url = str(session["url"])
        return str(session["id"])

    async def link(self, session_id):
        return self.created_url  # Veriff has no "new link" call: the stored link is used (integration.hosted)

    def return_url(self, case_id) -> str:
        return f"{self.settings.frontend_url}/app/professional/verification?verification={case_id}"

    async def decision(self, session_id) -> tuple[str, str | None] | None:
        """Polled when the professional comes back (and the webhook may not have arrived): (status, reason) or None."""
        found = (await self.request("GET", f"/v1/sessions/{session_id}/decision", session_id.encode())).get("verification")
        if not found or found.get("status") not in VERIFF_STATUS:
            return None
        return VERIFF_STATUS[found["status"]], found.get("reason")

    def verify(self, signature: str | None, body: bytes) -> bool:
        return bool(signature) and hmac.compare_digest(signature.lower(), self.sign(body))


class SimulatedProvider:
    """Development only: no partner is called; the page offers the answers a partner can give (integration.simulate)."""

    name = "simulated"
    created_url = None

    def __init__(self, settings, transport=None):
        self.settings = settings

    async def create(self, case_id):
        return f"sim_{uuid.uuid4().hex}"

    async def link(self, session_id):
        return None


@lru_cache
def _veriff_breaker() -> CircuitBreaker:
    settings = get_settings()
    return CircuitBreaker("identity partner", settings.provider_breaker_failures, settings.provider_breaker_reset_seconds)
