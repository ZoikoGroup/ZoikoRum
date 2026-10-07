"""Payment provider adapter (BUILD_SPEC s.payments). Zoikorum never sees raw card or bank data: only provider tokens.

The documents require a regulated third-party partner (Payments & Escrow s.22) without naming one. Any partner
(e.g. Stripe Connect, Adyen for Platforms, Razorpay Route) implements ``PaymentProvider``; nothing else changes.

FakeProvider (development and tests) succeeds unless the token is ``tok_fail`` or the account is ``acct_fail``.
Every money-moving call goes through a circuit breaker (Engineering Handbook 21.4).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from zoikorum.config import get_settings
from zoikorum.shared import clock
from zoikorum.shared.circuit import CircuitBreaker, Guarded


@dataclass(frozen=True)
class ChargeResult:
    ok: bool
    provider_ref: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    method_label: str = "Card"


@dataclass(frozen=True)
class PayoutResult:
    ok: bool
    provider_ref: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class ProviderReport:
    """What the provider says moved in a period, per currency (minor units): the provider side of reconciliation."""

    charges: dict[str, int] = field(default_factory=dict)
    payouts: dict[str, int] = field(default_factory=dict)
    refunds: dict[str, int] = field(default_factory=dict)


class PaymentProvider(Protocol):
    name: str

    def charge(self, token: str, amount_minor: int, currency: str) -> ChargeResult: ...
    def payout(self, account_ref: str, amount_minor: int, currency: str) -> PayoutResult: ...
    def create_payout_account(self, holder_name: str, country: str, currency: str, account_number: str) -> str: ...
    def refund(self, charge_ref: str | None, amount_minor: int, currency: str) -> PayoutResult: ...
    def verify_webhook(self, signature_header: str, body: bytes) -> bool: ...
    def report(self, since: datetime, until: datetime) -> ProviderReport | None: ...


def sign_webhook(body: bytes, secret: str, timestamp: int | None = None) -> str:
    """``t=<unix seconds>,v1=<HMAC-SHA256 of "<t>.<body>">``: the scheme the fake provider uses (Stripe-style)."""
    t = int(clock.now().timestamp()) if timestamp is None else timestamp
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify_signature(signature_header: str, body: bytes, secret: str, tolerance_seconds: int) -> bool:
    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        t = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(clock.now().timestamp() - t) > tolerance_seconds:
        return False  # too old (or from the future): a replayed or delayed message
    expected = sign_webhook(body, secret, t).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))


class FakeProvider:
    name = "fake"
    LABELS = {"tok_visa": "Test Visa •••• 4242", "tok_mastercard": "Test Mastercard •••• 4444", "tok_fail": "Test card (declined)"}

    def charge(self, token: str, amount_minor: int, currency: str) -> ChargeResult:
        label = self.LABELS.get(token, "Test card")
        if token == "tok_fail":
            return ChargeResult(False, failure_code="card_declined", failure_message="The card was declined", method_label=label)
        return ChargeResult(True, provider_ref=f"fake_ch_{uuid.uuid4().hex[:16]}", method_label=label)

    def payout(self, account_ref: str, amount_minor: int, currency: str) -> PayoutResult:
        if account_ref == "acct_fail":
            return PayoutResult(False, failure_message="The bank rejected the transfer")
        return PayoutResult(True, provider_ref=f"fake_po_{uuid.uuid4().hex[:16]}")

    def refund(self, charge_ref: str | None, amount_minor: int, currency: str) -> PayoutResult:
        return PayoutResult(True, provider_ref=f"fake_re_{uuid.uuid4().hex[:16]}")

    def create_payout_account(self, holder_name: str, country: str, currency: str, account_number: str) -> str:
        # The provider keeps the bank details; Zoikorum stores only this reference and the last four digits.
        return "acct_fail" if account_number.endswith("0000") else f"acct_{uuid.uuid4().hex[:16]}"

    def verify_webhook(self, signature_header: str, body: bytes) -> bool:
        s = get_settings()
        return verify_signature(signature_header, body, s.webhook_secret, s.webhook_tolerance_seconds)

    def report(self, since: datetime, until: datetime) -> ProviderReport | None:
        return None  # the fake keeps no books of its own; real providers return their settlement report


_breaker: CircuitBreaker | None = None


def breaker() -> CircuitBreaker:
    global _breaker
    if _breaker is None:
        s = get_settings()
        _breaker = CircuitBreaker("payment provider", s.provider_breaker_failures, s.provider_breaker_reset_seconds)
    return _breaker


def get_provider() -> PaymentProvider:
    return Guarded(FakeProvider(), breaker(), ("charge", "payout", "refund", "create_payout_account", "report"))  # type: ignore[return-value]
