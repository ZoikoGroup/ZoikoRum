# Customer (buyer) data: what we store and why

Audience: the Zoikorum engineering and product team. "Customer" means the buying side: individual buyers,
business and enterprise organizations, and their team members. Sources are the product documents in
[`docs/product/`](../../docs/product/README.md); the live column list is in [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

Short answer: the core customer data the documents require is stored today (account, organization, team roles
and spend limits, business units, cost centers, consents, audit). Engagement, payment, policy and safety records are also stored by their owning domains. Remaining identity/buyer gaps are listed in §3; see [current implementation status](CURRENT_STATUS.md) for validation limits.

## 1. Stored today

| Area | What | Where |
|---|---|---|
| Account | Email, email confirmation, password hash (argon2), display name, country, account roles, staff roles, MFA secret (encrypted), lockout counters | `identity.identities` |
| Sessions | Rotating refresh tokens, auth strength (password / MFA), expiry, revocation | `identity.sessions` |
| Consents | Terms / privacy / marketing acceptance with document version and time | `identity.consent_records` |
| Organization | Name, type (Individual / Business / Enterprise), country, status, business context | `buyer.organizations` |
| Team | Members, roles (Org Admin, Requester, Approver, Budget Owner, Legal Reviewer, Exception Authority), approval spend limit | `buyer.members` |
| Invitations | Email-bound invitations with roles, expiry, status | `buyer.invitations` |
| Structure | Business units (hierarchy), cost centers with quarterly budget | `buyer.business_units`, `buyer.cost_centers` |
| Shortlist | Saved professionals | `marketplace.saved_professionals` |
| Audit | Every action: actor, action, object, time, policy version, evidence hash; hash-chained and append-only | `audit.audit_records`, `audit.export_jobs` |

## 2. Commercial data now stored

| Data | Document | Owning domain |
|---|---|---|
| Proposal requests: service, engagement type, objective, details, start date, duration, budget, delivery mode, NDA, up to 3 attachments | Request Proposal & Engagement Flow §6 | Proposals |
| Proposal decisions (accept, decline with reason, revision requests) | same §9 | Proposals |
| Contracts, parties, signatures (terms hash, receipts), milestones, change orders | same §10, §14 | Contracts |
| Escrow funding, holds, releases with approver, refunds, ledger | Payments & Escrow §7, §13, §21 | Escrow |
| Payment method (provider **token only**), invoices (sequential number, gross/fee/net, tax) | Payments & Escrow; Architecture (Payments) | Payments |
| Approvals, policy profiles, exceptions and policy retention configuration (not a completed retention executor) | Enterprise Policy Profiles | Policy |
| Disputes and evidence | Dispute Resolution | Disputes |

Encrypted phone storage (`identity.identities.phone_enc`), billing contacts (`buyer.billing_contacts`), privacy-request intake (`identity.data_requests`) and duplicate-account suspicion records (`identity.duplicate_suspicions`) also exist. Intake/status fields alone do not establish completed privacy handling.

## 3. Remaining work (proposed)

| Proposed | Why | Document |
|---|---|---|

| `identity.consent_records.withdrawn_at` (+ optional IP / user agent) | Consents can be withdrawn; evidence of consent | Architecture (Identity); Ethics §10 |
| Privacy-request fulfilment and export/erasure execution | `identity.data_requests` already records ACCESS/ERASURE intake; completed handling and legal retention enforcement remain gaps | Regulator Assurance §9; Ethics §10 |
| `identity.mfa_devices` / passkeys; `identity.identity_providers` (SSO, SCIM) | Passkey-first, enterprise SSO and provisioning | Architecture §11.2 (planned for a later wave) |
| `buyer.organizations.organization_tier` | OrganizationTier value object | Architecture (Buyer) |
| `buyer.member_delegations` (delegator, delegate, roles, limit, starts/ends, revoked) | Time-bound delegation of authority, logged | Homepage §4.2 |
| `buyer.business_units.status`, `merged_into_id` | Handling merged business units | Enterprise Policy §18 |
| `buyer.cost_center_spend` (projection: period, committed, released) | Enforce "cannot exceed quarterly allocation" | Architecture §13.2 |
| Saved-search alert delivery | `marketplace.saved_searches` already stores queries and supports new-result counts; scheduled alert delivery remains unverified | Buyer Dashboard §13 |

**Product decision, not required by the documents:** buyer legal name, registration number, tax/VAT ID and
billing address. The documents only imply them (contract "parties", invoices and tax). Billing contact storage exists, but required legal identifiers and jurisdiction-specific tax/invoice rules still need product confirmation.

## 4. Rules for sensitive data (from the documents)

- **Card data is never stored**: payment methods are provider tokens only. Payment data lives in an isolated store
  with its own keys; operators cannot write to it.
- **Personal data**: field-level encryption for sensitive attributes (including the MFA secret and stored phone; tax identifiers require an agreed schema),
  encryption in transit and at rest, data minimisation and purpose limitation.
- **Retention**: configured per evidence type, jurisdiction and enterprise policy; audit logs are immutable.
- **Access**: role- and attribute-based (organization, contract party, authority level, sensitivity). Exports are
  role-restricted. Professionals see sensitive request details only after accepting an NDA.
- **Step-up authentication** for contract signing, escrow release, payment-method changes and large approvals.
- **Federated (SSO) accounts** cannot change their email without the identity provider reconfirming it.
- **Data residency** is not specified in any document: a decision is needed before production.
