"""Money value object. Never use floats for money (Handbook 4.3).

Amounts are integer minor units (cents, pence ...) plus an ISO-4217 currency.
Persist as two columns: <name>_minor BIGINT and <name>_currency CHAR(3).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from zoikorum.shared.errors import ValidationFailed


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.minor, int) or isinstance(self.minor, bool):
            raise ValidationFailed("Money minor units must be an integer")
        if self.minor < 0:
            raise ValidationFailed("Money cannot be negative")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValidationFailed(f"Invalid currency code: {self.currency!r}")

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(0, currency)

    def _same(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValidationFailed(f"Cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.minor - other.minor, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._same(other)
        return self.minor < other.minor

    def __le__(self, other: "Money") -> bool:
        self._same(other)
        return self.minor <= other.minor

    def is_zero(self) -> bool:
        return self.minor == 0

    def percentage_bps(self, bps: int) -> "Money":
        """Basis-point share, rounded half-up to the minor unit."""
        return Money((self.minor * bps + 5_000) // 10_000, self.currency)

    def to_dict(self) -> dict:
        return {"amountMinor": self.minor, "currency": self.currency}


class MoneyDTO(BaseModel):
    """API shape for money: {"amountMinor": 150000, "currency": "USD"}."""

    amountMinor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")

    def to_money(self) -> Money:
        return Money(self.amountMinor, self.currency)

    @classmethod
    def of(cls, m: Money) -> "MoneyDTO":
        return cls(amountMinor=m.minor, currency=m.currency)
