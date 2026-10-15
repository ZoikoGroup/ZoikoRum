"""Operator CLI.

    python -m zoikorum.cli create-admin --email admin@zoikorum.com --name "Platform Admin"
    python -m zoikorum.cli reindex-search      # rebuild the search projection from the owning domains
    python -m zoikorum.cli schema-doc          # regenerate docs/DATABASE_SCHEMA.md from the models
    python -m zoikorum.cli reconcile --day 2026-10-06   # payments reconciliation for one UTC day (default: yesterday)
    python -m zoikorum.cli check-config [--connect]   # is this environment's configuration complete? (no values printed)

The first Platform Admin can only be created here (never over HTTP). The password
is read from a prompt or ZK_ADMIN_PASSWORD - never pass it as an argument.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import getpass
import os

from zoikorum.shared import context
from zoikorum.shared.db import dispose_engine, session_factory


def load_domains() -> None:
    # Imported when a command needs the app, so check-config can report bad settings instead of failing on import.
    from zoikorum.main import load_domains as load

    load()


async def _create_admin(email: str, name: str, country: str, password: str, roles: tuple[str, ...] = ()) -> None:
    from zoikorum.domains.identity import service

    load_domains()
    ctx = context.ExecutionContext(correlation_id=context.new_correlation_id(), actor_id="cli", actor_type="operator")
    with context.use_context(ctx):
        async with session_factory()() as s, s.begin():
            identity = await service.create_platform_admin(s, email, password, name, country, roles)
    await dispose_engine()
    print(f"Platform Admin ready: {identity.email} ({identity.id}). Sign in and enable MFA to use staff tools.")


async def _reindex_search() -> None:
    from zoikorum.domains.search import service

    load_domains()
    ctx = context.ExecutionContext(correlation_id=context.new_correlation_id(), actor_id="cli", actor_type="operator")
    with context.use_context(ctx):
        async with session_factory()() as s, s.begin():
            count = await service.reindex_all(s)
    await dispose_engine()
    print(f"Search index rebuilt for {count} professionals.")


async def _reconcile(day: str | None) -> None:
    from datetime import date, timedelta

    from zoikorum.domains.payments import reconciliation
    from zoikorum.shared import clock

    load_domains()
    target = date.fromisoformat(day) if day else (clock.now() - timedelta(days=1)).date()
    ctx = context.ExecutionContext(correlation_id=context.new_correlation_id(), actor_id="cli", actor_type="operator")
    with context.use_context(ctx):
        async with session_factory()() as s, s.begin():
            batch = await reconciliation.reconcile(s, target, run_by="CLI")
            status, checks = batch.status, batch.checks
    await dispose_engine()
    print(f"Reconciliation {target}: {status}")
    for c in checks:
        print(f"  {'OK ' if c['ok'] else 'BAD'} {c['name']:<12} {c['currency']}  ledger={c['ledger']}  payments={c['payments']}"
              f"  provider={c['provider'] if c['provider'] is not None else '-'}")


async def _db_grants(role: str | None) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from zoikorum.config import get_settings
    from zoikorum.shared import db_grants

    s = get_settings()
    role = role or s.db_app_role
    if not role:
        print("No ZK_DB_APP_ROLE: the app uses the owner account (development). Nothing to do.")
        return
    engine = create_async_engine(s.migration_database_url or s.database_url)
    try:
        async with engine.begin() as conn:
            count = await db_grants.apply(conn, role)
    finally:
        await engine.dispose()
    print(f"Privileges set for {role}: {count} statements (append-only tables: read and insert only).")


async def _rotate_field_keys() -> None:
    """Re-encrypt every stored sensitive value that is not yet on the active key, in small transactions."""
    from sqlalchemy import column as sql_column, select, table as sql_table, update

    from zoikorum.shared.crypto import ENCRYPTED_COLUMNS, active_key_id, decrypt_field, encrypt_field, key_id_of

    target = active_key_id()
    async with session_factory()() as session:
        for table, column in ENCRYPTED_COLUMNS:
            schema, name = table.split(".")
            t = sql_table(name, sql_column("id"), sql_column(column), schema=schema)  # identifiers quoted by SQLAlchemy
            rows = (await session.execute(select(t.c.id, t.c[column]).where(t.c[column].is_not(None)))).all()
            changed = 0
            for row_id, value in rows:
                if key_id_of(value) == target and value.startswith("v2:"):
                    continue
                await session.execute(update(t).where(t.c.id == row_id).values({column: encrypt_field(decrypt_field(value))}))
                changed += 1
            await session.commit()
            print(f"{table}.{column}: {changed} re-encrypted, {len(rows) - changed} already on key {target}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="zoikorum")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ca = sub.add_parser("create-admin", help="create or promote the first Platform Admin")
    ca.add_argument("--email", required=True)
    ca.add_argument("--name", default="Platform Admin")
    ca.add_argument("--country", default="US")
    ca.add_argument("--roles", default="", help="extra staff roles, comma-separated (e.g. COMPLIANCE_OFFICER,MEDIATOR)")
    sub.add_parser("reindex-search", help="rebuild the search projection")
    sd = sub.add_parser("schema-doc", help="write the database schema as Markdown")
    sd.add_argument("--out", default="docs/DATABASE_SCHEMA.md")
    ac = sub.add_parser("api-contract", help="write the API models and their fields for the web app's contract test")
    ac.add_argument("--out", default="../frontend/src/api/contract.json")
    rc = sub.add_parser("reconcile", help="reconcile escrow ledger, payments and provider for one day")
    rc.add_argument("--day", help="YYYY-MM-DD (UTC); default yesterday")
    nk = sub.add_parser("new-field-key", help="make a field encryption data key wrapped by Cloud KMS (prints only the wrapped key)")
    nk.add_argument("--id", required=True, help="a name for the key, e.g. 2026-10")
    sub.add_parser("rotate-field-keys", help="re-encrypt stored sensitive fields with ZK_FIELD_ACTIVE_KEY")
    dg = sub.add_parser("db-grants", help="give the app database user its privileges (append-only tables: read and insert)")
    dg.add_argument("--role", help="the app user (default ZK_DB_APP_ROLE)")
    cc = sub.add_parser("check-config", help="report missing or unreachable services for this environment")
    cc.add_argument("--connect", action="store_true", help="also try the database, Redis, S3 and the email server")
    args = parser.parse_args()
    if args.cmd == "check-config":
        from zoikorum.config_check import run

        raise SystemExit(run(args.connect))
    if args.cmd == "new-field-key":
        from zoikorum.shared.crypto import new_wrapped_key

        wrapped = new_wrapped_key(args.id)
        print("Add to ZK_FIELD_DATA_KEYS (keep the existing entries), then set ZK_FIELD_ACTIVE_KEY to use it:")
        print(json.dumps({args.id: wrapped}))
    if args.cmd == "rotate-field-keys":
        asyncio.run(_rotate_field_keys())
    if args.cmd == "db-grants":
        asyncio.run(_db_grants(args.role))
    if args.cmd == "reconcile":
        asyncio.run(_reconcile(args.day))
    if args.cmd == "reindex-search":
        asyncio.run(_reindex_search())
    if args.cmd == "api-contract":
        from zoikorum.api_contract import render as render_contract

        with open(args.out, "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(render_contract())
        print(f"Wrote {args.out}")
    if args.cmd == "schema-doc":
        from zoikorum.schema_doc import render

        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(render())
        print(f"Wrote {args.out}")
    if args.cmd == "create-admin":
        # Same validation as the API, so the account can actually sign in.
        from email_validator import EmailNotValidError, validate_email

        try:
            args.email = validate_email(args.email, check_deliverability=False).normalized
        except EmailNotValidError as exc:
            raise SystemExit(f"Invalid email: {exc}")
        password = os.environ.get("ZK_ADMIN_PASSWORD") or getpass.getpass("Password (min 12 chars): ")
        if len(password) < 12:
            raise SystemExit("Password must be at least 12 characters")
        roles = tuple(r.strip().upper() for r in args.roles.split(",") if r.strip())
        asyncio.run(_create_admin(args.email, args.name, args.country, password, roles))


if __name__ == "__main__":
    main()
