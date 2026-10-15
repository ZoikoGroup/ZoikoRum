"""Typed payloads of money and dispute events."""

from __future__ import annotations

import uuid

import pytest

from zoikorum.shared.event_catalog import E
from zoikorum.shared.event_schemas import check


def test_a_release_without_its_amounts_breaks_the_contract():
    good = {"escrowAccountId": uuid.uuid4(), "contractId": uuid.uuid4(), "milestoneId": uuid.uuid4(), "professionalId": uuid.uuid4(),
            "grossMinor": 1000, "feeMinor": 100, "netMinor": 900, "currency": "USD", "releaseId": uuid.uuid4(), "extra": "allowed"}
    check(E.ESCROW_RELEASED, {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in good.items()})
    with pytest.raises(ValueError, match="netMinor"):
        check(E.ESCROW_RELEASED, {k: v for k, v in good.items() if k != "netMinor"})
    with pytest.raises(ValueError, match="decisionPath"):
        check(E.DISPUTE_RESOLVED, {"disputeId": str(uuid.uuid4()), "contractId": str(uuid.uuid4()), "outcome": "FULL_RELEASE",
                                   "decisionPath": "COIN_TOSS", "allocations": [], "currency": "USD"})
    check(E.PROFILE_UPDATED, {"anything": 1})  # untyped events are not checked
