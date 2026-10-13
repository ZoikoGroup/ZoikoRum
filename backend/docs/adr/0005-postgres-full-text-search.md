# ADR-005: PostgreSQL full-text search instead of OpenSearch with vectors

**Status:** Accepted for Waves 1-2  
**Date:** 2026-10-03

## Context

Buyers search professionals by text, filters and trust. The target is hybrid BM25 plus dense vectors in OpenSearch.

## Decision

A search projection built from events, PostgreSQL full-text ranking with the documented weights, and a plain-language reason per result. Vector retrieval sits behind an interface.

## Consequences

Meets current volumes with no extra service. The projection can be rebuilt into OpenSearch from events at any time.

## Alternatives considered

OpenSearch now (another cluster before the catalogue needs it).
