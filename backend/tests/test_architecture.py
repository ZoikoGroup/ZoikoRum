"""Architecture fitness tests - domain boundaries (Architecture 2.2, Handbook 3.3).

A domain may import another domain ONLY through its ``facade`` module.
Shared kernel must never import a domain.
"""

from __future__ import annotations

import ast
from pathlib import Path

from zoikorum.domains import DOMAINS
from zoikorum.shared.db import DOMAIN_SCHEMAS

SRC = Path(__file__).resolve().parents[1] / "src" / "zoikorum"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            # "from zoikorum.domains.x import facade" imports the name, not the package body.
            if len(node.module.split(".")) != 3 or not node.module.startswith("zoikorum.domains."):
                out.append(node.module)
            out += [f"{node.module}.{a.name}" for a in node.names]
    return out


def test_domains_only_import_other_domains_through_facades():
    violations = []
    for d in DOMAINS:
        root = SRC / "domains" / d
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            for mod in _imports(py):
                parts = mod.split(".")
                if len(parts) >= 3 and parts[:2] == ["zoikorum", "domains"] and parts[2] in DOMAINS and parts[2] != d:
                    if len(parts) == 3 or parts[3] != "facade":
                        violations.append(f"{py.relative_to(SRC)} imports {mod}")
    assert not violations, "Cross-domain imports must go through facade:\n" + "\n".join(sorted(set(violations)))


def test_shared_kernel_does_not_depend_on_domains():
    violations = [
        f"{py.relative_to(SRC)} imports {mod}"
        for py in (SRC / "shared").rglob("*.py")
        for mod in _imports(py)
        if mod.startswith("zoikorum.domains")
    ]
    assert not violations, "\n".join(violations)


def test_every_domain_table_lives_in_its_own_schema():
    from zoikorum.main import load_domains
    from zoikorum.shared.db import Base

    load_domains()
    for t in Base.metadata.sorted_tables:
        assert t.schema in DOMAIN_SCHEMAS, f"{t.name} has no domain schema"
        module_domains = {d for d in DOMAINS if t.schema == d}
        assert module_domains or t.schema == "platform", t.fullname
        # No foreign keys across schemas: cross-domain references are plain UUIDs.
        for fk in t.foreign_keys:
            assert fk.column.table.schema == t.schema, f"cross-schema FK {t.fullname} -> {fk.target_fullname}"
