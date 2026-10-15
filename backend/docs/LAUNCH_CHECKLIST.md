# Zoikorum launch checklist

What has to happen before real customers and real money go through Zoikorum. The code side is built and tested;
nearly everything left is an account, a contract, a decision or a check that people outside the codebase own.
Tick each line and write who did it and when. "Owner" is the role responsible, not necessarily the person who does it.

Status on 2026-10-12: every feature in the build specification is in the code, with 332 backend tests, 28 frontend
tests and 8 browser journeys passing locally. See [CURRENT_STATUS.md](CURRENT_STATUS.md) for detail and
[DEPLOYMENT.md](DEPLOYMENT.md) for how to run it.

## 1. Accounts and keys with outside services

Each needs a company account, a contract or terms accepted, and keys stored in the secret manager (never in git or email).

| ✓ | Service | What it is for | Owner | Setting(s) |
|---|---|---|---|---|
| ☐ | Google Cloud project: VM, Cloud SQL with backups and two database users, GCS bucket, Cloud KMS key, Artifact Registry, Secret Manager ([DEPLOYMENT.md](DEPLOYMENT.md#google-cloud-setup-once-per-environment)) | Running the platform, files, keys | Engineering lead | `ZK_DATABASE_URL`, `ZK_MIGRATION_DATABASE_URL`, `ZK_DB_APP_ROLE`, `ZK_GCS_BUCKET`, `ZK_FIELD_KMS_KEY_NAME`, `ZK_FIELD_DATA_KEYS` |
| ☐ | HTTPS load balancer with managed certificates for the app and staff domains; Identity-Aware Proxy on the staff app | Public addresses; only staff reach the staff app | Engineering lead | `ZK_FRONTEND_URL`, `ZK_STAFF_FRONTEND_URL`, `ZK_WEBAUTHN_RP_ID`, `ZK_LB_IP` |
| ☐ | GitHub: `production` environment with required reviewers, release variables, Workload Identity Federation | Approved releases ([release workflow](../../.github/workflows/release.yml)) | Engineering lead | — |
| ☐ | Domain names (app and staff) | `https://` addresses customers and staff use | Engineering lead | DNS records to the load balancer |
| ☐ | Email sending (e.g. AWS SES), with SPF/DKIM/DMARC on the domain | Confirmations, password resets, notices | Engineering lead | `ZK_EMAIL_PROVIDER=smtp`, `ZK_SMTP_*`, `ZK_EMAIL_FROM` |
| ☐ | Veriff (identity checks) | Verifying professionals' identity documents | Compliance + management (contract) | `ZK_VERIFICATION_PROVIDER=veriff`, `ZK_VERIFF_API_KEY`, `ZK_VERIFF_SHARED_SECRET`; webhook URL in Veriff's dashboard |
| ☐ | Stripe (payments, Connect payouts) | Funding escrow, paying professionals | Finance + management | `ZK_PAYMENT_PROVIDER=stripe`, Stripe keys, `ZK_PAYMENT_FLOW_APPROVED` only after Stripe approves the funds flow |
| ☐ | Redis | Shared rate limits across servers | Engineering lead | `ZK_REDIS_URL` |
| ☐ | Sentry (optional) | Error reporting | Engineering lead | `ZK_SENTRY_DSN`, `ZK_RELEASE` |
| ☐ | Anthropic (optional) | AI for "Describe what you need" and specialization matching; works without it using keyword rules | Management (cost decision) | `ZK_AI_PROVIDER=anthropic`, `ZK_ANTHROPIC_API_KEY` |
| ☐ | Secrets generated per environment | Sign-in tokens, field encryption, webhooks | Engineering lead | `ZK_JWT_SECRET`, `ZK_FIELD_ENCRYPTION_KEY`, `ZK_WEBHOOK_SECRET` (long random values; the app refuses to start with development values outside development) |

## 2. Business and legal decisions

The code has a setting or a placeholder for each; someone with authority has to choose the value and sign it off.

| ✓ | Decision | Where it shows | Owner |
|---|---|---|---|
| ☐ | Terms of service, privacy policy, cookie notice: final text approved by a lawyer | Sign-up, footer, `/legal` pages | Management + legal counsel |
| ☐ | Platform fee (currently 10%) and who pays it | Proposals, invoices (`ZK_PLATFORM_FEE_BPS`) | Management + finance |
| ☐ | Escrow model: is Stripe's flow enough, or is a licence or a regulated partner needed in each country we operate in? | Funding, release, refunds | Legal counsel + finance |
| ☐ | Countries we launch in (buyers and professionals) | Sign-up country lists, Stripe Connect countries | Management |
| ☐ | Platform deadlines: acceptance review window, signature deadline, dispute evidence, direct-resolution and challenge windows | Server settings, one source for every organisation (`ZK_ACCEPTANCE_WINDOW_DAYS`, `ZK_SIGNATURE_DEADLINE_DAYS`, `ZK_DISPUTE_*`) | Management + operations |
| ☐ | Data retention periods and what is kept after an account is deleted | Privacy export/erasure ([CUSTOMER_DATA.md](CUSTOMER_DATA.md)) | Legal counsel |
| ☐ | Dispute rules and mediator playbook | Disputes, staff dispute queue | Operations + legal counsel |
| ☐ | Verification rules: which credentials need which evidence, Tier A requirements, insurance minimums | Verification queue, trust tiers | Compliance |
| ☐ | Specialization list: the five starter categories beyond Finance & Accounting reviewed by people who know those fields | Taxonomy (staff can edit it) | Product/management |
| ☐ | Data processing agreements with each outside service above | — | Legal counsel |

## 3. Security

| ✓ | Check | Owner |
|---|---|---|
| ☐ | Independent penetration test of staging, findings fixed or accepted in writing | Management (hire) + engineering |
| ☐ | Two-step sign-in required for every staff account; development switches off (`ZK_DEV_SKIP_MFA` is refused outside development, confirm the staging and production settings) | Engineering lead |
| ☐ | Staff roles reviewed: each person has only the roles they need (Staff → Users page) | Operations |
| ☐ | Secret rotation plan written (who can rotate each key, how, and how often) | Engineering lead |
| ☐ | Dependency and container image scanning turned on in CI | Engineering |

## 4. Running it

| ✓ | Check | Owner |
|---|---|---|
| ☐ | Staging environment set up exactly like production, with the partner services in test mode | Engineering lead |
| ☐ | Restore test: restore a database backup to a new server and start the app against it | Engineering lead |
| ☐ | Monitoring and alerts: `/ready` failing, error rate, slow responses, worker stopped, disk and database size | Engineering lead |
| ☐ | Prometheus scrapes `GET /metrics` with `ZK_METRICS_TOKEN`. Suggested alerts: `zk_outbox_oldest_unpublished_seconds` > 120 or `zk_timers_oldest_overdue_seconds` > 300 (worker stopped or behind); `zk_consumer_dead_letters_financial` > 0 (page Financial Operations); `zk_reconciliation_latest_mismatches` > 0 or `zk_reconciliation_latest_age_days` ≥ 2; `zk_circuit_open` = 1 for 5 minutes; p99 of `zk_http_request_duration_seconds` over 300 ms for search or 500 ms for proposal changes | Engineering lead |
| ☐ | Incident switches rehearsed on staging (Administration → Switches & Worker): pause and resume funding, releases and payouts; releases and payouts must go out on their own within 10 minutes of switching back on. Alert on any `zk_switch_paused_*` = 1 for more than a day | Engineering lead + Financial Operations |
| ☐ | Traces (optional): `ZK_TRACING_ENDPOINT` points at an OpenTelemetry collector; image built with the `tracing` extra (default) | Engineering lead |
| ☐ | On-call rota and an incident contact list (including Stripe and Veriff support) | Engineering lead + management |
| ☐ | Load test on staging passed and recorded below (`backend/scripts/load_test.py`, see [DEPLOYMENT.md](DEPLOYMENT.md#load-test-staging-before-launch-and-before-big-releases)) | Engineering |
| ☐ | One full engagement done end to end on staging with real partner test modes: sign-up, Veriff check, request, proposal, contract, funding, delivery, acceptance, payout, invoice | Product + engineering |
| ☐ | First staff accounts created (`python -m zoikorum.cli create-admin`), then roles granted in the app | Operations |
| ☐ | Search index built after the first deploy and after releases that add search fields (`python -m zoikorum.cli reindex-search`) | Engineering |

Load test result: users ___, duration ___, requests/second ___, worst p95 ___ ms (endpoint ___), errors ___%,
server sizes ___, rate limits on/off ___. Run by ___ on ___.

## 5. Accessibility

Done in code: every form field has a label read out by screen readers, dialogs can be used by keyboard (focus moves in
and stays in, Escape closes, focus returns), table action columns are named, and the linter now blocks the common
mistakes. A browser test checks the dialog keyboard behaviour.

| ✓ | Check | Owner |
|---|---|---|
| ☐ | Manual pass with a screen reader (NVDA on Windows or VoiceOver on Mac) through sign-up, search, proposal, funding, dispute | Product |
| ☐ | Colour contrast checked on every page (e.g. browser accessibility tools) | Design |
| ☐ | If selling to public-sector or large enterprise buyers: a formal WCAG 2.1 AA audit and an accessibility statement | Management |

## 6. Known limits at launch (agreed, not bugs)

- Search is PostgreSQL full-text with ranking by trust, availability and track record; no semantic/vector search.
- Passkeys are built. Enterprise single sign-on (SAML/OIDC) and SCIM provisioning are not built yet.
- Retainers are funded cycle by cycle by the buyer; there is no automatic card charging.
- Recovery of money after a dispute has settled and been paid out follows a manual process (no automated clawback).
- Live behaviour of Stripe, Veriff, SES and Anthropic has been tested only with their test modes or simulations in
  development; the staging run in section 4 is the first real check.

## 7. Added on 2026-10-14

| ✓ | Item | Owner |
|---|---|---|
| ☐ | Tax rules per country for invoices (`ZK_TAX_RULES`, tax-inclusive) decided and entered | Finance |
| ☐ | Support agents named and given the Support Agent role; first-answer target (one business day) agreed | Operations |
| ☐ | Alertmanager receivers filled in (paging tool, email) and a test alert received | Engineering lead |
| ☐ | Trust & Safety staff briefed on user reports (Safety cases → "Show the reports", "Close: no action needed") | Operations |
| ☐ | Financial Operations briefed on Money Problems (retry, close with outcome) | Financial Operations |
