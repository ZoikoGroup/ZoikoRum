"""Verification provider adapter. A real KYC / sanctions / registry provider plugs in behind
``VerificationProvider``; ``FakeProvider`` is deterministic for development and tests.

A provider can say PASS (verified automatically), REVIEW (a compliance officer decides) or FAIL.
AI never decides a verification.
"""

from __future__ import annotations

from typing import Protocol


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
    return FakeProvider()
