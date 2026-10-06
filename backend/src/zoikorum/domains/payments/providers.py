"""Payment provider adapter (BUILD_SPEC s.payments). Zoikorum never sees raw card or bank data: only provider tokens.

FakeProvider (development and tests) succeeds unless the token is ``tok_fail`` or the account is ``acct_fail``.
A real provider (e.g. a regulated PSP) implements the same interface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


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


class PaymentProvider(Protocol):
    name: str

    def charge(self, token: str, amount_minor: int, currency: str) -> ChargeResult: ...
    def payout(self, account_ref: str, amount_minor: int, currency: str) -> PayoutResult: ...
    def create_payout_account(self, holder_name: str, country: str, currency: str, account_number: str) -> str: ...


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

    def create_payout_account(self, holder_name: str, country: str, currency: str, account_number: str) -> str:
        # The provider keeps the bank details; Zoikorum stores only this reference and the last four digits.
        return "acct_fail" if account_number.endswith("0000") else f"acct_{uuid.uuid4().hex[:16]}"


def get_provider() -> PaymentProvider:
    return FakeProvider()
