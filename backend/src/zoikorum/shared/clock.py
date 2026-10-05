"""Single source of 'now' for domain logic, so tests can travel in time.

Domain code must call ``clock.now()`` instead of ``datetime.now()``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_override: datetime | None = None


def now() -> datetime:
    return _override if _override is not None else datetime.now(timezone.utc)


def set_now(value: datetime | None) -> None:
    global _override
    _override = value


def advance(delta: timedelta) -> datetime:
    global _override
    _override = now() + delta
    return _override
