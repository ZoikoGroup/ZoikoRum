"""Operator CLI.

    python -m zoikorum.cli create-admin --email admin@zoikorum.com --name "Platform Admin"
    python -m zoikorum.cli reindex-search      # rebuild the search projection from the owning domains

The first Platform Admin can only be created here (never over HTTP). The password
is read from a prompt or ZK_ADMIN_PASSWORD - never pass it as an argument.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os

from zoikorum.main import load_domains
from zoikorum.shared import context
from zoikorum.shared.db import dispose_engine, session_factory


async def _create_admin(email: str, name: str, country: str, password: str) -> None:
    from zoikorum.domains.identity import service

    load_domains()
    ctx = context.ExecutionContext(correlation_id=context.new_correlation_id(), actor_id="cli", actor_type="operator")
    with context.use_context(ctx):
        async with session_factory()() as s, s.begin():
            identity = await service.create_platform_admin(s, email, password, name, country)
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="zoikorum")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ca = sub.add_parser("create-admin", help="create or promote the first Platform Admin")
    ca.add_argument("--email", required=True)
    ca.add_argument("--name", default="Platform Admin")
    ca.add_argument("--country", default="US")
    sub.add_parser("reindex-search", help="rebuild the search projection")
    args = parser.parse_args()
    if args.cmd == "reindex-search":
        asyncio.run(_reindex_search())
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
        asyncio.run(_create_admin(args.email, args.name, args.country, password))


if __name__ == "__main__":
    main()
