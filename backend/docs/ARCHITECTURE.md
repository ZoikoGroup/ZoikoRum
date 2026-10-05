# Zoikorum Backend Architecture

Audience: the Zoikorum engineering team and the CTO office. This explains what was built from the
18 source documents, why it is shaped this way, where it intentionally differs from the
long-term target, and what still needs a business decision.

Companion documents: [BUILD_SPEC.md](BUILD_SPEC.md) (per-domain contracts) and the source docs in
`Downloads/zoikorum/`.

## 1. What the documents ask for

| Source document | Backend obligations it creates |
|---|---|
| Engineering Backend Architecture | 20 bounded contexts, database per domain, outbox, idempotency, event envelope, policy-as-code, hash-chained audit, step-up auth, SLOs, roadmap waves |
| Backend Engineering Handbook | Aggregates own invariants, explicit state machines, CQRS projections, inbox/outbox, release decision tree, double-entry ledger, Problem Details errors, cursor pagination, optimistic concurrency, vertical-slice build order |
| Payments & Escrow | Milestone payment states, "no work without funding / no release without acceptance / no acceptance without authority", dispute freezes funds, retainers, enterprise release approvals, PDF/CSV/JSON exports |
| Dispute Resolution | 7 categories, 9-phase lifecycle, evidence hashing, direct-resolution window (5 business days), mediation, policy escalation, decision package, idempotent enforcement, sealed records |
| Enterprise Policy Profiles | 4 profile templates, eligibility/contract/escrow/approval/exception/audit sections, approval chain types, version lock for in-flight engagements, impact preview |
| Trust & Safety Charter, Ethics Code | Tiers A/B/C are system-enforced; time-bound credentials; no silent penalties; explainability ("Why am I seeing this?"); no pay-to-win ranking |
| Internal Governance Playbook | Enforcement levels 0–4, mandatory flow (signal → evidence → level → impact → notice → action → audit → review), 6-field notices, appeals by an independent reviewer, role separation |
| Regulator Assurance Pack, Investor/Board Brief | Evidence for each control (verification records, ledgers, approval logs, override logs), named human owner for every decision, board metrics |
| Professional Onboarding wireframe | Individual/Firm tracks, taxonomy-only specializations, verification checklist, conditional credential checks, jurisdiction eligibility, human review SLAs, 30/14/7-day expiry reminders, publish attestation |
| Professional Profile, Category (Finance & Accounting), Homepage | Public profile with verified-only credentials, faceted search, 7-group finance taxonomy, comparison (max 3), "why this result" |
| Request Proposal & Engagement flow (×2) | Structured request → proposal → comparison → agreement → signing → funding → active workspace, change orders with scope versioning, NDA gating, conflict detection |
| Buyer Dashboard, Professional Dashboard | Summary projections, pending-action queues, earnings, funds in protection |

## 2. Shape of the system

```
                         ┌──────────────────────── FastAPI app (one deployable) ───────────────────────┐
 Client ─► edge MW ─►    │ identity  buyer  firm  professional  marketplace  search  proposal  contract │
 (correlation id,        │ escrow  payments  verification  trust  policy  dispute  audit  messaging     │
  rate limit,            │ notification  ai  admin  analytics          (each: own Postgres schema)      │
  Problem Details)       └──────────────┬──────────────────────────────────────────────▲───────────────┘
                                        │ record_event() in the same TX                 │ @subscribe handlers
                                        ▼                                               │ (inbox-deduped)
                              platform.outbox ──► relay worker ──► in-process bus ──────┘
                                                   (Kafka adapter later)    │
                              platform.timers ──► timer worker (deadlines, expiries, SLAs, retries)
                              audit.audit_records ◄── every event, SHA-256 hash-chained, append-only
```

* **Modular monolith, strict boundaries.** 20 domain packages, 21 Postgres schemas (plus `platform`).
  A domain may only import another domain's `facade.py`; `tests/test_architecture.py` fails the
  build otherwise, and also rejects cross-schema foreign keys. This is the path the Architecture
  doc (§20.2) and Handbook (§27.2) recommend for a young team: extracting a domain later means
  swapping its facade for an HTTP/gRPC client and its in-process subscriptions for Kafka consumers.
  Domain code does not change.
* **Writes:** command → aggregate invariants → state change + `record_event` in one transaction.
* **Reads across domains:** facades (synchronous, authoritative) or local projections built from
  events (search documents, dashboards, identity links).
* **Workflows:** long-running processes (signature deadlines, acceptance windows, evidence windows,
  credential expiry, approval escalation, webhook retries) are event-driven process managers with
  durable timers in `platform.timers`. They survive restarts and are idempotent.

## 3. Cross-cutting guarantees, and where they live

| Guarantee (doc ref) | Implementation |
|---|---|
| Outbox, at-least-once (EP-03, H 21.1) | `shared/events.record_event`, `shared/relay.relay_once` |
| Consumer idempotency + DLQ (Arch 6.4) | `platform.inbox`, `platform.consumer_failures` (5 attempts, backoff, DEAD); financial events need FINANCIAL_OPS to replay |
| API idempotency (EP-04, H ch.12) | `shared/idempotency.py`; key row written in the same TX as the mutation |
| Immutable audit (EP-05, ADR-007) | `audit` domain consumes every event; SHA-256 chain; DB trigger blocks UPDATE/DELETE; chain re-validated hourly |
| Append-only evidence/ledgers | `shared/ddl.py` triggers on ledger, evidence, signatures, messages, policy evaluations |
| State machines (H ch.8) | `shared/state_machine.py`, asserted in each service |
| Money (H 4.3) | `shared/money.py` integer minor units; floats rejected |
| RBAC + ABAC, step-up (Arch 11.3–11.4) | `shared/auth.py` `Actor` (platform roles, org roles, professional, firm); `require_step_up()` needs MFA/passkey from the last 5 minutes |
| Problem Details, correlation IDs | `shared/http.py`; `X-Correlation-Id` flows into every event, audit record and log |
| Optimistic concurrency (H 18.4) | `Versioned` mixin → 409 VERSION_CONFLICT |
| Field-level encryption (Arch 8.2) | `shared/crypto.py` AES-256-GCM (KMS data keys in production) |
| Policy-as-code (EP-07) | `policy` domain: versioned profiles, rule evaluator, approvals, exceptions |
| AI governance (Arch ch.10) | `ai` domain: prompt registry with safety approval, inference log, offline fallback; no decision-making paths |

## 4. Decisions and deliberate deviations (ADR summary)

| ADR | Target in docs | What we built now | Why / migration path |
|---|---|---|---|
| ADR-001 Database per domain | Separate databases | One Postgres cluster, **schema per domain**, no cross-schema FKs/joins | Same ownership rules at MVP cost. Moving a schema to its own cluster is a dump/restore plus a connection-string change. |
| ADR-002 Kafka event bus | Managed Kafka + schema registry | **Transactional outbox + in-process bus**; envelope already matches Arch §6.2; topic names follow `zoikorum.{domain}.{aggregate}.{action}.v1` | No broker to run on day one. A Kafka adapter only replaces `relay.publish`; consumers keep using `deliver()`. |
| ADR-003 Temporal | Temporal workflows | **Durable timers + event-driven process managers** in Postgres | Covers every documented workflow with no new infrastructure. Revisit when workflows need complex compensation trees. **Needs CTO sign-off: this is the main departure from an accepted ADR.** |
| ADR-005 OpenSearch + vector | Hybrid BM25 + dense vectors | **Postgres full-text** projection with the documented ranking weights and explanations; vector retrieval behind an interface | Meets Wave 1–2 needs. OpenSearch can rebuild from events at any time. |
| ADR-008 Passkey-first | Passkeys, SSO, SCIM | Email+password (argon2), TOTP MFA, step-up, rotating refresh tokens with reuse detection | Passkeys, SAML/OIDC and SCIM are Wave 5 items. `AuthStrength.PASSKEY` already exists for step-up. |
| JWT signing | KMS-backed keys | HS256 shared secret | Switch to RS256/ES256 with KMS and a JWKS endpoint before any service is extracted. |
| Payments provider | Regulated third party | `PaymentProvider` interface + deterministic fake | Choose the partner (e.g. Stripe Connect or Adyen for Platforms). See open question Q1. |

## 5. Gaps and contradictions found in the documents (need owners)

1. **Payment partner and money-transmission model (Legal/Finance).** The docs say Zoikorum "does not act
   as a bank" and that funds are held by regulated partners. Which partner, which countries, and who is merchant of record?
2. **Escrow optional vs. "no work without funding".** The Growth & Advisory profile lists "escrow optional",
   but the Payments doc says no work starts without funding. The build treats every engagement as escrow-funded,
   and the profile flag is stored but not yet honoured. Product must decide.
3. **What Tier C can do.** The Homepage calls Tier C "Unverified (Discovery only)" and says it cannot use escrow.
   Onboarding says Tier C can "receive interest". The build lets Tier C publish and receive requests, but
   not submit proposals or contract.
4. **Engagement vs. contract status.** The dashboards show "Draft / Awaiting Signature / Active / In Review /
   Completed / Disputed". These map onto contract + milestone states and are exposed through the dashboard projection.
5. **Platform dispute decisions.** "Platform decision (if agreed)" needs legal terms that define when the platform
   may decide. The build requires a mediator plus a second LEGAL approver.
6. **Sanctions / restrictions screening and background-check providers** are unnamed. Fake providers sit behind interfaces.
7. **Tax** (VAT/GST on platform fees, invoices per jurisdiction). A `TaxCalculator` interface returns 0 today.
8. **Retainers and recurring cycles.** These are described in the Payments doc but not in the Engagement flow.
   Modelled as milestones today; recurring funding cycles are a follow-up.
9. **Accessibility target.** Some docs say WCAG 2.2 AAA and the category doc says AA. This is frontend-only, but procurement packs quote it.
10. **Data retention.** Retention is "policy-configured by evidence type and jurisdiction", but no periods are given.
    S3 Object Lock periods and GDPR/CCPA erasure workflows need concrete numbers from Legal.

## 6. Build status (step by step)

The platform is built in small, reviewed steps. Only what is listed as built exists in code.
The other domain folders contain only their `facade.py` interface contracts; they hold no logic yet.

| Step | Scope | Status |
|---|---|---|
| 0 Foundation | Shared kernel (outbox/inbox, idempotency, timers, errors, money, auth), audit ledger, migrations | Built |
| 1 Role-based login | Sign-up by account type (Buyer, Professional, Firm, Enterprise), one login for all roles, dashboard routing, role guards, staff roles with mandatory MFA, step-up, password reset, admin bootstrap CLI, frontend screens | Built |
| 2 Organizations, firms & team roles | Buyer domain (Individual/Enterprise organizations, members, Org roles: Org Admin, Requester, Approver, Budget Owner, Legal Reviewer, Exception Authority; spend limits; business units; cost centers; email-bound invitations) and Firm domain (firm profile with optimistic concurrency, Firm Admin / Member / Authorized Representative, invitations); identity derives Enterprise/Firm workspaces from memberships; frontend team, structure, firm and invitation screens | Built |
| 3 Professional profile & taxonomy | Marketplace taxonomy (Finance & Accounting: 7 groups, 43 specializations, credential/regulated flags; seeded by migration; admin add/edit/deprecate with taxonomy versioning) and Professional domain (one profile per account, optional firm link, profile basics with optimistic concurrency, 1 primary + ≤5 secondary specializations, jurisdictions with cross-border acknowledgement, availability/capacity, credential claims shown as "Self-reported" until verified, offerings DRAFT/ACTIVE/PAUSED, readiness checklist, publish with copy rules + attestation, public profile) | Built (backend + frontend). Reactions to contract and enforcement events arrive with those domains |
| 4 Verification & trust tiers | Verification domain (cases for identity, credentials, jurisdiction, insurance, sanctions screening and firm registration; provider adapter with a deterministic fake; append-only evidence metadata + SHA-256; Compliance Officer review queue with step-up MFA and no self-review; 30/14/7-day expiry reminders and expiry on durable timers; credential claims and firm status follow outcomes) and Trust domain (deterministic Tier A/B/C rules, five verification dimensions, 0-100 score with plain-language reasons, tier history and signals; adverse events downgrade immediately; risk flags never change the tier); frontend verification, firm verification and review-queue screens; real tiers on dashboards and public profiles | Built. Secure document storage (blob uploads) and a real KYC/sanctions provider are still open decisions |
| 5 Search & discovery | Search projection `search.professional_documents` built only from events (profile, offerings, availability, jurisdictions, trust, verification, enforcement) through facades; Postgres full-text (name/headline A, specializations B, bio/offerings/verified credentials C); filters (specialization any/all, tier, verified dimensions, engagement, delivery, availability, pricing, credential, jurisdiction), 7 sorts, facets; ranking with the Architecture 9.4 weights and a plain-language "why this result" (contract, review, response and policy signals score 0 until those domains exist); SEARCH_PERFORMED / SEARCH_ZERO_RESULT; `count_eligible` for policy impact previews; admin and CLI reindex. Frontend: public Browse page, dashboard "Verified professionals", and one dashboard design for every role | Built. Buyer-organization policy filtering arrives with the policy domain |
| 6+ | Proposed next: proposals (request → proposal → compare → accept), then contracts, escrow… | Not started |

## 6a. Product decisions taken (2026-10-05, after the documentation audit)

| Topic | Decision |
|---|---|
| Engagement type "Fractional" and pricing "Quote on request" | Kept (Onboarding doc s.9 lists them; the Professional Dashboard doc's shorter list is treated as examples) |
| Profile photo | Required to publish (Onboarding s.7). Stored through `shared/storage.py` (local disk in development, S3 in production) |
| Tier names | Homepage wireframe wording: "Fully Verified Professional", "Verified Identity", "Unverified (Discovery Only)" |
| Step-up MFA before submitting verification evidence (Architecture 11.4) | Not enforced yet (BUILD_SPEC omits it; it would force every professional to enrol an authenticator first). Can be enabled later |
| Offering editor | Five-step wizard with per-step saving (Professional Dashboard s.6) |
| Tier B | Requires identity VERIFIED **and** restrictions screening CLEAR |
| Verification | VERIFIED needs at least one evidence item (except list-based screening); a provider FAIL goes to human review |
| Public trust | No raw score; screening shown only when clear; licences marked verified / self-reported |

## 7. Running it

See `backend/README.md`.
