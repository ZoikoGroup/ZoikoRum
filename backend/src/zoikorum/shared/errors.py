"""Domain errors rendered as RFC 9457 Problem Details (Handbook 18.2).

Raise these from aggregates and services; never return ad-hoc error dicts.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status: int = 400
    code: str = "DOMAIN_ERROR"
    title: str = "Request could not be processed"

    def __init__(self, detail: str | None = None, *, code: str | None = None, extra: dict[str, Any] | None = None):
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code:
            self.code = code
        self.extra = extra or {}


class ValidationFailed(DomainError):
    status, code, title = 422, "VALIDATION_FAILED", "Validation failed"


class NotFound(DomainError):
    status, code, title = 404, "NOT_FOUND", "Resource not found"


class Forbidden(DomainError):
    status, code, title = 403, "FORBIDDEN", "You are not allowed to perform this action"


class Unauthenticated(DomainError):
    status, code, title = 401, "UNAUTHENTICATED", "Authentication required"


class StepUpRequired(DomainError):
    """Sensitive operation needs fresh MFA (Architecture 11.4)."""

    status, code, title = 401, "STEP_UP_REQUIRED", "Elevated authentication required"


class Conflict(DomainError):
    status, code, title = 409, "CONFLICT", "Conflict with current resource state"


class VersionConflict(Conflict):
    code, title = "VERSION_CONFLICT", "Resource was modified by someone else"


class InvalidStateTransition(Conflict):
    code, title = "INVALID_STATE_TRANSITION", "This action is not allowed in the current state"

    def __init__(self, aggregate: str, from_state: str, to_state: str):
        super().__init__(
            f"{aggregate}: {from_state} -> {to_state} is not allowed",
            extra={"aggregate": aggregate, "from": from_state, "to": to_state},
        )


class PolicyBlocked(DomainError):
    status, code, title = 403, "POLICY_BLOCKED", "Policy blocked this action"


class ApprovalRequired(DomainError):
    status, code, title = 409, "APPROVAL_REQUIRED", "Approval is required before this action can proceed"


class ExceptionRequired(DomainError):
    status, code, title = 409, "EXCEPTION_REQUIRED", "A policy exception is required before this action can proceed"


class IdempotencyKeyRequired(DomainError):
    status, code, title = 400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required"


class IdempotencyKeyReused(DomainError):
    status, code, title = 422, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request"


class RateLimited(DomainError):
    status, code, title = 429, "RATE_LIMITED", "Too many requests"
