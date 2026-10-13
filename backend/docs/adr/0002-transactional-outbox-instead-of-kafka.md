# ADR-002: Transactional outbox and in-process bus instead of Kafka

**Status:** Accepted (deviation from the Kafka target)  
**Date:** 2026-10-02

## Context

Domains communicate through events. The architecture targets managed Kafka with a schema registry.

## Decision

Events are written to `platform.outbox` in the same transaction as the state change; the worker relays them in commit order to in-process consumers, with an inbox per consumer (exactly-once effect), retries with jitter and a dead-letter queue (`shared/relay.py`). Envelopes and topic names already follow the Kafka conventions (`zoikorum.{domain}.{aggregate}.{action}.v1`).

## Consequences

No broker to operate on day one; no event is lost once the database commits. A Kafka adapter replaces only `relay.publish`. Throughput is bounded by one database.

## Alternatives considered

Kafka now (operational load before there is traffic); direct calls between domains (coupling, lost events on failure).
