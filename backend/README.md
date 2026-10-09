# Zoikorum Backend

FastAPI + PostgreSQL modular monolith for the Zoikorum governed professional-services marketplace.
Current status and merge validation: [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md).

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Domain contracts: [docs/BUILD_SPEC.md](docs/BUILD_SPEC.md)

## Prerequisites
- Python 3.12+ (developed on 3.13)
- Docker (for Postgres 16 + Redis), started from the repo root: `docker compose up -d`

## Setup
```bash
# from the repo root
python -m venv .venv
.venv/Scripts/pip install -e "backend[dev]"      # Windows; use .venv/bin/pip on macOS/Linux
# Exact, tested versions instead (CI does this):
#   pip install -r backend/requirements-dev.txt && pip install --no-deps -e backend
cp backend/.env.example backend/.env             # then change the secrets

cd backend
alembic upgrade head                             # creates every domain schema + append-only triggers
```

## Run
```bash
cd backend
uvicorn zoikorum.main:app --reload --app-dir src   # API on http://localhost:8000  (OpenAPI at /docs)
python -m zoikorum.worker                          # outbox relay, consumer retries, durable timers
```
The worker must run, or events (and therefore the audit ledger and every later domain) will not progress.
On Windows, clicking inside the worker's console window can pause it (QuickEdit mode); press Enter or Esc in that window to resume.
Local uploads use `ZK_STORAGE_DIR` (default `var/storage` relative to the backend working directory, git-ignored). Optional S3 storage and hosted payment/verification configuration are described in [current status](docs/CURRENT_STATUS.md#integrations-and-remaining-production-work).

Create the first Platform Admin (only possible from the CLI; the password is prompted, or read from `ZK_ADMIN_PASSWORD`):
```bash
python -m zoikorum.cli create-admin --email admin@yourcompany.com --name "Platform Admin"
```
Sign in at http://localhost:5173/login. Staff accounts must set up two-step verification first.

After restoring a database or changing the search document, rebuild the search index:
```bash
python -m zoikorum.cli reindex-search
```

## Test
```bash
cd backend
pytest                       # everything; uses database "zoikorum_test" on localhost:5434 (created automatically)
pytest -m unit               # pure business rules, no database (under a second)
pytest -m integration        # one feature through the API + database
pytest -m regression         # end-to-end journeys across Steps 1-9 (tests/test_regression.py)
```
Plain (non-async) tests that use no database fixture are marked `unit` automatically and skip the database;
everything else is `integration` unless marked `regression`. `--strict-markers` rejects unknown markers.
Useful env vars for isolated runs: `ZK_TEST_DATABASE=<db>` and `ZK_DOMAINS=identity,audit,<domain>`.

## Dependencies
`pyproject.toml` declares the dependencies (minimum versions). `requirements.txt` (runtime) and
`requirements-dev.txt` (tests) pin the exact versions the test suite passes with, for reproducible
installs. When you add or upgrade a dependency, update `pyproject.toml`, run the tests, then refresh both pin files.

## Layout
```
src/zoikorum/
  shared/        kernel: db, events/outbox, relay+timers, idempotency, auth, errors, money, http
  domains/<d>/   models, schemas, service, api (router), handlers (events/timers), facade (public)
  main.py        app factory (auto-mounts every domain)
  worker.py      background worker
alembic/         revisions for all schemas; branch histories join at a single merge head
tests/           per-domain tests, architecture fitness tests, end-to-end platform spine
```

## Rules of the road
Read BUILD_SPEC §0 before writing code. The short version: one domain owns each table; other domains
go through `facade.py` or events; every commercial mutation is idempotent, policy-checked and audited;
money is integer minor units; AI never decides.

## Schema reference

Regenerate the model-derived table reference without connecting to a database:

```bash
python -m zoikorum.cli schema-doc
```

After the dev merge, the migration head is `f1360ce42a96`. A single head does not prove database migration success; run upgrade and `alembic check` against the intended database.
