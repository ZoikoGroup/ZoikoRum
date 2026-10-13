# ADR-011: Prometheus metrics, optional OpenTelemetry tracing

**Status:** Accepted  
**Date:** 2026-10-13

## Context

The handbook requires logs, metrics and traces, and the SLOs (search p99 under 300 ms, proposal changes p99 under 500 ms, zero unresolved reconciliation mismatches) need measurements.

## Decision

`GET /metrics` in Prometheus format behind a bearer token (`ZK_METRICS_TOKEN`): request latency per route template, AI calls, worker backlog, dead letters, circuit breakers, reconciliation. Web processes add up their counters through `PROMETHEUS_MULTIPROC_DIR`. Tracing is OpenTelemetry over OTLP, switched on by `ZK_TRACING_ENDPOINT` with the `tracing` extra; spans carry the correlation id and never query strings.

## Consequences

Works with any Prometheus- and OTLP-compatible stack. Database-derived gauges are identical from every process. The SQLAlchemy instrumentation's declared range ends below SQLAlchemy 2.1, so its version check is skipped (verified by a smoke test).

## Alternatives considered

A vendor agent (lock-in); metrics in logs only (no alerting on rates).
