# ADR-003: Durable database timers instead of Temporal

**Status:** Proposed: **needs CTO sign-off** (departs from an accepted architecture ADR)  
**Date:** 2026-10-02

## Context

Contract signing, funding, acceptance windows, dispute phases and expiries are long-running. The architecture chose Temporal.

## Decision

Durable timers in `platform.timers` (fire at most once, idempotent per business key, retried with backoff) plus event-driven process managers in each domain. Every documented workflow runs on them.

## Consequences

No workflow cluster to run; workflow state lives next to the business data and shares its backups. Complex compensation trees would be harder to express; revisit when one appears.

## Alternatives considered

Temporal (better tooling for long workflows, another cluster to operate); cron jobs (no per-object state, double runs).
