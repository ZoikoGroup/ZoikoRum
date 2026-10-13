"""API and worker in one process for the browser tests (frontend/playwright.config.ts starts it).

It first recreates and migrates its own database (e2e_database.py), so the servers never start before their database
exists and nothing drops the database under a running server. Fixed settings for a repeatable run, independent of any
developer .env: its own database (zk_e2e), local environment, no two-step codes, simulated identity partner, test
payment provider, no rate limits, a throwaway file store.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

PORT = int(os.environ.get("ZK_E2E_API_PORT", "8100"))
SETTINGS = {
    "ZK_ENV": "local",
    "ZK_DATABASE_URL": os.environ.get("ZK_E2E_DATABASE_URL", "postgresql+asyncpg://zoikorum:zoikorum@localhost:5434/zk_e2e"),
    "ZK_DEV_SKIP_MFA": "true",
    "ZK_VERIFICATION_PROVIDER": "simulated",
    "ZK_PAYMENT_PROVIDER": "fake",
    "ZK_EMAIL_PROVIDER": "console",
    "ZK_RATE_LIMIT_ENABLED": "false",
    "ZK_STORAGE_PROVIDER": "local",
    "ZK_STORAGE_DIR": tempfile.mkdtemp(prefix="zk-e2e-files-"),
    "ZK_FRONTEND_URL": os.environ.get("ZK_E2E_WEB_URL", "http://localhost:5174"),
    "ZK_LOG_LEVEL": "WARNING",
}


def prepare_database() -> None:
    """Fresh, migrated database before anything connects (only zk_e2e* names are ever dropped)."""
    from e2e_database import main as recreate_and_migrate

    os.environ["ZK_E2E_DATABASE_URL"] = SETTINGS["ZK_DATABASE_URL"]
    recreate_and_migrate()


async def main() -> None:
    os.environ.update(SETTINGS)
    os.chdir(Path(__file__).resolve().parents[2])  # repository root: no developer .env is read
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import uvicorn

    from zoikorum import worker

    server = uvicorn.Server(uvicorn.Config("zoikorum.main:app", host="127.0.0.1", port=PORT, log_level="warning"))
    await asyncio.gather(server.serve(), worker.run(poll_seconds=0.2))


if __name__ == "__main__":
    prepare_database()
    asyncio.run(main())
