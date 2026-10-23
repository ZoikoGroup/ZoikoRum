"""Evidence retention: how long each kind of stored file is kept, per jurisdiction, and the job that removes it after.

Rules are configuration (ZK_RETENTION_RULES, decided by Legal), in days per evidence type and country with a
"default", e.g. ``{"data_export": {"default": 30}, "verification_document": {"default": 2555, "DE": 1825}}``. An
evidence type with no rule is kept indefinitely; a country without its own entry uses the type's "default" (no default:
kept).

Domains own their files, so each registers a *source* for its evidence types (``register_source``): a function listing
stored files older than a date (key, version, country, stored at, legal hold) and one that forgets a purged file in its
own records. The shared kernel never reads domain tables.

* ``report`` (``python -m zoikorum.cli retention-report``): what is due, per type and country, without changing anything;
* ``purge``: removes what is due. Files under legal hold are never removed (they are counted as held). The daily job
  (05:00 UTC) only reports until ZK_RETENTION_PURGE_ENABLED is on. Every removal is in the audit trail.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.shared import clock
from zoikorum.shared.events import record_audit
from zoikorum.shared.relay import on_timer, schedule_timer

log = logging.getLogger("zoikorum.retention")
TIMER = "platform.retention"
BATCH = 500


@dataclass(frozen=True)
class RetainedFile:
    evidence_type: str
    key: str
    version_id: str | None
    jurisdiction: str | None  # ISO country code
    stored_at: datetime
    legal_hold: bool
    ref: str  # the owning record, e.g. "DataRequest:<id>" (for the report and the audit trail; no personal data)


Lister = Callable[[AsyncSession, datetime, int], Awaitable[list[RetainedFile]]]
Forget = Callable[[AsyncSession, RetainedFile], Awaitable[None]]


@dataclass(frozen=True)
class Source:
    evidence_type: str
    list_older_than: Lister
    forget: Forget


_sources: dict[str, Source] = {}


def register_source(evidence_type: str, list_older_than: Lister, forget: Forget) -> None:
    _sources[evidence_type] = Source(evidence_type, list_older_than, forget)


def sources() -> dict[str, Source]:
    return dict(_sources)


def retention_days(rules: dict[str, dict[str, int]], evidence_type: str, jurisdiction: str | None) -> int | None:
    """Days to keep a file of this type from this country; None: keep (no rule)."""
    rule = rules.get(evidence_type)
    if not rule:
        return None
    return rule.get((jurisdiction or "").upper(), rule.get("default"))


def _shortest(rules: dict[str, dict[str, int]], evidence_type: str) -> int | None:
    days = [d for d in (rules.get(evidence_type) or {}).values() if d is not None]
    return min(days) if days else None


async def _due(session: AsyncSession, now: datetime) -> list[tuple[RetainedFile, int]]:
    rules = get_settings().retention_rules or {}
    out = []
    for evidence_type, source in sorted(_sources.items()):
        shortest = _shortest(rules, evidence_type)
        if shortest is None:
            continue
        for f in await source.list_older_than(session, now - timedelta(days=shortest), BATCH):
            days = retention_days(rules, evidence_type, f.jurisdiction)
            if days is not None and f.stored_at <= now - timedelta(days=days):
                out.append((f, days))
    return out


async def report(session: AsyncSession, now: datetime | None = None) -> dict:
    """What a purge would do now, per evidence type and jurisdiction. Changes nothing."""
    now = now or clock.now()
    rules = get_settings().retention_rules or {}
    types: dict[str, dict] = {t: {"rule": rules.get(t), "due": 0, "held": 0, "byJurisdiction": {}, "examples": []}
                              for t in sorted(set(_sources) | set(rules))}
    for f, days in await _due(session, now):
        t = types[f.evidence_type]
        slot = t["byJurisdiction"].setdefault(f.jurisdiction or "default", {"due": 0, "held": 0, "days": days})
        bucket = "held" if f.legal_hold else "due"
        t[bucket] += 1
        slot[bucket] += 1
        if len(t["examples"]) < 20:
            t["examples"].append({"ref": f.ref, "storedAt": f.stored_at.isoformat(), "legalHold": f.legal_hold})
    unregistered = sorted(set(rules) - set(_sources))
    return {"at": now.isoformat(), "purgeEnabled": get_settings().retention_purge_enabled, "types": types,
            "rulesWithoutSource": unregistered}


async def purge(session: AsyncSession, now: datetime | None = None, *, dry_run: bool = True) -> dict:
    """Remove the files whose retention ended (never under legal hold). dry_run: report only."""
    from zoikorum.shared.storage import get_storage

    now = now or clock.now()
    if dry_run:
        return {"dryRun": True, **await report(session, now)}
    removed, held, failed = 0, 0, 0
    storage = get_storage()
    for f, days in await _due(session, now):
        if f.legal_hold:
            held += 1
            continue
        try:
            purge_file = getattr(storage, "purge_for_retention")
            purge_file(f.key, f.version_id)
        except Exception:  # noqa: BLE001 - e.g. object lock still running: keep the record, try again tomorrow
            failed += 1
            log.warning("retention purge refused by storage", extra={"fields": {"ref": f.ref, "type": f.evidence_type}})
            continue
        await _sources[f.evidence_type].forget(session, f)
        ref_type, _, ref_id = f.ref.partition(":")
        record_audit(session, "storage.retention.purged", object_type=ref_type or "StoredFile", object_id=ref_id or f.key,
                     details={"ref": f.ref, "evidenceType": f.evidence_type, "jurisdiction": f.jurisdiction, "retentionDays": days,
                              "storedAt": f.stored_at.isoformat()})
        removed += 1
    log.info("retention purge", extra={"fields": {"removed": removed, "held": held, "failed": failed}})
    return {"dryRun": False, "removed": removed, "heldByLegalHold": held, "refusedByStorage": failed}


def next_run(now: datetime) -> datetime:
    """Daily at 05:00 UTC."""
    today = datetime.combine(now.date(), time(5, 0), tzinfo=timezone.utc)
    return today if now < today else today + timedelta(days=1)


async def bootstrap(session: AsyncSession) -> None:
    nxt = next_run(clock.now())
    await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)


@on_timer(TIMER)
async def _daily(session: AsyncSession, key: str, payload: dict) -> None:
    result = await purge(session, dry_run=not get_settings().retention_purge_enabled)
    if result.get("dryRun"):
        due = sum(t["due"] for t in result["types"].values())
        log.info("retention report (purge switched off)", extra={"fields": {"due": due}})
    nxt = next_run(clock.now())
    await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)  # re-arms itself
