# Zoikorum Frontend

React 19 + TypeScript + Vite web app for Zoikorum. Zoikorum brand styling (Inter, green `#00875A`,
slate text). All business rules are enforced by the backend; the UI only mirrors them.

## Run
```bash
# 1. backend (see ../backend/README.md): API on :8000 and the worker
# 2. frontend
npm install
npm run dev        # http://localhost:5173  (proxies /v1/* to the API on :8000)
npm test             # unit tests (Vitest): upload helpers, CSV export, password strength, money format
npm run build      # type-check + production build into dist/
npm run e2e        # browser tests (Playwright): see below
```

### Browser tests (`e2e/`)

A real Chrome drives the main journeys: a customer signs up, confirms their email and signs back in; finds a verified
professional and opens the profile; accepts delivered work and downloads the agreement and invoice PDFs. Test data is
set up through the API (`e2e/api.ts`): a professional who publishes and passes the identity check through the simulated
identity partner, a buyer organisation, and an engagement up to submitted work.

The tests never touch your running app or data: `e2e/global-setup.ts` recreates a separate database (`zk_e2e`;
`backend/scripts/e2e_database.py` refuses any other name), and Playwright starts its own API and worker on :8100
(`backend/scripts/e2e_stack.py`, fixed development settings) and this app on :5174. Needs PostgreSQL from
`docker-compose.yml`, the backend virtualenv (`ZK_E2E_PYTHON` overrides its path) and, once, `npx playwright install chromium`.
On failure, `test-results/` holds screenshots and a trace (`npx playwright show-trace <trace.zip>`). CI runs them in the
`browser` job.

## Step 1 — role-based login (built)

| Route | Who | Purpose |
|---|---|---|
| `/login` | everyone | One sign-in for all roles; asks for the authenticator code when MFA is on; opens the right dashboard |
| `/join` (`?type=BUYER\|PROFESSIONAL\|FIRM\|ENTERPRISE`) | new users | Sign-up by account type; Firm/Enterprise also capture the organization name |
| `/enterprise` | enterprise buyers | Target of the site's "Enterprise Access" button |
| `/forgot-password`, `/reset-password`, `/confirm-email` | everyone | Account recovery and email confirmation |
| `/app/buyer` · `/app/professional` · `/app/firm` · `/app/enterprise` | by account role | Role workspaces (summary cards fill in later steps) |
| `/app/ops`, `/app/ops/staff` | platform staff / Platform Admin | Operations home; grant/revoke staff roles (step-up MFA) |
| `/app/ops/reconciliation` | Financial Ops, Platform Admin | Nightly reconciliation results per day; re-run a day; mismatch details |
| `/app/ops/users` | Platform Admin, T&S analyst | Every account: search, role and status filters, last sign-in; "Open safety case" to restrict one (audited) |
| `/app/ops/duplicates` | Platform Admin, T&S analyst | Possible duplicate accounts (same ID document): keep one, close the other, or dismiss |
| `/app/ops/taxonomy` | Platform Admin | Specializations suggested by professionals: approve, merge into an existing one, or reject |
| `/app/compare?ids=` | Buyer, Enterprise | Shared comparison of up to 3 professionals (signed-in link) |
| `/app/account`, `/app/security` | signed in | Roles held, add Buyer/Professional role, set up two-step verification |

## Step 2 — organizations, firms & team roles (built)

| Route | Who | Purpose |
|---|---|---|
| `/app/enterprise` | Enterprise Admin / Member | Organization home: your roles, team size, setup checklist |
| `/app/enterprise/team` | members (admins manage) | Members, roles, approval spend limits; invite / edit / remove; pending invitations |
| `/app/enterprise/structure` | members (admins / budget owners manage) | Business units and cost centers with quarterly budgets |
| `/app/firm`, `/app/firm/team`, `/app/firm/profile` | Firm Admin (members read) | Firm status, professionals, authorized representative, registration details |
| `/app/invitations` | signed in | Invitations sent to your email (accept requires a confirmed email) |
| `/invite?kind=org\|firm&token=` | anyone | Invitation link: sign in or sign up, then join automatically |

## Step 3 — professional profile & offerings (built)

| Route | Who | Purpose |
|---|---|---|
| `/app/professional` | Professional | Profile status, Trust Tier (C until verification), readiness checklist with links to fix each item |
| `/app/professional/profile?step=` | Professional | Step-by-step setup: basics, specializations (taxonomy), engagement & pricing, availability, jurisdictions, credentials, review & publish |
| `/app/professional/offerings` | Professional | Service offerings: create, edit, activate, pause (paused ≠ deleted) |
| `/professionals/:id` | anyone (no sign-in) | Public profile. Unpublished profiles are visible only to their owner (preview) |

## Step 4 — verification & trust tiers (built)

| Route | Who | Purpose |
|---|---|---|
| `/app/professional/verification` | Professional | Trust tier, the five verification areas and why; start identity, jurisdiction and insurance checks; submit documents |
| `/app/firm/verification` | Firm Admin | Start and follow the firm-registration check |
| `/app/ops/verification` | Compliance Officer | Review queue: evidence, decision (verified / more info / not verified) with step-up MFA |

Documents: the browser computes each file's SHA-256; only name, size and fingerprint are sent until secure storage is connected.

## Step 5 — search & dashboards (built)

| Route | Who | Purpose |
|---|---|---|
| `/professionals` | anyone (no sign-in) | Browse and filter published professionals; each result shows its Trust Tier and why it matched. Filters live in the URL |
| `/app/buyer`, `/app/enterprise`, `/app/professional`, `/app/firm`, `/app/ops` | by role | One dashboard design: greeting, summary cards, pending actions with priority, plus role panels (recent activity, verified professionals, verification). Only real data; future areas say when they arrive |

## Customer portal (management designs; built)

Buyers and enterprise users get a "Customer / Account" sidebar. Screens whose records arrive in later steps
(requests, proposals, contracts, escrow, messaging) already have their final layout, with real zero counts and
an explanation of how the step will work. Nothing is invented: no wallet balance, no star ratings, no partner logos.

| Route | Who | Purpose |
|---|---|---|
| `/app/find` | Buyer, Enterprise | Search verified professionals: filter bar and panel (incl. experience), active filter pills, save this search, verification chips, compare up to 3 |
| `/app/saved` | Buyer, Enterprise | Shortlist with collections, filters, bulk add-to-collection, compare, remove; saved searches with new-match counts |
| `/app/requests/new?pro=…&pro=…` | Buyer, Enterprise | Request a proposal (5 steps: context, scope, commercial, protections, review); 1–3 professionals |
| `/app/requests`, `/app/requests/:id`, `/app/proposals` | Buyer, Enterprise | Requests and received proposals; side-by-side comparison, request revision, decline, accept |
| `/app/professional/requests`, `/app/professional/requests/:id` | Professional | Incoming requests inbox; NDA; proposal builder (deliverables, milestones, dates, terms); decline with reason; withdraw |
| `/app/engagements`, `/app/engagements/:id` | Buyer, Enterprise | Contracts: review the agreement, sign (two-step), milestones (review submitted work, request revision, accept), activity, open delivered files, overdue-review notice, export engagement record (JSON) |
| `/app/professional/engagements`, `/app/professional/engagements/:id` | Professional | Countersign, deliver milestones (note + file fingerprints), resubmit after revision |
| `/app/payments` | Buyer, Enterprise | Payments & Protection: escrow per engagement, payments into escrow, invoices with printable receipts, CSV export (test mode) |
| `/app/professional/earnings` | Professional | Payout account (two-step), payouts with gross / fee / net |
| `/app/disputes`, `/app/professional/disputes`, `/app/ops/disputes`, `/app/disputes/:id` | Parties; Mediator / Legal / Platform Admin | Raise a dispute from an engagement; evidence, structured proposals, escalation, mediation, two-person platform decision, decision package and timeline |
| `/app/messages` | Buyer, Enterprise | Layout until messaging exists |
| `/app/organisation?tab=` | Buyer, Enterprise | Profile (name, industry, time zone), members & access, roles & authority, billing contacts, audit log + CSV export |
| `/app/verification` | Buyer, Enterprise | Verification status of the professionals on your shortlist; what each check and Tier means |
| `/app/settings?tab=` | everyone | Account, security (password, two-step, signed-in devices), notifications, privacy requests, platform preferences |
| `/app/help` | everyone | Searchable help from the product docs, service status (`/health`), support cases (empty until engagements) |

Shared building blocks live in `src/components/portal.tsx` and `src/components/CompareDialog.tsx`; the screens are in `src/pages/customer/`.

Rules the UI follows:
- Staff, Firm Admins and Enterprise Admins are sent to `/app/security` until two-step verification is on.
- Pages are gated by role (`RequireRole`). The API applies the same check to every call.
- Sensitive actions that get `STEP_UP_REQUIRED` open the "Confirm it's you" code dialog and retry.
- In development the API returns the email-confirmation and password-reset
  tokens, and the UI shows them as "Development mode" links.

## Messaging, commercial workflows and operations

Current routes include `/app/messages`, `/app/policies`, `/app/notifications`, `/app/webhooks`, `/app/reports`, `/app/safety`, and staff AI, analytics, safety, dead-letter and audit pages. Engagement workspaces include change orders, payments and dispute workflows; completed engagements support reviews. Backend authorization remains authoritative.

Hosted Stripe payments/onboarding and Persona identity controls read backend configuration and require configured external services. Credentials stay on the backend. The latest dev merge brought backend additions rather than matching frontend files: partial acceptance, verification appeals, duplicate-account handling, taxonomy suggestions, proposal attachments and retainer controls still need dedicated UI wiring or verification. See [current status](../backend/docs/CURRENT_STATUS.md).

Current local CI validation (2026-10-09): lint returned exit code 0, 25 frontend tests and the production build passed. There are 35 non-blocking lint warnings and a large-bundle warning. The full backend suite and fresh-database migration checks also passed; live provider verification remains separate.

## Layout
```
src/api/        HTTP client (token refresh, Problem Details errors) + typed APIs (auth, orgs, professional)
src/auth/       AuthContext (session) and route guards
src/components/ shared UI: site header, auth layout, fields, step-up MFA dialog
src/pages/      screens
```
