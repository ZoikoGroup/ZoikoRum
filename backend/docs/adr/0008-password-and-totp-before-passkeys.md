# ADR-008: Password and TOTP now; passkeys, SSO and SCIM later

**Status:** Accepted (deviation from passkey-first)  
**Date:** 2026-10-02

## Context

The architecture is passkey-first with enterprise SSO and SCIM provisioning.

## Decision

Email and password (argon2), TOTP two-step with recovery codes, step-up for sensitive actions, rotating refresh tokens with reuse detection, separate staff sign-in.

## Consequences

Works for every customer today. Enterprises that require SSO cannot onboard yet; passkeys, SAML/OIDC and SCIM are Wave 5. `AuthStrength.PASSKEY` already exists for step-up.

## Alternatives considered

Building passkeys and SSO before launch (delays every other journey).
