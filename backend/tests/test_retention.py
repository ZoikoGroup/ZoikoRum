"""Evidence retention (shared/retention.py): rules per evidence type and jurisdiction, a dry-run report, and a purge that
removes what is due, never what is under legal hold."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from zoikorum.shared import retention


@pytest.mark.unit
def test_rule_lookup():
    rules = {"verification_document": {"default": 2555, "DE": 1825}, "data_export": {"GB": 30}}
    assert retention.retention_days(rules, "verification_document", "de") == 1825
    assert retention.retention_days(rules, "verification_document", "US") == 2555
    assert retention.retention_days(rules, "data_export", "US") is None  # no default: kept
    assert retention.retention_days(rules, "unknown", "GB") is None


@pytest.fixture
def rules(monkeypatch):
    from zoikorum.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "retention_rules", {"data_export": {"default": 30, "DE": 90}, "test_evidence": {"default": 10}})
    monkeypatch.setattr(s, "retention_purge_enabled", False)
    return s


async def test_report_and_purge_respect_jurisdiction_and_legal_hold(sf, client, make_user, rules, monkeypatch):
    from zoikorum.domains.identity.models import DataRequest
    from zoikorum.shared.storage import get_storage

    now = datetime.now(timezone.utc)
    us, de = await make_user("us-person", country="US"), await make_user("de-person", country="DE")
    storage = get_storage()
    async with sf() as s, s.begin():
        for user in (us, de):
            key = f"privacy/{user.id}/{uuid.uuid4()}.json"
            storage.put(key, b"{}")
            s.add(DataRequest(identity_id=user.id, request_type="ACCESS", status="COMPLETED", export_key=key,
                              completed_at=now - timedelta(days=45)))
    # A second, held source: held files are reported and never removed.
    held_removed = []

    async def held_list(session, before, limit):
        return [retention.RetainedFile("test_evidence", "held/key", None, None, now - timedelta(days=99), True, "Case:1")]

    async def held_forget(session, f):
        held_removed.append(f)

    monkeypatch.setitem(retention._sources, "test_evidence", retention.Source("test_evidence", held_list, held_forget))

    async with sf() as s:
        report = await retention.report(s, now)
    exports = report["types"]["data_export"]
    assert exports["due"] == 1 and exports["byJurisdiction"]["US"]["due"] == 1 and "DE" not in exports["byJurisdiction"]
    assert report["types"]["test_evidence"]["held"] == 1 and report["purgeEnabled"] is False

    async with sf() as s, s.begin():
        dry = await retention.purge(s, now, dry_run=True)
    assert dry["dryRun"] is True
    async with sf() as s, s.begin():
        done = await retention.purge(s, now, dry_run=False)
    assert done == {"dryRun": False, "removed": 1, "heldByLegalHold": 1, "refusedByStorage": 0} and not held_removed
    async with sf() as s:
        from sqlalchemy import select
        rows = {r.identity_id: r for r in (await s.scalars(select(DataRequest))).all()}
    assert rows[us.id].export_key is None and "exportPurgedAt" in rows[us.id].detail
    assert rows[de.id].export_key is not None and storage.get(rows[de.id].export_key) == b"{}"  # DE keeps 90 days
