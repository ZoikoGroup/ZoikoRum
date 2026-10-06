# Zoikorum

Governed professional-services marketplace: verified professionals, contract-required engagements,
escrow-protected payments and an audit-grade record of every action.

| Folder | What it is | Docs |
|---|---|---|
| [`backend/`](backend/) | FastAPI + PostgreSQL modular monolith: one schema per domain, outbox events, audit ledger | [backend/README.md](backend/README.md), [Architecture](backend/docs/ARCHITECTURE.md), [Build spec](backend/docs/BUILD_SPEC.md) |
| [`frontend/`](frontend/) | React 19 + TypeScript + Vite web app | [frontend/README.md](frontend/README.md) |
| `docker-compose.yml` | Local Postgres 16 (port 5434) and Redis 7 (port 6380) | |
| [`docs/product/`](docs/product/README.md) | The 18 product documents (originals + readable text) | |
| `start-dev.ps1` | Starts the whole dev stack on Windows | |
| `.github/workflows/ci.yml` | CI: backend migrations + tests, frontend lint + build | |

## Quick start (Windows)

Prerequisites: Docker Desktop, Python 3.12+, Node.js 20.19+ (or 22.12+).

```powershell
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements-dev.txt
.venv\Scripts\pip install --no-deps -e backend
copy backend\.env.example backend\.env      # then change the secrets
cd frontend; npm install; cd ..

.\start-dev.ps1                              # database, migrations, API, worker and frontend
```

Then open http://localhost:5173. Create the first Platform Admin with
`python -m zoikorum.cli create-admin` (see the backend README). macOS/Linux: run the same steps with
`.venv/bin/...` and start the servers as described in each folder's README.

## Build status

Built in small, reviewed steps. See [ARCHITECTURE.md §6](backend/docs/ARCHITECTURE.md) for the current status:
foundation, role-based login, organizations & firms, professional profiles, verification & trust tiers, and search & discovery are built; proposals come next.

## Rules of the road

- Read [BUILD_SPEC §0](backend/docs/BUILD_SPEC.md) before writing backend code: domains talk only through
  `facade.py` or events, money is integer minor units, every commercial action is idempotent, policy-checked and audited.
- Never commit `.env` files or secrets.
- Every database change ships as an Alembic migration; CI fails if the models and migrations drift.
