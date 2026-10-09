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
- Enterprise SSO/SCIM/passkeys, privacy-request fulfilment, authorised retainer auto-funding, saved buyers/followed organisations, and agreed post-settlement recovery rules remain gaps. See the [product decisions and limits](STEPS_12_18_IMPLEMENTATION.md#product-document-decisions-and-limits).

Never commit `.env` or put backend credentials in frontend environment variables. Existing model defaults are not a guarantee that an external model/service is available.

## Latest validation

- Backend: **103 unit tests passed**, 166 non-unit tests deselected; Python compilation passed.
- Frontend: **23 tests passed**, TypeScript and production build passed. The build retains a large-bundle warning.
- Alembic reports the single head `f1360ce42a96`; whitespace checks passed.
- Database integration tests could not run: PostgreSQL at the test endpoint was unavailable and Docker was stopped. No passing full integration suite is claimed.
- Offline migration SQL generation encountered an existing taxonomy-seeding literal-rendering limitation. Actual database upgrade and model-drift checks remain unverified for this merge.

Regenerate [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) using `python -m zoikorum.cli schema-doc` from `backend/`; the generated document describes models, not proof that a deployed database has applied migrations.
