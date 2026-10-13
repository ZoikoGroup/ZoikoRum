# ADR-009: HS256 access tokens until a service is extracted

**Status:** Accepted  
**Date:** 2026-10-02

## Context

Access tokens are signed. The target is KMS-backed asymmetric keys with a JWKS endpoint.

## Decision

HS256 with a long random shared secret (`ZK_JWT_SECRET`), refused at start-up when it is a development value.

## Consequences

Only the monolith verifies tokens, so a shared secret is enough. Before any service is extracted: switch to RS256 or ES256 in KMS and publish JWKS.

## Alternatives considered

Asymmetric keys now (key management with no second verifier).
