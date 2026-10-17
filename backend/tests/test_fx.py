"""Spend limits in another currency: converted at Finance's rate with a safety margin, never in the spender's favour."""

from __future__ import annotations

import pytest

from zoikorum.config import get_settings
from zoikorum.shared import fx


@pytest.fixture
def rates(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "fx_rates", {"USD": 1, "EUR": 0.9, "JPY": 150, "KWD": 0.3})
    monkeypatch.setattr(s, "fx_margin_bps", 300)


def test_same_currency_needs_no_rates():
    assert fx.within_limit(10_000, "USD", 10_000, "USD")
    assert not fx.within_limit(10_001, "USD", 10_000, "USD")


def test_without_rates_a_limit_in_another_currency_does_not_authorise(monkeypatch):
    monkeypatch.setattr(get_settings(), "fx_rates", {})
    assert fx.convert(100_00, "USD", "EUR") is None
    assert not fx.within_limit(1, "USD", 1_000_000, "EUR")
    assert not fx.within_limit(1, None, 1_000_000, "EUR")


def test_conversion_adds_the_margin_and_rounds_up(rates):
    # USD 100.00 -> EUR 90.00, plus 3% -> EUR 92.70
    assert fx.convert(100_00, "USD", "EUR") == 92_70
    assert fx.within_limit(100_00, "USD", 92_70, "EUR")
    assert not fx.within_limit(100_00, "USD", 92_69, "EUR")
    assert fx.convert(1, "USD", "EUR") == 1  # a fraction of a cent rounds up, never down


def test_currencies_without_two_decimals(rates):
    assert fx.convert(100_00, "USD", "JPY") == 15_450  # 15,000 yen + 3%, yen has no minor unit
    assert fx.convert(100_00, "USD", "KWD") == 30_900  # KWD 30.000 + 3%, three decimals
    assert fx.convert(15_000, "JPY", "USD") == 103_00
