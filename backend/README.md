# Zoikorum Backend

FastAPI + PostgreSQL modular monolith for the Zoikorum governed professional-services marketplace.
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
Uploaded files (profile photos) go to `ZK_STORAGE_DIR` (default `backend/var/storage`, git-ignored).

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
pytest                       # uses database "zoikorum_test" on localhost:5434 (created automatically)
```
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
alembic/         single migration chain for all schemas
tests/           per-domain tests, architecture fitness tests, end-to-end platform spine
```

## Rules of the road
Read BUILD_SPEC §0 before writing code. The short version: one domain owns each table; other domains
go through `facade.py` or events; every commercial mutation is idempotent, policy-checked and audited;
money is integer minor units; AI never decides.
