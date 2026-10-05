# Zoikorum Frontend

React 19 + TypeScript + Vite web app for Zoikorum. Styling follows zoikorum.com (Inter, green `#00875A`,
slate text). All business rules are enforced by the backend; the UI only mirrors them.

## Run
```bash
# 1. backend (see ../backend/README.md): API on :8000 and the worker
# 2. frontend
npm install
npm run dev        # http://localhost:5173  (proxies /v1/* to the API on :8000)
npm run build      # type-check + production build into dist/
```

## Step 1 — role-based login (built)

| Route | Who | Purpose |
|---|---|---|
| `/login` | everyone | One sign-in for all roles; asks for the authenticator code when MFA is on; opens the right dashboard |
| `/join` (`?type=BUYER\|PROFESSIONAL\|FIRM\|ENTERPRISE`) | new users | Sign-up by account type; Firm/Enterprise also capture the organization name |
| `/enterprise` | enterprise buyers | Target of the site's "Enterprise Access" button |
| `/forgot-password`, `/reset-password`, `/confirm-email` | everyone | Account recovery and email confirmation |
| `/app/buyer` · `/app/professional` · `/app/firm` · `/app/enterprise` | by account role | Role workspaces (summary cards fill in later steps) |
| `/app/ops`, `/app/ops/staff` | platform staff / Platform Admin | Operations home; grant/revoke staff roles (step-up MFA) |
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

Rules the UI follows:
- Staff, Firm Admins and Enterprise Admins are sent to `/app/security` until two-step verification is on.
- Pages are gated by role (`RequireRole`). The API applies the same check to every call.
- Sensitive actions that get `STEP_UP_REQUIRED` open the "Confirm it's you" code dialog and retry.
- In development (no email provider yet) the API returns the email-confirmation and password-reset
  tokens, and the UI shows them as "Development mode" links.

## Layout
```
src/api/        HTTP client (token refresh, Problem Details errors) + typed APIs (auth, orgs, professional)
src/auth/       AuthContext (session) and route guards
src/components/ shared UI: site header, auth layout, fields, step-up MFA dialog
src/pages/      screens
```
