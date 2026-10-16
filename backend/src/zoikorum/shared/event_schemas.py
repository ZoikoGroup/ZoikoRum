"""Typed payloads for the events that move money or decide disputes (Engineering handbook: typed event contracts).

Consumers in other domains act on these payloads (hold, release, refund, pay out), so a missing or mistyped field is
a money bug. `record_event` checks each payload against its schema: outside production a mismatch is an error at
the point of emission (tests catch it); in production it is logged and the event still goes out, so a schema slip
never blocks a payment. Extra fields are allowed: producers may add context without changing the contract.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from zoikorum.shared.event_catalog import E

Currency = str  # ISO 4217, three letters
Minor = int  # amount in minor units (cents)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="allow")


class PaymentCaptured(_Payload):
    paymentIntentId: uuid.UUID
    escrowAccountId: uuid.UUID
    fundingId: uuid.UUID
    amountMinor: Minor = Field(ge=0)
    currency: Currency = Field(min_length=3, max_length=3)


class EscrowFunded(_Payload):
    escrowAccountId: uuid.UUID
    contractId: uuid.UUID
    organizationId: uuid.UUID
    fundingId: uuid.UUID
    milestoneIds: list[uuid.UUID] = Field(min_length=1)
    amountMinor: Minor = Field(ge=0)
    currency: Currency = Field(min_length=3, max_length=3)


class MilestoneAccepted(_Payload):
    contractId: uuid.UUID
    organizationId: uuid.UUID
    professionalId: uuid.UUID
    milestoneId: uuid.UUID
    amountMinor: Minor = Field(ge=0)
    currency: Currency = Field(min_length=3, max_length=3)


class EscrowReleased(_Payload):
    escrowAccountId: uuid.UUID
    contractId: uuid.UUID
    milestoneId: uuid.UUID
    professionalId: uuid.UUID
    grossMinor: Minor = Field(ge=0)
    feeMinor: Minor = Field(ge=0)
    netMinor: Minor = Field(ge=0)
    currency: Currency = Field(min_length=3, max_length=3)
    releaseId: uuid.UUID


class EscrowRefunded(_Payload):
    escrowAccountId: uuid.UUID
    contractId: uuid.UUID
    amountMinor: Minor = Field(ge=0)
    currency: Currency = Field(min_length=3, max_length=3)
    refundId: uuid.UUID


class Allocation(_Payload):
    milestoneId: uuid.UUID
    releaseMinor: Minor = Field(ge=0)
    refundMinor: Minor = Field(ge=0)


class DisputeResolved(_Payload):
    disputeId: uuid.UUID
    contractId: uuid.UUID
    outcome: str
    decisionPath: Literal["DIRECT", "MEDIATION", "PLATFORM", "ARBITRATION"]
    allocations: list[Allocation]
    currency: Currency = Field(min_length=3, max_length=3)


class ResolutionExecuted(_Payload):
    disputeId: uuid.UUID
    escrowAccountId: uuid.UUID
    releasedMinor: Minor = Field(ge=0)
    refundedMinor: Minor = Field(ge=0)
    currency: Currency = Field(min_length=3, max_length=3)


SCHEMAS: dict[str, type[_Payload]] = {
    E.PAYMENT_CAPTURED: PaymentCaptured,
    E.ESCROW_FUNDED: EscrowFunded,
    E.MILESTONE_ACCEPTED: MilestoneAccepted,
    E.ESCROW_RELEASED: EscrowReleased,
    E.ESCROW_REFUNDED: EscrowRefunded,
    E.DISPUTE_RESOLVED: DisputeResolved,
    E.ESCROW_RESOLUTION_EXECUTED: ResolutionExecuted,
}


def check(event_type: str, payload: dict) -> None:
    """Raise ValueError when a typed event's payload breaks its contract."""
    schema = SCHEMAS.get(event_type)
    if schema is None:
        return
    from pydantic import ValidationError

    try:
        schema.model_validate(payload)
    except ValidationError as e:
        raise ValueError(f"Payload of {event_type} breaks its contract: {e.errors(include_url=False)}") from e
