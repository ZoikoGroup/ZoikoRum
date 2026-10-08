"""Verification provider adapter. A real KYC / sanctions / registry provider plugs in behind
``VerificationProvider``; ``FakeProvider`` is deterministic for development and tests.

A provider can say PASS (verified automatically), REVIEW (a compliance officer decides) or FAIL.
AI never decides a verification.
"""

from __future__ import annotations

from typing import Protocol
import httpx
from zoikorum.config import get_settings
from zoikorum.shared.errors import ServiceUnavailable


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
    if settings.verification_provider == "fake" and settings.env in ("local", "test", "development"):
        return FakeProvider()
    if settings.verification_provider in ("manual", "persona"):
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
