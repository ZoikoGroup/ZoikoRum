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
    "verification.provider_events",
    "contract.signatures",
    "contract.contract_revisions",
    "messaging.messages",
    "messaging.attachments",
    "policy.policy_evaluations",
    "policy.approval_votes",
    "notification.delivery_attempts",
    "review.reviews",
    "ai.inference_logs",
)

PREVENT_MUTATION_FN = """
CREATE OR REPLACE FUNCTION platform.prevent_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'table %.% is append-only (% rejected)', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""

POLICY_VERSION_GUARD = """
CREATE OR REPLACE FUNCTION policy.guard_active_version() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' OR OLD.status = 'ACTIVE' THEN
    RAISE EXCEPTION 'active policy versions are immutable' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CHANGE_ORDER_GUARD = """
CREATE OR REPLACE FUNCTION contract.guard_change_order_history() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'change orders are append-only';
  END IF;
  IF OLD.contract_id IS DISTINCT FROM NEW.contract_id
     OR OLD.proposed_by_identity_id IS DISTINCT FROM NEW.proposed_by_identity_id
     OR OLD.proposer_party IS DISTINCT FROM NEW.proposer_party
     OR OLD.change_type IS DISTINCT FROM NEW.change_type
     OR OLD.delta IS DISTINCT FROM NEW.delta
     OR OLD.impact IS DISTINCT FROM NEW.impact
     OR OLD.base_contract_version IS DISTINCT FROM NEW.base_contract_version
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'change order proposal details are immutable';
  END IF;
  IF OLD.status = 'PROPOSED' THEN
    IF NEW.status NOT IN ('APPROVED', 'REJECTED')
       OR NEW.decided_by_identity_id IS NULL
       OR NEW.decided_at IS NULL
       OR (NEW.status = 'REJECTED' AND NEW.applied_version IS NOT NULL)
       OR (NEW.applied_version IS NOT NULL AND NEW.applied_version <= NEW.base_contract_version) THEN
      RAISE EXCEPTION 'invalid change order decision transition';
    END IF;
  ELSIF OLD.status = 'APPROVED' AND OLD.applied_version IS NULL THEN
    IF NEW.status <> 'APPROVED'
       OR NEW.applied_version IS NULL
       OR NEW.applied_version <= NEW.base_contract_version
       OR NEW.decided_by_identity_id IS DISTINCT FROM OLD.decided_by_identity_id
       OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
       OR NEW.decision_reason IS DISTINCT FROM OLD.decision_reason THEN
      RAISE EXCEPTION 'invalid change order execution transition';
    END IF;
  ELSE
    RAISE EXCEPTION 'change order decisions are final';
  END IF;
  RETURN NEW;
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
    if "ai.prompt_versions" in existing_tables:
        stmts.extend(["""CREATE OR REPLACE FUNCTION ai.guard_prompt() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR (OLD.status <> 'DRAFT' AND (NEW.prompt_key IS DISTINCT FROM OLD.prompt_key
             OR NEW.version IS DISTINCT FROM OLD.version OR NEW.instructions IS DISTINCT FROM OLD.instructions
             OR NEW.golden_tests IS DISTINCT FROM OLD.golden_tests OR NEW.target_model IS DISTINCT FROM OLD.target_model
             OR NEW.approved_by IS DISTINCT FROM OLD.approved_by OR NEW.status <> 'RETIRED')) THEN
             RAISE EXCEPTION 'approved prompt versions are immutable';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;""",
        "DROP TRIGGER IF EXISTS trg_prompt_immutable ON ai.prompt_versions;",
        "CREATE TRIGGER trg_prompt_immutable BEFORE UPDATE OR DELETE ON ai.prompt_versions FOR EACH ROW EXECUTE FUNCTION ai.guard_prompt();"])
    if "dispute.cases" in existing_tables:
        stmts.extend(["""CREATE OR REPLACE FUNCTION dispute.guard_decision() RETURNS trigger AS $$
        BEGIN
          IF OLD.decision IS NOT NULL AND NEW.decision IS DISTINCT FROM OLD.decision THEN
            RAISE EXCEPTION 'issued dispute decisions are immutable';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;""",
        "DROP TRIGGER IF EXISTS trg_decision_immutable ON dispute.cases;",
        "CREATE TRIGGER trg_decision_immutable BEFORE UPDATE ON dispute.cases FOR EACH ROW EXECUTE FUNCTION dispute.guard_decision();"])
    if "dispute.appeals" in existing_tables:
        stmts.extend(["""CREATE OR REPLACE FUNCTION dispute.guard_appeal() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR OLD.status <> 'PENDING' OR NEW.case_id IS DISTINCT FROM OLD.case_id
            OR NEW.submitted_by IS DISTINCT FROM OLD.submitted_by OR NEW.grounds IS DISTINCT FROM OLD.grounds
            OR NEW.explanation IS DISTINCT FROM OLD.explanation OR NEW.evidence IS DISTINCT FROM OLD.evidence THEN
            RAISE EXCEPTION 'appeal submissions and issued decisions are immutable';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;""",
        "DROP TRIGGER IF EXISTS trg_appeal_immutable ON dispute.appeals;",
        "CREATE TRIGGER trg_appeal_immutable BEFORE UPDATE OR DELETE ON dispute.appeals FOR EACH ROW EXECUTE FUNCTION dispute.guard_appeal();"])
    if "policy.versions" in existing_tables:
        stmts.extend([POLICY_VERSION_GUARD,
            "DROP TRIGGER IF EXISTS trg_policy_versions_immutable ON policy.versions;",
            "CREATE TRIGGER trg_policy_versions_immutable BEFORE UPDATE OR DELETE ON policy.versions "
            "FOR EACH ROW EXECUTE FUNCTION policy.guard_active_version();"])
    for t in APPEND_ONLY_TABLES:
        if t in existing_tables:
            stmts.extend(append_only_trigger(t))
    if "contract.change_orders" in existing_tables:
        stmts.extend(
            [
                CHANGE_ORDER_GUARD,
                "DROP TRIGGER IF EXISTS trg_change_orders_append_only ON contract.change_orders;",
                "CREATE TRIGGER trg_change_orders_append_only BEFORE UPDATE OR DELETE ON contract.change_orders "
                "FOR EACH ROW EXECUTE FUNCTION contract.guard_change_order_history();",
            ]
        )
    return stmts
