# Current implementation and merge status

Updated 2026-10-09 after merge commit `2e2c659` on `maruthi`, incorporating dev commit `5891d0f`. The merge changed only the local feature branch; remote dev was not modified. This file describes the inspected checkout, not a new product specification.

## Existing implementation

The repository uses a FastAPI/SQLAlchemy/PostgreSQL modular monolith with facade boundaries, transactional events, durable workers and an append-only audit trail. The React/TypeScript frontend calls these APIs. Core account, organisation, profile, discovery, proposal, contract, escrow and dispute workflows are implemented. Messaging and change orders are also wired into the frontend. [Steps 12–18](STEPS_12_18_IMPLEMENTATION.md) describes policy approvals, notifications, dispute appeals and automatic intake, reviews, advisory AI, reporting and account enforcement.

## Backend additions merged from dev

| Addition | Implemented code | Frontend / operational limits |
|---|---|---|
| Partial acceptance | `src/zoikorum/domains/contract/{api,service,models,schemas}.py`; `domains/escrow/service.py`: buyer offers a reduced amount, professional agrees or declines, agreed amount releases and remainder refunds | No frontend files arrived in this dev merge; dedicated controls still require wiring/verification. Deferred release now reads the persisted accepted amount, including policy approval continuations. |
| Retainer controls and funding reminders | `domains/contract/service.py`, `handlers.py`; `domains/escrow/service.py`: unfunded-cycle cancellation and durable dated funding reminders | Not a complete recurring billing system. Missing automatic funding with an authorised stored payment method; frontend cycle controls need verification. Completion accounts for cancelled cycles. |
| Verification appeals | `domains/verification/{api,service,models,schemas}.py`: time-limited appeals of failed/revoked checks with an independent reviewer | Distinct from dispute and enforcement appeals. Dedicated frontend appeal controls are not established by the merge. |
| Duplicate identities | `domains/identity/duplicates.py`, `api.py`, `models.py`: evidence-based suspicion, owner response, staff decision | Account data is not migrated automatically. No complete frontend workflow verified. |
| Taxonomy expansion and suggestions | `domains/marketplace/taxonomy_data.py`, `service.py`, `api.py`; `domains/ai/specializations.py`: starter categories, advisory suggestions, staff approval/merge/rejection | The extra category names/flags are implementation defaults requiring product review, not detailed source-document requirements. Frontend suggestion/review controls need wiring. |
| Proposal attachments | `domains/proposal/{api,service,models,schemas}.py` and shared uploads | Backend attachment support added; dedicated proposal UI integration still needs verification. |
| Discovery and availability data | `domains/search/{schemas,service}.py`; `domains/professional/{models,schemas,service}.py` | Backend jurisdiction data and weekly hours do not establish that quick view, shareable comparison or weekly-hours controls exist in this frontend. |
| Development MFA switch | `config.py`, `domains/identity/service.py`, `shared/auth.py` | `ZK_DEV_SKIP_MFA` defaults false; effective only in local/development, ignored for test, rejected outside permitted environments. |

## Migrations and operation

Run from `backend/` with the project virtual environment and the intended database:

```powershell
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m alembic check
```

Migration `f1360ce42a96` joins `e0259bc31d85` (integration changes) and `41e86365a15a` (dev product changes), yielding one head. The merge revision itself performs no schema mutations; prerequisite revisions still must run. Keep the API and event worker running for asynchronous funding, refunds, notifications and reminders.

## Integrations and remaining production work

- Stripe hosted checkout, Connect onboarding, signed callbacks, transfers and payouts have adapter/UI code in `domains/payments/` and the payments panels. Selecting Stripe requires `ZK_PAYMENT_PROVIDER=stripe`, secret key, webhook secret, approved funds-flow configuration and enabled operating countries. Credentials alone do not establish regulated escrow, partner approval, or successful live transactions.
- Persona hosted identity code lives in `domains/verification/integration.py` and `providers.py`, with `HostedVerification` frontend controls. Configure `ZK_VERIFICATION_PROVIDER=persona`, API key, template ID and webhook secret. Other checks still require human review or separate live providers.
- S3 versioned storage and optional Object Lock code lives in `shared/storage.py`; install `backend[cloud]` and configure bucket, region, AWS identity, encryption and agreed retention settings. Full archival/legal-hold operations and deployment compliance are not established by the adapter.
- SMTP and optional Anthropic assistance are configurable; real delivery, provider outcomes and model availability were not verified in this merge. Search remains PostgreSQL full-text; OpenSearch/vector search is not implemented.
- Enterprise SSO/SCIM/passkeys, authorised retainer auto-funding, and agreed post-settlement recovery rules remain gaps. See the [product decisions and limits](STEPS_12_18_IMPLEMENTATION.md#product-document-decisions-and-limits).

Never commit `.env` or put backend credentials in frontend environment variables. Existing model defaults are not a guarantee that an external model/service is available.

## Merge-time validation (before CI and database repairs)

- Backend: **103 unit tests passed**, 166 non-unit tests deselected; Python compilation passed.
- Frontend: **23 tests passed**, TypeScript and production build passed. The build retains a large-bundle warning.
- Alembic reports the single head `f1360ce42a96`; whitespace checks passed.
- Database integration tests could not run: PostgreSQL at the test endpoint was unavailable and Docker was stopped. No passing full integration suite is claimed.
- Offline migration SQL generation encountered an existing taxonomy-seeding literal-rendering limitation. Actual database upgrade and model-drift checks remain unverified for this merge.

Regenerate [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) using `python -m zoikorum.cli schema-doc` from `backend/`; the generated document describes models, not proof that a deployed database has applied migrations.

## Database drift repair (2026-10-09)

The local application database was still at `e0259bc31d85` after the dev merge. Missing merged columns affected the data reads used by Messages and other pages. Applied the missing migrations to `f1360ce42a96`; `alembic check` now reports no new upgrade operations, and a read-only model-column check passes.

The API and worker now refuse startup against outdated migration markers or missing model columns. `start-dev.ps1` stops on migration/check failure before launching services. Runtime missing-table/column errors return safe structured service errors, and the frontend preserves their codes and correlation IDs.

Verification for this repair: 19 backend schema-guard, account-page-data and messaging tests passed, covering buyer, professional, enterprise, firm and staff reads; 25 frontend tests and the production build passed. Python compilation and PowerShell launcher syntax passed. These are focused checks, not a full backend suite or exhaustive browser test. The build retains its existing bundle-size warning.

## Full local CI verification (2026-10-09)

After the authentication-test and schema-drift fixes:

- Full backend suite: **283 passed** (unit, integration and regression tests together).
- Fresh isolated database: Alembic upgraded from an empty database to head; `alembic check` reported no new upgrade operations.
- Collection with the repository's strict marker configuration passed; whitespace checks passed.
- Frontend: lint exit code 0, **25 tests passed**, TypeScript/production build passed.
- Existing non-blocking warnings remain: 35 frontend lint warnings and the large-bundle build warning.

These local checks supersede the earlier incomplete merge-time verification above. They do not claim that GitHub's hosted checks have already rerun; the pushed commit must pass that environment too. Live payment, verification, email and cloud-provider behaviour still needs its separate operational verification.

## Completion work (2026-10-12)

- **Track-record ranking:** search stores and ranks by contract success, reviews and response time, with reasons in "why this result" (migration `15081f5c2ac6`; run `python -m zoikorum.cli reindex-search` once after upgrading).
- **"Describe what you need" search:** `POST /v1/search/intent` turns a buyer's own words into ordinary, editable filters with reasons. Claude when configured, keyword rules otherwise (`domains/ai/intent.py`).
- **Browser journeys:** 8 Playwright journeys (sign-up, find, accept and invoice, describe-a-need search, proposal writing, dispute, compliance review, dialog keyboard use).
- **Accessibility:** labels linked to every form field, keyboard-safe dialogs (`useDialog` in `components/ui.tsx`), named table action columns, and accessibility lint rules turned on in `.oxlintrc.json`.
- **Fix:** the proposal form no longer loses what a professional typed when a page load finishes late.
- **Load test:** `backend/scripts/load_test.py` for staging, with a PASS/FAIL verdict ([DEPLOYMENT.md](DEPLOYMENT.md)).
- **Launch checklist:** [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) lists the accounts, decisions and checks owned outside the code.

Verification: backend suite **332 passed**; frontend 28 tests, type check and lint clean (no accessibility findings); browser suite 8/8 on two consecutive runs.

## Gap review and fixes (2026-10-12, afternoon)

A read-through of verification, accounts and the money flow found gaps that tests had not covered. Fixed:

- **Unrelated documents:** every upload gets an automatic first look (`domains/ai/documents.py`, Claude when configured) shown to staff as "Looks right / May be unrelated / Hard to read", with a "flagged" count in the queue. It never decides. Staff pick from standard reasons (`verification/reasons.py`), each with a pre-filled message; "Suspected altered or fake" also opens a Trust & Safety case. Reviewers now see the name as on ID and the details entered for the check.
- **Verification:** an abandoned or expired partner session no longer lets a check be verified without any document; decided checks cannot be decided again (reversals go through appeal); screening "needs info" can be answered with an upload; insurance needs an end date; expiry comes only from the registered credential; checks can be renewed in their last 60 days; a withdrawn credential closes its check; a legal-name change re-does identity checks made before it and re-runs screening; a firm's legal-name or registration change re-opens its registration check; identity uploads always count for the duplicate-account check; an enforcement revocation gets a fresh appeal window; suspended or closed accounts are not listed.
- **Accounts:** ten one-time recovery codes when two-step verification is turned on (new ones on request); sign-in with a recovery code; a Platform Admin can reset two-step for someone else after confirming who they are (audited, signs them out); wrong authenticator or recovery codes count towards the lockout, including at step-up.
- **Money:** funding only while the contract is active (not during a dispute or while an amendment awaits signatures); a payment that completes after its milestone closed is refunded at once; a charge the provider refuses is a failed payment, and a funding the provider never starts reverts after an hour; accepted work is paid when the last milestone closes by any route, including termination; failed refunds are announced and retried daily; payouts the bank returned are retried when the account is enabled again; a partial chargeback refunds the rest of that milestone; auto-acceptance waits while a partial-acceptance offer is open; an agreement nobody signs lapses after a second period; the platform fee is fixed when the contract activates; spend limits count everything a person funded on the engagement and a limit in another currency does not authorise; a denied release approval is announced to both parties and Financial Ops; more money events reach people as notifications.

Migrations `518d2a365770` (evidence checks), `01d68a850c0a` (fee fixed per escrow account), `632f70603204` (recovery codes).

Still a business decision: what should happen when a buyer organisation's approver refuses to release payment for work the buyer already accepted. Today the money stays held and everyone is told; it is neither paid nor refunded on one side's word. Material contract amendments still have no automatic way back if one side never signs (a new, never-signed agreement now lapses).
