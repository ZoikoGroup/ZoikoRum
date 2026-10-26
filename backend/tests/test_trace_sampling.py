"""Trace sampling (shared/observability.py): parent-based ratio sampling, with money and legal routes always traced."""

from __future__ import annotations

import pytest

from zoikorum.shared import observability


@pytest.mark.unit
def test_route_matching():
    assert observability.route_of("POST /v1/escrow/{account_id}/fund", {}) == "/v1/escrow/{account_id}/fund"
    assert observability.route_of("GET", {"url.path": "/v1/payments/x?y=1"}) == "/v1/payments/x"
    assert observability.always_sampled("/v1/escrow/1/fund", ["/v1/escrow"])
    assert observability.always_sampled("/v1/escrow", ["/v1/escrow"])
    assert not observability.always_sampled("/v1/escrowed", ["/v1/escrow"])


@pytest.mark.unit
def test_sampler_overrides_ratio_for_critical_routes():
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace.sampling import Decision

    sampler = observability.make_sampler(0.0, ["/v1/payments", "/v1/disputes"])
    keep = sampler.should_sample(None, 123, "POST /v1/payments/webhooks/stripe", attributes={"http.target": "/v1/payments/webhooks/stripe"})
    drop = sampler.should_sample(None, 123, "GET /v1/search/professionals", attributes={"http.target": "/v1/search/professionals"})
    assert keep.decision == Decision.RECORD_AND_SAMPLE and drop.decision == Decision.DROP
    assert "RouteOverride" in sampler.get_description()
