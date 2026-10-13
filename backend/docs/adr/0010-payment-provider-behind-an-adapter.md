# ADR-010: Payments behind a provider adapter

**Status:** Accepted; **partner still to be chosen** (open question Q1)  
**Date:** 2026-10-04

## Context

Money is held and released by a regulated partner; the platform must not claim to hold funds itself.

## Decision

`PaymentProvider` interface with a development fake and a configurable Stripe adapter (hosted Checkout, Connect payouts, signed webhooks), behind a circuit breaker. The escrow ledger is ours and is reconciled daily against the partner's report.

## Consequences

The partner can change without touching escrow logic. The live Stripe flow is unverified until real keys and a signed agreement exist.

## Alternatives considered

Building directly on one provider's SDK (lock-in, hard to test).
