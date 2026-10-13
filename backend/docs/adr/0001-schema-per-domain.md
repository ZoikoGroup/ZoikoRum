# ADR-001: One database, one schema per domain

**Status:** Accepted (deviation from the architecture's database-per-domain target)  
**Date:** 2026-10-02

## Context

The architecture asks for a database per domain so that no domain can read or write another's data.

## Decision

One PostgreSQL cluster with a schema per domain (`identity`, `proposal`, `escrow`, ...). No foreign keys or joins across schemas; other domains are reached only through their `facade` module. `tests/test_architecture.py` enforces both rules.

## Consequences

Same ownership rules at a fraction of the running cost. Cross-domain reads cost an extra query instead of a join. Moving a schema to its own cluster later is a dump and restore plus a connection-string change.

## Alternatives considered

Database per domain from day one (more infrastructure to run and back up); one shared schema (ownership would erode).
