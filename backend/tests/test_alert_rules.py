"""The alert rules only use metrics the API really exports, and every alert has a runbook section."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[1]
RULES = yaml.safe_load((BACKEND / "deploy" / "monitoring" / "alerts.yml").read_text(encoding="utf-8"))
RUNBOOKS = (BACKEND / "docs" / "RUNBOOKS.md").read_text(encoding="utf-8")
SOURCE = "\n".join(p.read_text(encoding="utf-8") for p in (BACKEND / "src").rglob("*.py"))
ALERTS = [rule for group in RULES["groups"] for rule in group["rules"]]


def anchor(heading: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")


@pytest.mark.unit
def test_every_metric_in_an_alert_is_exported():
    used = set()
    for rule in ALERTS:
        used.update(re.findall(r"\bzk_[a-z0-9_]+", rule["expr"]))
    used = {re.sub(r"_(bucket|count|sum)$", "", m) for m in used}
    for metric in used:
        prefix = metric.rstrip("_") if metric.endswith("_") else metric
        assert prefix in SOURCE, f"{metric} is not exported by the API"


@pytest.mark.unit
def test_every_alert_links_an_existing_runbook_section_and_has_a_severity():
    sections = {anchor(h) for h in re.findall(r"^## (.+)$", RUNBOOKS, re.M)}
    for rule in ALERTS:
        assert rule["labels"]["severity"] in ("page", "ticket"), rule["alert"]
        target = rule["annotations"]["runbook"].split("#", 1)[1]
        assert target in sections, f"{rule['alert']} links a missing runbook section: {target}"
