"""The app's database user may add to append-only tables but never change or delete them (Handbook: insert-only role
for the audit ledger); ordinary tables stay writable; privacy name erasure keeps its one column."""

from __future__ import annotations

from sqlalchemy import text

from zoikorum.shared import db_grants

ROLE = "zk_grants_test_app"


async def test_append_only_tables_are_read_and_insert_only_for_the_app_user(engine):
    async with engine.begin() as conn:
        await conn.execute(text(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') "
                                f"THEN CREATE ROLE {ROLE} NOLOGIN; END IF; END $$"))
        assert await db_grants.apply(conn, ROLE) > 20

        async def can(table, privilege):
            return await conn.scalar(text("SELECT has_table_privilege(:r, :t, :p)"), {"r": ROLE, "t": table, "p": privilege})

        for table in ("audit.audit_records", "escrow.ledger_entries", "contract.signatures"):
            assert await can(table, "SELECT") and await can(table, "INSERT")
            assert not await can(table, "UPDATE") and not await can(table, "DELETE") and not await can(table, "TRUNCATE")
        assert await can("contract.contracts", "UPDATE") and await can("identity.identities", "DELETE")
        assert await conn.scalar(text("SELECT has_column_privilege(:r, 'review.reviews', 'reviewer_name', 'UPDATE')"), {"r": ROLE})
        assert not await conn.scalar(text("SELECT has_column_privilege(:r, 'review.reviews', 'rating', 'UPDATE')"), {"r": ROLE})
        owner = await conn.scalar(text("SELECT tableowner FROM pg_tables WHERE schemaname = 'audit' AND tablename = 'audit_records'"))
        assert owner != ROLE  # it cannot drop the table or switch its trigger off
