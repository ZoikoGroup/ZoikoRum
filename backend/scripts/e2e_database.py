"""Fresh database for the browser tests (frontend/e2e): drop, create, migrate.

    python backend/scripts/e2e_database.py            # uses ZK_E2E_DATABASE_URL or the default below

Safety: only databases whose name starts with "zk_e2e" are ever dropped, so this can never touch the development
or test databases. The admin connection uses the same server and credentials as the URL, on the "postgres" database.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

DEFAULT = "postgresql+asyncpg://zoikorum:zoikorum@localhost:5434/zk_e2e"
BACKEND = Path(__file__).resolve().parents[1]


async def recreate(url: str) -> None:
    base, name = url.rsplit("/", 1)
    if not name.startswith("zk_e2e"):
        sys.exit(f"Refusing to drop {name!r}: browser-test databases must be named zk_e2e*")
    admin = await asyncpg.connect(base.replace("postgresql+asyncpg://", "postgresql://") + "/postgres")
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


def main() -> None:
    url = os.environ.get("ZK_E2E_DATABASE_URL", DEFAULT)
    asyncio.run(recreate(url))
    env = {**os.environ, "ZK_DATABASE_URL": url, "ZK_ENV": "local"}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
                   stdout=subprocess.DEVNULL)
    print(f"browser-test database ready: {url.rsplit('/', 1)[1]}")


if __name__ == "__main__":
    main()
