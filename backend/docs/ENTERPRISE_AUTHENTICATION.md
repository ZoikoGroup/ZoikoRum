# Enterprise authentication

Microsoft Entra ID is the default identity provider. Authentication stays in the identity domain; buyer membership changes use domain events and owning-domain handlers.

## OIDC and provisioning

Configure `ZK_ENTRA_TENANT_ID`, `ZK_ENTRA_CLIENT_ID`, `ZK_ENTRA_CLIENT_SECRET`, `ZK_ENTERPRISE_ORGANIZATION_ID` and a random `ZK_SCIM_BEARER_TOKEN` of at least 32 characters. The organisation must exist, be active, and have type ENTERPRISE. Secrets remain server-side.

Register the exact redirect URI `${ZK_FRONTEND_URL}/sso/callback`. The backend uses authorization code, PKCE S256, nonce, tenant-specific issuer, RS256 signing keys, audience and expiry validation. User authentication resolves the signed Entra object ID to an explicitly provisioned account. It never links accounts merely because their emails match.

Entra provisioning base URL: `${ZK_PUBLIC_API_URL}/v1/scim/v2`. Set the provisioning bearer token and map Entra object ID to `externalId`, mail/UPN to `userName`, display name to `displayName`, and account enabled to `active`. Supported operations are user creation, userName equality filtering, retrieval, replacement, active/displayName patches and deactivation. Unsupported attributes/operations are rejected rather than reported as successful. Provisioned users start as Requesters; additional authority is assigned through the existing organisation role workflow.

Existing ZoikoID email collisions return `ACCOUNT_LINK_REQUIRED` and require a verified linking process; they are not silently merged. Deactivation revokes sessions in the same transaction and updates membership through the outbox. Reprovisioning never restores previously revoked sessions.

## SAML

Configure `ZK_PUBLIC_API_URL`, `ZK_SAML_SP_ENTITY_ID`, `ZK_SAML_IDP_SSO_URL`, `ZK_SAML_IDP_CERTIFICATE`, `ZK_SAML_SP_CERTIFICATE` and `ZK_SAML_SP_PRIVATE_KEY`, together with the Entra tenant and enterprise organisation mapping. Use HTTPS in production. PEM values in environment files must be quoted correctly or supplied by the deployment secret manager.

SP metadata: `/v1/auth/saml/metadata`. ACS: `/v1/auth/saml/acs`. Configure Entra to sign both the response and assertion using SHA-256 and include `http://schemas.microsoft.com/identity/claims/objectidentifier`. Strict toolkit validation checks signatures, issuer, audience, destination, request correlation and validity. Unsolicited assertions are not accepted. A browser-bound, one-use handoff completes sign-in; assertion content never becomes an unvalidated account profile.

OIDC/SAML sessions start with OAUTH strength. Staff and organisation-admin sign-ins must complete local strong verification before privileged access; unsigned or ambiguous IdP MFA claims never grant elevated authority.

## Passkeys

Set `ZK_PASSKEY_RP_ID` to the frontend relying-party domain and `ZK_PASSKEY_ORIGIN` to its exact HTTPS origin (localhost HTTP is for development). Passkeys require user verification and discoverable credentials. Server challenges expire after five minutes and cannot be replayed or moved between authenticated sessions. Additional enrolment and removal require fresh verification. Sign-in and the shared step-up dialog support passkeys; passwords cannot bypass an enrolled passkey-only account.

## Validation

Tests use real signed WebAuthn assertions, signed SAML responses/assertions, and signed OIDC tokens with mocked provider transport. They verify ownership, replay, browser binding and immediate deprovisioning. Deployment still needs a live Entra tenant, certificate rotation checks and supported-browser/device testing.
