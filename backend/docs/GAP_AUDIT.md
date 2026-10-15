# Gap audit against the product documents (2026-10-14)

Every concrete requirement in the 18 documents in `docs/product/` (plus `BUILD_SPEC.md` and deployment readiness) was
checked against the code, not against earlier status files. Each requirement is **done**, **partly done**, **missing**,
or **not code** (an account, contract, licence, decision or human process that code cannot deliver).

**Built = (done + half of partly done) ÷ (all requirements − not code).** Sizes: S under half a day, M 1–2 days, L 3+ days.

## Summary

| Area (documents) | Requirements | Done | Partly | Missing | Not code | Built |
|---|---|---|---|---|---|---|
| Engineering handbook + backend architecture | 112 | 61 | 20 | 20 | 11 | 70% |
| Buyer dashboard, request for proposal, request → engagement flow | 70 | 35 | 21 | 10 | 4 | 69% |
| Professional profile, onboarding & verification, dashboard, Finance & Accounting category | 101 | 61 | 22 | 14 | 4 | 74% |
| Payments & escrow, dispute resolution | 81 | 48 | 16 | 12 | 5 | 74% |
| Enterprise policy profiles, regulator assurance | 64 | 38 | 16 | 6 | 4 | 77% |
| Trust & safety charter, ethics code, governance playbook, board brief | 52 | 27 | 10 | 8 | 7 | 71% |
| Production deployment on Google Cloud | 30 | 11 | 11 | 4 | 4 | 63% |
| **Total** | **510** | **281** | **116** | **74** | **39** | **72%** |

The main flow (sign-up, verification, search, request, proposal, contract, signing, escrow, release, invoice, payout,
disputes, appeals, policies and approvals, audit) works end to end. What is left is mostly hardening for production,
staff operations screens, enterprise extras and reporting.

## A. Before real customers and real money (launch blockers): all done 2026-10-14

| # | Gap | Area | Size | Status |
|---|---|---|---|---|
| A1 | Authenticator codes can be reused within their 90-second window (RFC 6238 §5.2) | Security | S | Fixed 2026-10-14 |
| A2 | Production starts with test settings (local files, fake payments, fake verification, console email, default database URL, no passkey domain when the staff domain differs) | Deploy | S | Done: production refuses to start; check-config lists what is missing |
| A3 | Behind the Google load balancer every request looks like it comes from the balancer: rate limits and the IP recorded with signatures are wrong; nginx overwrites the https scheme | Deploy | M | Done: nginx trusts only Google's load balancer ranges |
| A4 | The AI document check calls the model (up to 30 s) inside a database transaction | Verification | M | Done: model call before the transaction (`prepare` step) |
| A5 | Parties cannot end a contract (no terminate command); offboarding a professional does not wind down their contracts, escrow and payouts | Contracts | M | Done: end now / by agreement / lapse / withdraw; offboarding ends open engagements |
| A6 | Uploaded files are not virus-scanned | Files | M | Done: ClamAV before storing; fails closed |
| A7 | No alert rules (metrics exist, nobody is paged), no runbooks; logs use `level`/`msg` so Cloud Logging shows no severity; no log rotation | Operations | M | Done: 13 alert rules, RUNBOOKS.md, Cloud Logging format, rotation |
| A8 | The refresh token is kept in browser storage (an XSS bug could steal it); should be an httpOnly cookie | Security | M | Done: HttpOnly SameSite=Strict cookie |
| A9 | Field encryption uses one app key that falls back to the JWT secret; no Cloud KMS, no rotation | Security | M | Done: KMS-wrapped data keys, rotation command |
| A10 | About three-quarters of changing requests ignore Idempotency-Key, including the payout account and onboarding | API | S | Done: every change honours Idempotency-Key |
| A11 | No staff worklist for failed payouts, failed refunds and chargeback losses; buyers cannot see their refunds | Money | M | Done: Money Problems page; buyer Refunds tab |
| A12 | Users cannot report a profile, person, review or conduct problem | Trust & safety | M | Done: Report buttons, confidential option, retaliation flag |
| A13 | Buyers are not told when their professional is suspended or loses a credential | Trust & safety | M | Done: buyers on open engagements are told |
| A14 | No way to ask for help: the Help page says support cases are not available | Support | M | Done: help requests, Support Agent role, error links |
| A15 | Invoice tax is always 0 (code waits for the tax-rules decision) | Money | M | Done in code: tax-inclusive rules by country (rates: finance) |
| A16 | CI runs only on `main` and PRs; no container image scan; no release job; secrets in a file on the server instead of Secret Manager; no TLS / load-balancer config in the repo | Deploy | M | Done: CI on team branches, image scan, SBOM, release workflow, Secret Manager |
| A17 | The audit table is protected by triggers only; the database role can still UPDATE/DELETE | Audit | S | Done: restricted app user, cli db-grants |
| A18 | Docs still say S3/AWS and "passkeys not built"; the deployment guide leaves out the staff app, the Stripe webhook address and the passkey domain | Docs | S | Done |
| A19 | Third-party identity "approved" verifies with no person involved (ethics code requires human oversight; at least sampling) | Verification | S | Done: sampled second look (ZK_VERIFICATION_SECOND_LOOK_PCT) |

## B. Product completeness (what the documents describe that users would notice)

Progress: 21 of 34 groups done, 1 partly done (2026-10-15). Each done item has tests in `backend/tests/`.

**Buyers and engagements**
- B1 Guided "fund and activate" step after signing, with the approver named, a retry/other-method/support path, and an "Engagement activated" screen (M) — **Done 2026-10-15**
- B2 Engagement workspace as the single record: messages and files tabs, activity from the audit log, per-engagement evidence pack (PDF/CSV/JSON with attestations) (M) — **Done 2026-10-15**
- B3 Response deadline on requests and reminders when no proposal arrives (M) — **Done 2026-10-15**
- B4 Request wizard: at least one deliverable required, inline field errors, "Need help?", custom deliverables flagged, signed-out request kept until sign-in (S each) — **Done 2026-10-15**
- B5 Proposals: "Ask a question" per proposal, structured decline reason, best-match highlight and "why this matches", alternatives when a tier blocks acceptance (S each) — **Done 2026-10-15**
- B6 Agreement: change order before signing; separate sections for standard terms, data handling, governing law (M + S) — **Done 2026-10-15**
- B7 Dashboard: Payments & Contracts and Messages & Activity modules, progress bars and actions on the engagements table, enterprise controls panel, Saved Professionals card (M) — **Done 2026-10-15**
- B8 Alerts when a saved professional's availability changes and when a saved search has new matches (M) — **Done 2026-10-15**

**Professionals**
- B9 Enterprise readiness: designation, apply flow, security attestation, Enterprise Signals on the profile, enterprise filter, two-step required (L)
- B10 Finance & Accounting category page with "Post your requirement" and the enterprise pathway (M) — **Done 2026-10-15**
- B11 Regulated professions need Tier A to be discoverable beyond a preview; background check self-service with consent; firm beneficial-ownership declaration; "can handle regulated data" (S–M) — **Done 2026-10-15**
- B12 Contact a professional before a request (new message context) (M) — **Done 2026-10-15**
- B13 New-device sign-in alerts; tier-upgrade nudges when blocked by a buyer policy (S each) — **Done 2026-10-15**
- B14 Profile: tier tooltips and verification report, full breadcrumb with structured data, "under review" state, listing-view tracking (S–M)
- B15 Onboarding: controlled role-title list, "why we ask this", autosave on every step, 7-step shell with Save & Exit (S–M)
- B16 Search: multi-select specializations with "match all", advanced filters (credentials, industry, cross-border, budget), autocomplete and recent searches, caching (M)
- B17 Own performance insights (acceptance rate, timeliness, dispute frequency) (M) — **Done 2026-10-15**

**Payments and disputes**
- B18 Retainer pause; release ID shown on "Funds released"; payment frame (authority, what happens next) (S each) — **Done 2026-10-15**
- B19 Enterprise payments dashboard (exposure by vendor, release timelines) and bulk funding (M each)
- B20 Disputes: import message logs as evidence, save as draft, request clarification, timeline extension moves the due date, link account-restriction outcomes, linked artifacts on the timeline, 24-hour cooldown (S each) — **Done 2026-10-15**
- B21 Enterprise dispute controls (mandatory mediation thresholds, escalation authority, legal-review triggers), enterprise escalation path, external arbitration referral (M) — **Done 2026-10-15**
- B22 Per-case dispute record export; retention rules by policy and jurisdiction (M) — **Partly done 2026-10-15**: case record export (PDF/JSON with fingerprint) built; retention rules still open
- B23 Bad-faith dispute detection (M) — **Done 2026-10-15**

**Enterprise policies**
- B24 Structured policy builder instead of JSON boxes: risk badge, "where this applies", conflict checks, review-and-activate checklist (M)
- B25 Live policy state on engagements; blocked actions disabled up front; exception request from the blocked action; emergency exception path (S–M)
- B26 Policy dashboard and KPIs (usage, exception rate, approval latency, spend leakage prevented) (M)
- B27 Cross-Border and Growth templates filled in; business-unit merge; cost-centre quarterly budget enforced; setup wizard / first-engagement prompt; remove the stale "arrive with enterprise policies" text (S each)

**Trust & safety operations**
- B28 Enforcement queue: close/dismiss Level 0, triage SLA and overdue flag, filters, appeal deadline and evidence, executive override, remediation tracking, evidence refs and policy version on records, dispute-access restriction (S–M) — **Done 2026-10-15**
- B29 Incident register (type, severity, containment, notification, root cause, remediation) (M) — **Done 2026-10-15**
- B30 Tier history visible to staff; AI-override records and per-output disclosure (S) — **Done 2026-10-15**
- B31 Publish the Charter and Ethics Code in the app (S) — **Done 2026-10-15**

**Reporting**
- B32 KPIs: enforcement, disputes, payments, onboarding funnel, board metrics; marketplace-health without loading every fact into memory (M–L)

**Quality**
- B33 Accessibility checks (axe) in browser tests and CI; skeleton loading states; error messages with a support path (M)
- B34 Coverage gate, API contract tests between frontend types and the backend, typed event payload schemas (M)

## C. Larger items for after launch (each 3+ days)

- C1 Single sign-on (SAML/OIDC), SCIM provisioning, Google/Microsoft sign-in — needs the identity-provider choice
- C2 Semantic (vector) search with rank fusion
- C3 Pricing engine (market rates, budget estimates)
- C4 Separate analytics store
- C5 Infrastructure as code, blue-green/canary deploys, rollback under 3 minutes
- C6 Retainer auto-funding from a saved payment method
- C7 Enterprise API keys and client rate tier; procurement pack
- C8 Feature flags for gradual rollout; ranking experiments with fairness checks
- C9 Fraud and risk scoring from payment and behaviour signals; trust hysteresis and decay
- C10 Audit archive to locked storage after 90 days; push notifications and digests; calendar integration

## D. Not code (39 items) — owners outside engineering

Stripe live account and escrow legal structure; Veriff and screening contracts; email provider; domains and TLS
certificates; Cloud SQL backups and restore test; who may reach the staff app (IAP/VPN); tax rules per country;
Terms, Privacy and agreement text approved by a lawyer; data-processing agreements; mediator staffing and an
arbitration partner; reviewer staffing for verification SLAs; SOC 2 / ISO 27001; incident and change-management
process; board and governance processes; WAF/DDoS/SIEM vendors; the decision on what happens when an approver refuses
to release accepted work. See [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md).
