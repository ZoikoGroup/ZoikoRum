"""Raw DDL that the ORM cannot express. Applied by Alembic and by the test harness.

APPEND_ONLY_TABLES: insert-only tables (EP-05). A trigger rejects UPDATE and
DELETE even for the application role; production also REVOKEs those grants.
Domains add their immutable tables here (audit ledger, escrow ledger, evidence).
"""

from __future__ import annotations

APPEND_ONLY_TABLES: tuple[str, ...] = (
    "audit.audit_records",
    "escrow.ledger_entries",
    "dispute.evidence_items",
    "verification.evidence_items",
    "contract.signatures",
    "messaging.messages",
    "policy.policy_evaluations",
)

PREVENT_MUTATION_FN = """
CREATE OR REPLACE FUNCTION platform.prevent_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'table %.% is append-only (% rejected)', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""


def append_only_trigger(qualified_table: str) -> list[str]:
    schema, table = qualified_table.split(".")
    name = f"trg_{table}_append_only"
    return [
        f"DROP TRIGGER IF EXISTS {name} ON {schema}.{table};",
        f"CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {schema}.{table} "
        f"FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();",
    ]


def all_statements(existing_tables: set[str]) -> list[str]:
    stmts = [PREVENT_MUTATION_FN]
    for t in APPEND_ONLY_TABLES:
        if t in existing_tables:
            stmts.extend(append_only_trigger(t))
    return stmts
