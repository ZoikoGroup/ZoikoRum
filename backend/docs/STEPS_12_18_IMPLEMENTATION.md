# Steps 12–18 implementation

The implementation follows the existing modular monolith: each domain owns its schema, cross-domain reads use facades, and durable events drive notifications, reporting, trust updates and automatic dispute intake. Business commands retain live authorization, transaction boundaries and audit records.

| Step | Backend | Frontend |
| --- | --- | --- |
| 12 — Enterprise policies and approvals | Versioned profiles, eligibility and spend rules, independent approval workflows, documented expiring exceptions, pinned contract terms, approval continuations and accepted-milestone release guards | `/app/policies`, organisation and cost-centre selection, approval and exception forms |
| 13 — Notifications | Recipient-scoped inbox, preferences, mandatory security notices, SMTP delivery/retry, encrypted webhook secrets, signed HTTPS deliveries, replay and immutable attempt logs | `/app/notifications`, unread bell, Settings preferences, `/app/webhooks` including attempt history |
| 14 — Dispute extras | Independent appeals with immutable original decisions; policy-pinned deadline, repeated revision and confirmed-compliance triggers; funded-work freeze and duplicate-intake protection | Engagement dispute/appeal panels, operator appeal review, automatic-intake controls in policy drafts |
| 15 — Reviews and outcomes | One named buyer review per completed engagement; public ratings; completion recency, on-time delivery, confirmed dispute outcomes and response statistics | Completed-engagement review form and public professional reviews |
| 16 — AI assistance | Authorized proposal/contract/dispute assistance; versioned prompt registry, golden-test approval, immutable inference records, deterministic fallback and advisory risk triage | Draft assistance, contract/evidence summaries, `/app/ops/ai` |
| 17 — Reports and analytics | Rebuildable event projections; buyer/professional action and financial metrics; marketplace health; scoped JSON, CSV and paginated PDF exports | `/app/reports`, `/app/ops/analytics` |
| 18 — Admin and safety | Evidence-based cases, independent approval, separate Executive/Legal approvals for Level 4, live restrictions, expiry/reversal, independent appeals and authorized financial dead-letter replay | `/app/safety`, `/app/ops/safety`, `/app/ops/dead-letters`, `/app/ops/audit` |

## Configuration and operation

Apply the checked-in migrations with `alembic upgrade head` from `backend/` using the project virtual environment and the intended database configuration. Steps 12–18 introduced `b739e68210ad` and `c8427d916a30`; later integration revisions and dev migrations now join at `f1360ce42a96`. See [current merge status](CURRENT_STATUS.md) for the migration graph and latest validation limits. The application/event relay must be running for asynchronous delivery, projections, reminders and timers.

Email defaults to local delivery status rather than claiming that a message reached an external mailbox. Configure the SMTP settings in `zoikorum/config.py` for real email delivery. Tokens are minted when an account email is delivered; plaintext tokens and webhook secrets are excluded from audit/event payloads. Webhook secrets are shown once, stored encrypted and used to sign the raw JSON body. Deliveries retry for 24 hours; immutable attempt records are retained indefinitely, satisfying the minimum 90-day retention requirement.

AI defaults to deterministic offline assistance. To use Anthropic, install the backend `ai` optional dependency and configure `ZK_AI_PROVIDER`, `ZK_AI_MODEL` and `ZK_ANTHROPIC_API_KEY`. An AI Safety Reviewer must approve a matching prompt version after its golden tests pass. Missing credentials or provider failures cannot approve a prompt; inference failures return an explicitly labelled fallback. Live SMTP/Anthropic credentials and delivery are outside the local test run.

Automatic dispute triggers default to disabled. Set `autoDisputeMissedDeadline`, `autoDisputeRejectionCount` (2–20 or null) and `autoDisputeComplianceFlag` in an organisation policy draft, save it and activate it. Contracts retain the accepted settings; later profile edits do not silently change an existing agreement. An AI flag alone cannot open a compliance case, change a trust tier or impose enforcement.

Suspended accounts can authenticate to read safety notices and file appeals. The live session/restriction guard blocks business APIs and removes staff authority. Old or new access tokens cannot bypass a live restriction. Financial actions still require their owning domain's eligibility, authorization and ledger checks.

## Product-document decisions and limits

- The product documents disagree on optional escrow versus funding before work. The existing mandatory-funding baseline remains enforced; policy versions cannot disable it.
- Trust scoring follows the concrete BUILD_SPEC weights: verification 40, completion 25, on-time delivery 10, confirmed dispute outcomes 15 and responsiveness 10. Ratings are published separately. The handbook's different rating weights and numeric tier hysteresis thresholds need a single agreed specification before changing the tier algorithm. Completion full-credit and recency half-life are configuration defaults, not claimed document requirements.
- Dispute appeals use a 14-day implementation window. Upholding an appeal records an independent remediation decision without rewriting the original settlement or automatically clawing back a payout. The documents do not define a safe post-settlement clawback workflow.
- Automatic intake covers eligible funded, unaccepted work. A post-acceptance challenge window cannot currently freeze money already released by the existing acceptance-and-release workflow; this requires an agreed holdback or recovery policy.
- Reporting projections reconstruct only recorded events. Historical saves removed before the new unbookmark event existed cannot be reconstructed accurately from the old event history alone. Financial projections and exports use integer minor currency units and separate currencies.
- Contract summaries preserve the source terms and hash. Missing legal/IP clauses are not invented by AI or by the implementation.

## Verification

Latest merge checks (2026-10-09): 103 backend unit tests and 23 frontend tests passed; compilation and frontend build passed. PostgreSQL was unavailable, so this merge has not passed database integration or migration execution checks. Offline migration SQL generation also hit an existing taxonomy seed rendering limitation. Earlier feature-level checks below describe test coverage, not a new full-suite pass.

Currency-summary follow-up: earnings totals now aggregate the entire payout history per currency, independently of the latest-200 payout detail window. Monthly settled earnings use the current UTC month. `totalsByCurrency` is the authoritative summary; legacy `totals` remains available for a single currency and is empty for multiple currencies. Buyer payments, engagement values, protected funds and dispute totals display currencies separately without an implied exchange rate.

Backend tests use real isolated PostgreSQL databases, domain schemas and database triggers. They cover permissions, mandatory notices, HMAC signatures/retries, prompt approval/provider failure, review eligibility, export scope, projection rebuild, automatic intake, live suspension and independent appeals. Direct SQL checks verify immutable approved prompts, delivery logs and dispute decisions.

```powershell
# Repository root
$env:ZK_TEST_FAST_CLEANUP = 'true' # Optional on slow local storage; clears the same tables and resets sequences without relation rewrites.
.venv/Scripts/python.exe -m pytest backend/tests -q -o addopts='' -p no:cacheprovider

# Frontend directory
npm test
npm run build
npm run lint
```

For concurrent backend test runs, set a different `ZK_TEST_DATABASE` for each process: the fixture recreates schemas and clears tables in its selected test database. Do not run two suites against the same test database. Migrations are verified separately by upgrading an isolated database and running `alembic check`; this does not migrate the application's configured database.
