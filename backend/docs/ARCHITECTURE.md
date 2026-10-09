# Zoikorum Backend Architecture

Audience: the Zoikorum engineering team and the CTO office. This explains what was built from the
18 source documents, why it is shaped this way, where it intentionally differs from the
long-term target, and what still needs a business decision.

Companion documents: [BUILD_SPEC.md](BUILD_SPEC.md) (per-domain contracts), [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)
(generated table list), [CUSTOMER_DATA.md](CUSTOMER_DATA.md) (customer data vs. the documents) and the source docs in
[`docs/product/`](../../docs/product/README.md).

## Current checkout (2026-10-09)

See [CURRENT_STATUS.md](CURRENT_STATUS.md) for the merged implementation, migration head `f1360ce42a96` and test limitations. Messaging, change orders and Steps 12–18 have implementations; they are no longer deferred solely because they are absent from the original Steps 0–9 status table. Hosted Stripe/Persona and optional S3 adapter code also exists, but live integrations are unverified.

The dated audit tables below preserve earlier observations. In particular, the 2026-10-08 audit lists frontend work that did not arrive with the backend-only dev merge: quick view, shareable comparison, weekly hours, verification appeals, partial acceptance, taxonomy suggestions and retainer controls must be checked against the actual frontend before claiming completion.

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
| Payments provider | Regulated third party | `PaymentProvider` interface, development fake and configurable Stripe adapter (live flow unverified) | Confirm the partner (e.g. Stripe Connect or Adyen for Platforms). See open question Q1. |

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
| 5a Customer portal | Management designs for Buyer/Enterprise: Find, Saved (collections, compare ≤3), Organisation (profile, members, roles, billing contacts, audit CSV), Verification (shortlist status), Settings (profile, devices, notifications, privacy requests), Help; Requests/Proposals/Engagements/Payments/Messages laid out with empty states. Backend: `PATCH /v1/me`, sessions, data requests, notification preferences, billing contacts, collections, compare | Built. Pipeline screens fill in with Steps 6–8 |
| 6 Requests & proposals | Proposal domain: a buyer (Requester) sends one structured requirement to 1–3 chosen professionals (`group_id`), with optional budget, NDA and attachment fingerprints; drafts; professionals see NDA-protected details only after accepting the NDA (audited); decline with a structured reason; structured proposals (deliverables with acceptance criteria, milestones mapped to deliverables whose amounts make the total, timeline, assumptions/exclusions, validity); submit needs Tier B and a complete proposal; buyer comparison with deltas vs the request, revision requests, reject, accept (Idempotency, spend limit respected) → `PROPOSAL_ACCEPTED` with the full terms snapshot and `termsHash`; accepting one closes the rest of the group; expiry on a durable timer. Frontend: request wizard (5 steps), Requests/Proposals/request detail with comparison, professional Requests inbox and proposal builder, dashboard counts | Built. Organisation approval workflows (`REQUIRE_APPROVAL`) and messaging threads arrive with the policy and messaging domains |
| 7 Contracts & engagements | Contract domain: generated from `PROPOSAL_ACCEPTED` (idempotent per proposal; refuses terms whose hash does not match) with parties, scope, deliverables and acceptance criteria, milestone payment schedule, change-order and dispute clauses, NDA clause and platform standard terms; rendered document with SHA-256 (every read audited); signature deadline timer → `SIGNATURE_DEADLINE_ESCALATED`. Signing: buyer (Requester/Approver) first, professional countersigns; each needs step-up MFA, an Idempotency-Key and the exact `termsHash`; receipts in append-only `contract.signatures`; both signed → ACTIVE + `CONTRACT_ACTIVATED`. Milestones wait in PENDING_FUNDING until `ESCROW_FUNDED`, then submit (note + file fingerprints) → revision / accept → all accepted → COMPLETED. Professional capacity counts active contracts. Frontend: Engagements list and workspace (overview, agreement + signing, milestones, payments placeholder, activity) for both sides; dashboards and sidebar | Built. Change orders (versioned re-signing), dispute hooks and acceptance reminders are the next contract increment; funding arrives with escrow (Step 8) |
| 8 Escrow & payments | Escrow domain: account per contract on `CONTRACT_ACTIVATED` (allocation per milestone); buyer funding (Requester/Approver/Budget Owner, Idempotency, spend limit, no over-funding) → `ESCROW_FUNDING_REQUESTED`; `PAYMENT_CAPTURED` → balanced append-only double-entry ledger (BUYER_FUNDING/ESCROW_HOLD) → HELD → `ESCROW_FUNDED` (contract starts the milestone); `PAYMENT_FAILED` → back to unfunded; `MILESTONE_ACCEPTED` → release decision tree (idempotent per milestone, blocked while on hold) → ledger ESCROW_RELEASE + PLATFORM_FEE → `ESCROW_RELEASED`. No HTTP endpoint releases money; operators read only. Payments domain: provider adapter with FakeProvider (tokens only), charges, payout accounts (step-up, Tier B, restrictions clear; only last 4 digits stored), payouts (queued until an account exists), sequential buyer invoices. Frontend: fund dialog with breakdown and confirmation, engagement Payments tab (escrow, payments, ledger), customer Payments & Protection, professional Earnings, dashboard money cards | Built in test mode, including signed idempotent provider webhooks, chargebacks, expected payout dates and nightly reconciliation (see the Steps 0–9 re-audit below). A real regulated provider replaces `FakeProvider` behind the same adapter |
| 9 Disputes & mediation | Dispute domain: a party opens a case on funded, not-yet-accepted milestones (category immutable, summary ≤300, desired outcome, context ≤1000; no duplicate open case per milestone) → `DISPUTE_INITIATED`: escrow freezes the funds (ON_HOLD, `ESCROW_HOLD_APPLIED`) and the contract and milestones pause (DISPUTED). Evidence is append-only and fingerprinted (`dispute.evidence_items`), until both parties mark it complete or the evidence window ends (timer). Direct resolution: structured proposals (release / refund per milestone, each milestone fully allocated), accept or decline, escalation unlocked by a declined proposal; the window (5 business days) ends in mediation. Conduct and compliance cases skip direct resolution. Mediation: an operator assigns a mediator who is not a party; the mediator's recommendation binds only if both parties accept; otherwise the mediator proposes a platform decision that a different person with the Legal role must approve (four-eyes, step-up). `DISPUTE_RESOLVED` carries the decision package; escrow executes it exactly (release minus fee, refund, or back to held) with balanced ledger groups → `ESCROW_RESOLUTION_EXECUTED` → case ENFORCED → CLOSED; contract resumes, completes or terminates; termination refunds every remaining held milestone; payments returns refunds through the provider. Frontend: Raise-a-dispute dialog, dispute case page (frame, countdown, next step, evidence, proposals, mediation, decision, timeline), dispute lists for customers, professionals and staff | Built. Appeals, automated platform triggers, dispute messaging threads and trust-score effects come later |
| 10+ | Proposed next: messaging, change orders, appeals… | Not started |

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


### Step 6 decisions (2026-10-06)

| Topic | Decision |
|---|---|
| "Post a job / apply" | Not a job board (Homepage wireframe). "Post requirement" = a request to professionals the buyer chooses; professionals "apply" by sending a proposal from their Requests inbox |
| One requirement to several professionals | The RFP wireframe allows "Request Proposal for selected professional(s)". `POST /v1/proposal-requests` takes `professionalIds` (1–3, BUILD_SPEC had a single `professionalId`); one request row per professional sharing `group_id`. Accepting one proposal closes the others |
| Policy before the policy domain exists | Platform baseline only: restricted professionals cannot be engaged; Tier C cannot submit or be accepted; the accepting member's own spend limit applies. `PENDING_APPROVAL` exists in the state machine but is not used yet |
| One proposal per request | Revisions edit the same proposal (`revisionCount`, history in `revision_requests`); a rejected, withdrawn or expired proposal closes that professional's request |
| Total price | Always the sum of milestone amounts (a `total` sent by the client must match) |
| Contract defaults | Signature deadline 7 days and buyer review window 5 days (`ZK_SIGNATURE_DEADLINE_DAYS`, `ZK_ACCEPTANCE_WINDOW_DAYS`) until enterprise policy profiles set them. Governing law follows the Terms of Service unless a policy profile sets it |
| Platform fee | 10% (`ZK_PLATFORM_FEE_BPS=1000`, set in the original config). The product documents require a visible fee breakdown but do not state the rate: **management to confirm** |
| Payment provider | Development test mode (FakeProvider: `tok_fail` declines, account numbers ending 0000 fail payouts). A regulated PSP replaces it behind the same adapter; card and bank details are collected by the provider, never by Zoikorum |
| Dispute windows | Evidence window 3 days (`ZK_DISPUTE_EVIDENCE_DAYS`, **not stated in the documents: management to confirm**); direct resolution 5 business days (Dispute doc s.10). Accepted milestones cannot be disputed yet: the policy-defined challenge window is 0 until management sets one |
| Signing needs two-step verification | Both parties confirm with a fresh code (Architecture 11.4). Accounts without two-step verification are asked to turn it on before signing |
| Professional ↔ firm link | `PUT /v1/professionals/me/firm` links a profile to a firm the professional actively belongs to, or `null` for independent. Joining a firm (`FIRM_MEMBER_JOINED`) links an unlinked profile automatically; removal (`FIRM_MEMBER_REMOVED`) unlinks it. The public profile shows the firm's trading or registered name (hidden while the firm is suspended) |

### Steps 0–9 re-audit against the documents (2026-10-07)

Each product document was checked again against the code. Gaps that belong to Steps 0–9 were filled:

| Document | Gap filled |
|---|---|
| Onboarding s.6–7 | Password strength meter on sign-up; publish completion screen (tier reached, what you can do now, next steps) |
| Professional Dashboard | "Upcoming milestones" shows real contract milestones due within 14 days; request page shows service alignment with the professional's offerings |
| Public Profile | Engagement history from facades only (`contract.delivery_stats`, `proposal.response_stats`): completed engagements, on-time rate, median response time, "new to the platform"; expired credentials shown as "Expired"; conversion zone; out-of-area notice for the viewing buyer |
| Search & Discovery | `experience` filter (minimum years); `publishedAfter`; active filter pills with reset; saved searches (`marketplace.saved_searches`, `GET/POST /v1/saved/searches`, `POST /{id}/viewed`, `DELETE`) with "new since you last looked" counts |
| RFP flow | Request deliverables checklist (taxonomy and offering templates plus custom), dependencies, pricing preferences and payment cadence; deliverables and dependencies hidden until the NDA is accepted; jurisdiction conflict shown to both sides and blocks acceptance (`JURISDICTION_CONFLICT`); "Request again" pre-fills a new request; engagement record export (contract, escrow, ledger, disputes as JSON) |
| Payments & Escrow s.13/s.21 | Printable receipt per invoice (print or save as PDF); payments and invoices CSV export |
| Verification (Architecture 8.x, Trust & Safety) | Evidence documents are now stored, not just fingerprinted: PDF/JPG/PNG up to 10 MB, the file's own bytes must match the declared type and the browser's SHA-256 (`FINGERPRINT_MISMATCH`, `INVALID_FILE_TYPE`), kept in blob storage under `verification/{case}/{sha256}` (`evidence_items.storage_key`, `content_type`). `GET /v1/verification/evidence/{id}/file` lets the owner and compliance reviewers open it (no-store, sandboxed, every opening audited as `verification.evidence.viewed`). Records from before this change show "fingerprint only" |
| All other uploads (RFP flow, Payments & Escrow s.10, Dispute doc) | Request attachments, milestone deliverables and dispute evidence use the same shared upload kernel (`shared/uploads.py`): PDF, Word, Excel, CSV, JPG or PNG, 10 MB each and 25 MB per request, type checked against the file's bytes, fingerprint verified, stored content-addressed (`proposals/{group}/…`, `contracts/{contract}/{milestone}/…`, `disputes/{case}/…`; the JSONB file records gain `contentType` and `key`). Opening routes: `GET /v1/proposal-requests/{id}/attachments/{sha256}` (buyer organisation; the professional only after any NDA, `NDA_NOT_ACCEPTED`), `GET /v1/contracts/{id}/files/{sha256}` (parties and operators such as the mediator), `GET /v1/disputes/{id}/files/{sha256}` (parties, mediator, legal). Each opening is audited (`proposal.request.attachment.viewed`, `contract.deliverable.viewed`, `dispute.evidence.viewed`) |
| Engineering Handbook 15.1 / BUILD_SPEC: provider webhooks | `POST /v1/payments/webhooks/{provider}`: `Webhook-Signature: t=<unix>,v1=<HMAC-SHA256("<t>.<body>")>` with `ZK_WEBHOOK_SECRET`, refused when older than `ZK_WEBHOOK_TOLERANCE_SECONDS` (300); each provider event id stored once in `payments.webhook_events` (duplicates acknowledged, not re-applied). Handles charge succeeded/failed (async capture), `charge.dispute.created` (chargeback), payout paid/failed (a bank return re-opens the payout for retry), refund succeeded/failed |
| Payments & Escrow s.18: chargebacks | `PAYMENT_CHARGED_BACK` → escrow takes the reversed money out with a balanced `CHARGEBACK` ledger group: held (or dispute-frozen) milestones go back to unfunded and the contract moves them to `PENDING_FUNDING` ("no work without funding"); anything already released is booked to `PLATFORM_CHARGEBACK_LOSS` for Financial Ops to recover. The buyer sees "Reversed by your card issuer" |
| Professional Dashboard s.12, P&E s.14: expected settlement date | Payouts carry `expectedAt` (start + `ZK_PAYOUT_SETTLEMENT_BUSINESS_DAYS`, 2) and a plain-language `delayReason` (waiting for payout account, bank returned it, or later than expected); Earnings shows "Expected" and "Delayed" |
| Engineering Handbook 15.4: daily reconciliation | `payments.reconciliation_batches`: per UTC day and currency, escrow ledger (`escrow.facade.ledger_movements`) vs payments records vs the provider's report (when it has one): charges = BUYER_CLEARING debits, payouts = PRO_PAYABLE credits, refunds = BUYER_REFUND_PAYABLE credits, chargebacks = CHARGEBACK_REVERSAL credits. Runs at 01:00 UTC for the previous day (durable timer, re-arms itself), on demand for Financial Ops (`GET/POST /v1/payments/reconciliations`, Ops → Reconciliation) and via `python -m zoikorum.cli reconcile --day`. A mismatch emits `RECONCILIATION_MISMATCH` and an audit record (P0) |
| Engineering Handbook 21.4: circuit breakers | `shared/circuit.py`: after `ZK_PROVIDER_BREAKER_FAILURES` (5) consecutive technical errors the payment provider circuit opens for `ZK_PROVIDER_BREAKER_RESET_SECONDS` (30) and calls fail fast with 503 `PROVIDER_UNAVAILABLE`; event consumers are retried by the worker (the decision tree's "queue retry"). A declined card is a normal answer and never trips it |
| Payments & Escrow s.10 "start acceptance timer" | Submitting work arms two durable timers per submission: a reminder one day before the review window closes (`MILESTONE_ACCEPTANCE_REMINDER`) and the deadline (`MILESTONE_ACCEPTANCE_OVERDUE`). Timers are ignored once the buyer accepts, asks for a revision, a dispute pauses the milestone, or the work is resubmitted. Overdue work is flagged (`reviewOverdue`, next action) for both sides. Manual acceptance remains the default. The implemented policy engine can enable pinned, guarded auto-acceptance; asynchronous release still enforces policy and dispute holds. Notifications now consume reminder events. |

### Second re-audit (2026-10-08)

| Document | Gap filled |
|---|---|
| Finance & Accounting category s.5–8 | Grid / List view toggle; profile **quick view** (hover ~0.7s or "Quick view": summary, verified credentials, top specializations, engagement types, 3 deliverables, actions); "Compare: (n/3)"; **shareable comparison link** `/app/compare?ids=` (signed-in) with a governance row; **show partial matches** when few results (same search, other filters relaxed, unmet filters listed); "Browse all"; education cards with three short explainers; **"Jurisdiction-limited"** badge with one-click "Show eligible professionals" (search results now carry `servedJurisdictions` / `licensedJurisdictions`) |
| F&A category s.11.2 | Regional credential equivalency (`frontend/src/lib/equivalency.ts`): plain-language note with the nearest local qualification; "Recognised in your region" only for a verified credential issued in the buyer's country. Explanatory only (Homepage: no implied equivalence) |
| Professional Dashboard s.13 | Weekly availability slider (`professionals.weekly_hours`, 0–60), shown on the public profile |
| Onboarding s.20/s.22, RFP s.5/s.19 | Autosave within ~1s of a pause (profile basics, request wizard; per user, in this browser) with a resume prompt; budget range slider |
| Buyer Dashboard s.15 | Dashboard-scoped global search: engagements, requests and professionals with autocomplete and type filters (messages join with messaging) |
| Governance playbook s.11, Onboarding s.16 | **Verification appeals** (`verification.appeals`): the subject appeals a FAILED or REVOKED check once, within `ZK_VERIFICATION_APPEAL_DAYS` (14), adds evidence; a compliance officer who did not make the original decision decides once (step-up): OVERTURNED → VERIFIED, UPHELD → stands |
| Payments & Escrow s.18 | **Partial acceptance**: the buyer offers to accept submitted work for less with a reason; nothing moves unless the professional agrees; then that part is released (fee on it) and the rest refunded, balanced ledger, invoice for the released part. Declining, a revision or a dispute withdraws the offer |
| Payments & Escrow s.15, RFP s.11 | **Retainer cycles**: monthly-cycle generator in the proposal form (one milestone per cycle), cycle strip on the engagement, funding reminders `ZK_FUNDING_REMINDER_DAYS` (7) before each unfunded cycle (`MILESTONE_FUNDING_REMINDER`), buyer "Cancel remaining cycles" for unfunded cycles (escrow allocation → CANCELLED); not funding the next cycle pauses the work. Auto-funding needs a stored payment method from the live provider |
| Onboarding s.20 | **Duplicate accounts**: the same ID document (SHA-256) from two accounts raises `identity.duplicate_suspicions`; the person asks to merge or says it is not theirs; Platform Admin / T&S analyst decides (step-up): MERGED closes the duplicate (sessions revoked) and keeps the chosen account, NOT_DUPLICATE dismisses. Data is moved by support, never automatically |

### Taxonomy beyond Finance & Accounting, and "Can't find yours?" (2026-10-08)

| Topic | Decision |
|---|---|
| Categories | The documents describe a marketplace for governed professional services in general but detail only Finance & Accounting. Five **starter** categories were added next to it (Technology & Software Development, Legal Services, HR & People, Marketing & Growth, Management Consulting; 102 specializations in total, migration `935acaf8cfd4`). Legal specializations require credentials and are regulated. **Management to review** names and flags; admins can rename, extend or deprecate |
| Picker | The profile Services step searches all specializations (name, group, category) with a category filter; chosen items stay visible |
| "Can't find yours?" | `POST /v1/taxonomy/suggest` maps the professional's own words to up to 5 existing specializations and, if nothing fits, drafts a new one. Claude (`ZK_AI_PROVIDER=anthropic`, `ZK_ANTHROPIC_API_KEY`, `ZK_AI_MODEL`, default `claude-opus-5-5`; needs `pip install anthropic`) with structured output; any failure or no key falls back to keyword matching (`domains/ai/specializations.py`). Drafts are never live: `POST /v1/taxonomy/suggestions` stores a PENDING suggestion (max 3 per person), shown on the profile as "Custom (under review)" |
| Admin review | `GET /v1/admin/taxonomy/suggestions`, `POST …/{id}/decision` (Platform Admin): APPROVE creates the specialization (versioned taxonomy change), MERGE maps it to an existing one, REJECT needs a note. Approved/merged specializations are added to the professional's profile (`TAXONOMY_SUGGESTION_RESOLVED`). Frontend: Administration → Taxonomy |

Current gaps include authorised retainer auto-funding, messages in global search, saved buyers, enterprise federation/provisioning, privacy fulfilment, and production deployment/provider verification. Messaging, notifications, change orders, policies/approvals, enforcement, dispute appeals and scoped report exports now have implementations. See [current status](CURRENT_STATUS.md) for the limits of those implementations.

## 7. Running it

See `backend/README.md`.
