"""Credential-expiry reminders: 30/14/7 days before expiry, none that are already in the past."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from zoikorum.domains.verification.service import REMINDER_DAYS, reminder_schedule

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_reminders_at_30_14_7_days():
    exp = NOW + timedelta(days=90)
    assert REMINDER_DAYS == (30, 14, 7)
    assert reminder_schedule(exp, NOW) == [(30, exp - timedelta(days=30)), (14, exp - timedelta(days=14)), (7, exp - timedelta(days=7))]


def test_past_reminders_are_skipped():
    exp = NOW + timedelta(days=10)
    assert [d for d, _ in reminder_schedule(exp, NOW)] == [7]
    assert reminder_schedule(NOW + timedelta(days=3), NOW) == []
