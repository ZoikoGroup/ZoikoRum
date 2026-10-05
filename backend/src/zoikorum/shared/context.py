"""Request/event execution context propagated via contextvars.

Correlation ID ties together every request, event, log line and audit record of
one business chain (Architecture 6.4). Causation ID is the immediate upstream
event/action. Both are copied into every outbox event automatically.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator


@dataclass(frozen=True)
class ExecutionContext:
    correlation_id: str
    causation_id: str | None = None
    actor_id: str | None = None
    actor_type: str = "system"  # user | system | operator | service
    tenant_id: str | None = None
    auth_strength: str | None = None
    extra: dict = field(default_factory=dict)


_ctx: ContextVar[ExecutionContext | None] = ContextVar("zk_execution_context", default=None)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def current() -> ExecutionContext:
    ctx = _ctx.get()
    if ctx is None:
        ctx = ExecutionContext(correlation_id=new_correlation_id())
        _ctx.set(ctx)
    return ctx


def set_context(ctx: ExecutionContext) -> None:
    _ctx.set(ctx)


@contextmanager
def use_context(ctx: ExecutionContext) -> Iterator[ExecutionContext]:
    token = _ctx.set(ctx)
    try:
        yield ctx
    finally:
        _ctx.reset(token)


def bind_actor(actor_id: str, actor_type: str, tenant_id: str | None, auth_strength: str | None) -> None:
    c = current()
    _ctx.set(
        ExecutionContext(
            correlation_id=c.correlation_id,
            causation_id=c.causation_id,
            actor_id=actor_id,
            actor_type=actor_type,
            tenant_id=tenant_id,
            auth_strength=auth_strength,
            extra=c.extra,
        )
    )
