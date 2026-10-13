# Architecture Decision Records

One file per significant decision (Engineering Handbook 28.3). Where a record departs from one of the architecture
document's ADRs it keeps that number. For a new decision, copy a file, take the next number and add it here.

| ADR | Decision | Status |
|---|---|---|
| [ADR-001](0001-schema-per-domain.md) | One database, one schema per domain | Accepted |
| [ADR-002](0002-transactional-outbox-instead-of-kafka.md) | Transactional outbox and in-process bus instead of Kafka | Accepted |
| [ADR-003](0003-durable-timers-instead-of-temporal.md) | Durable database timers instead of Temporal | Proposed: **needs CTO sign-off** |
| [ADR-005](0005-postgres-full-text-search.md) | PostgreSQL full-text search instead of OpenSearch with vectors | Accepted for Waves 1-2 |
| [ADR-008](0008-password-and-totp-before-passkeys.md) | Password and TOTP now; passkeys, SSO and SCIM later | Accepted |
| [ADR-009](0009-hs256-jwt-until-services-are-extracted.md) | HS256 access tokens until a service is extracted | Accepted |
| [ADR-010](0010-payment-provider-behind-an-adapter.md) | Payments behind a provider adapter | Accepted |
| [ADR-011](0011-prometheus-metrics-and-optional-tracing.md) | Prometheus metrics, optional OpenTelemetry tracing | Accepted |
| [ADR-012](0012-built-in-ai-prompts-registered-in-code.md) | Built-in AI prompts registered in code | Accepted |
