"""Comparing an amount with a spend limit set in another currency.

Finance sets the exchange rates (ZK_FX_RATES: units of each currency per 1 USD, e.g. {"USD": 1, "EUR": 0.92, "INR": 83.2})
and a safety margin (ZK_FX_MARGIN_BPS). The converted amount is rounded up and the margin added, so a rate that moved
since it was set can only make the check stricter, never let a larger amount through. Without a rate for both currencies
a limit in another currency does not authorise the amount (the rule before rates existed).
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from zoikorum.config import get_settings

# ISO 4217 minor units for currencies that do not use two decimals.
_EXPONENT = {"JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "ISK": 0, "UGX": 0, "XOF": 0, "XAF": 0,
             "KWD": 3, "BHD": 3, "OMR": 3, "JOD": 3, "TND": 3}


def _exponent(currency: str) -> int:
    return _EXPONENT.get(currency.upper(), 2)


def convert(amount_minor: int, currency: str, to_currency: str) -> int | None:
    """The amount in `to_currency` minor units, with the safety margin added and rounded up; None without rates."""
    currency, to_currency = currency.upper(), to_currency.upper()
    if currency == to_currency:
        return amount_minor
    s = get_settings()
    rates = {k.upper(): Decimal(str(v)) for k, v in s.fx_rates.items()}
    if currency not in rates or to_currency not in rates or rates[currency] <= 0 or rates[to_currency] <= 0:
        return None
    major = Decimal(amount_minor) / (Decimal(10) ** _exponent(currency))
    converted = major / rates[currency] * rates[to_currency] * (1 + Decimal(s.fx_margin_bps) / 10_000)
    return int((converted * (Decimal(10) ** _exponent(to_currency))).to_integral_value(rounding=ROUND_CEILING))


def within_limit(amount_minor: int, currency: str | None, limit_minor: int, limit_currency: str) -> bool:
    """True when the amount is no more than the limit, converting conservatively if the currencies differ."""
    if not currency:
        return False
    converted = convert(amount_minor, currency, limit_currency)
    return converted is not None and converted <= limit_minor
