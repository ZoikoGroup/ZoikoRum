"""Retry spacing and retry worthiness (Engineering Handbook 21.3: "retry with exponential backoff and jitter; never retry
what cannot succeed").

Jitter: after a partner outage many failed jobs come due at once. Spreading each delay between half and all of its value
keeps them from all hitting the partner again at the same moment.
"""

from __future__ import annotations

import random

from zoikorum.shared.errors import Conflict, DomainError, RateLimited, ServiceUnavailable


def jittered(seconds: float) -> float:
    """Somewhere between half and all of ``seconds``."""
    return seconds / 2 + random.uniform(0, seconds / 2)  # noqa: S311 - spacing, not security


def exponential(attempt: int, base: float = 30, cap: float = 3600) -> float:
    """Delay before retry number ``attempt`` (1, 2, ...): base, 2x base, 4x base ... up to ``cap``, with jitter."""
    return jittered(min(cap, base * 2 ** min(max(attempt - 1, 0), 16)))


def scheduled(attempt: int, steps: tuple[float, ...]) -> float:
    """Delay from a fixed schedule (the last step repeats), with jitter."""
    return jittered(steps[min(max(attempt - 1, 0), len(steps) - 1)])


def is_permanent(exc: BaseException) -> bool:
    """A failure that will fail the same way however often it is retried: the input or the rules are wrong, not the
    moment (invalid data, missing record, not allowed, blocked by policy). Conflicts (someone else changed it, a lock,
    a state not reached yet), rate limits and unavailable partners are worth retrying; so is anything unexpected."""
    return (isinstance(exc, DomainError) and exc.status < 500
            and not isinstance(exc, (Conflict, RateLimited, ServiceUnavailable)))
