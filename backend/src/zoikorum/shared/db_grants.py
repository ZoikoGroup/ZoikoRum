"""Database privileges for the application user (Handbook: insert-only role for the audit ledger).

Run as the database owner after every migration (``python -m zoikorum.cli db-grants``; the migrate step does it):

* the app user may read and write ordinary tables in every domain schema, and use their sequences;
* on append-only tables (shared/ddl.APPEND_ONLY_TABLES: audit trail, escrow ledger, evidence, signatures, ...) it may
  only read and insert: UPDATE, DELETE and TRUNCATE are revoked, so even a bug or a stolen app password cannot rewrite
  history. Name columns that privacy erasure replaces with "Deleted user" keep a column-level UPDATE (the trigger still
  allows nothing else);
* the app user owns nothing, so it cannot drop tables or disable the protective triggers.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from zoikorum.shared.db import DOMAIN_SCHEMAS
from zoikorum.shared.ddl import APPEND_ONLY_TABLES, NAME_ERASURE_COLUMNS


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def statements(role: str, existing_tables: set[str]) -> list[str]:
    r = _q(role)
    out: list[str] = []  # (platform.alembic_version, read by the startup schema check, is covered below)
    for schema in DOMAIN_SCHEMAS:
        s = _q(schema)
        out += [f"GRANT USAGE ON SCHEMA {s} TO {r}",
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {s} TO {r}",
                f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {s} TO {r}",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {s} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {r}",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {s} GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {r}"]
    for table in APPEND_ONLY_TABLES:
        if table not in existing_tables:
            continue
        schema, name = table.split(".")
        t = f"{_q(schema)}.{_q(name)}"
        out.append(f"REVOKE UPDATE, DELETE, TRUNCATE ON {t} FROM {r}")
        if table in NAME_ERASURE_COLUMNS:
            out.append(f"GRANT UPDATE ({_q(NAME_ERASURE_COLUMNS[table])}) ON {t} TO {r}")
    return out


async def apply(conn: AsyncConnection, role: str) -> int:
    exists = await conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    if not exists:
        raise ValueError(f"Database role {role!r} does not exist; create it first (see backend/deploy/gcp/README.md)")
    rows = await conn.execute(text("SELECT table_schema || '.' || table_name FROM information_schema.tables "
                                   "WHERE table_type = 'BASE TABLE'"))
    stmts = statements(role, {row[0] for row in rows})
    for stmt in stmts:
        await conn.execute(text(stmt))
    return len(stmts)
