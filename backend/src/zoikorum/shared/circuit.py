"""Circuit breakers around external providers (Engineering Handbook 21.4: "If a dependency is failing, stop hammering it").

A breaker counts consecutive technical failures (exceptions such as timeouts or connection errors; a declined card is a
normal business answer, not a failure). After ``failure_threshold`` failures it OPENS: calls fail fast with
``ServiceUnavailable`` instead of waiting on a broken partner. After ``reset_seconds`` one trial call is let through
(HALF-OPEN); success closes the breaker, failure opens it again. Event consumers that hit an open breaker fail and are
retried by the worker later, which is the "queue retry" step of the release decision tree (Handbook 15.2).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from zoikorum.shared import clock
from zoikorum.shared.errors import ServiceUnavailable

log = logging.getLogger("zoikorum.circuit")
T = TypeVar("T")


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, reset_seconds: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_at = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "CLOSED"
        if (clock.now() - self.opened_at).total_seconds() >= self.reset_seconds:
            return "HALF_OPEN"
        return "OPEN"

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if self.state == "OPEN":
            raise ServiceUnavailable(f"The {self.name} is temporarily unavailable. We will retry automatically.",
                                     code="PROVIDER_UNAVAILABLE")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.failures += 1
            # A failed trial call (half-open) or too many failures in a row: open (again) for another cool-down.
            if self.opened_at is not None or self.failures >= self.failure_threshold:
                log.warning("circuit %s open after %d consecutive failures", self.name, self.failures)
                self.opened_at = clock.now()
            raise
        self.failures, self.opened_at = 0, None
        return result

    def reset(self) -> None:
        self.failures, self.opened_at = 0, None


class Guarded:
    """Wraps a provider object so the listed methods go through a breaker; everything else passes straight through."""

    def __init__(self, inner: Any, breaker: CircuitBreaker, methods: tuple[str, ...]):
        self._inner, self._breaker, self._methods = inner, breaker, methods

    def __getattr__(self, item: str) -> Any:
        attr = getattr(self._inner, item)
        if item in self._methods and callable(attr):
            return lambda *a, **kw: self._breaker.call(attr, *a, **kw)
        return attr
