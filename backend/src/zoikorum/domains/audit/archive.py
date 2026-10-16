"""Audit archive (Governance: audit records to locked storage after 90 days).

Every day, audit records older than ARCHIVE_AFTER that are not yet archived are written as one gzip'd JSON-lines file to
blob storage, write-once and, where the storage supports it, under a legal hold. The batch's SHA-256 is recorded, so a
later check proves the archive is unchanged and that its records still chain together. The database rows stay: the
audit table is append-only and its hash chain is checked in place.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.audit.models import AuditArchive, AuditRecord
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import NotFound
from zoikorum.shared.relay import schedule_timer
from zoikorum.shared.storage import get_storage

ARCHIVE_AFTER = timedelta(days=90)
BATCH = 50_000
TIMER = "audit.archive"  # daily at 04:00 UTC, re-arms itself
FIELDS = ("seq", "id", "source_event_id", "action", "actor_id", "actor_type", "auth_strength", "object_type", "object_id", "tenant_id",
          "correlation_id", "causation_id", "policy_version", "evidence_hash", "details", "occurred_at", "prev_hash", "hash")


def _next_run(now: datetime) -> datetime:
    run = datetime.combine(now.date(), time(4, 0), tzinfo=timezone.utc)
    return run if run > now else run + timedelta(days=1)


async def bootstrap(session: AsyncSession) -> None:
    nxt = _next_run(clock.now())
    await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)


def _line(r: AuditRecord) -> dict:
    return {f: (str(getattr(r, f)) if isinstance(getattr(r, f), (uuid.UUID, datetime)) else getattr(r, f)) for f in FIELDS}


async def archive_due(session: AsyncSession, *, rearm: bool = True) -> AuditArchive | None:
    last = await session.scalar(select(func.max(AuditArchive.to_seq))) or 0
    rows = (await session.scalars(select(AuditRecord).where(AuditRecord.seq > last, AuditRecord.occurred_at < clock.now() - ARCHIVE_AFTER)
                                  .order_by(AuditRecord.seq).limit(BATCH))).all()
    archive = None
    if rows:
        body = gzip.compress("\n".join(json.dumps(_line(r), sort_keys=True, default=str) for r in rows).encode(), mtime=0)
        digest = hashlib.sha256(body).hexdigest()
        key = f"audit-archive/{clock.now():%Y/%m/%d}/{rows[0].seq:012d}-{rows[-1].seq:012d}.jsonl.gz"
        storage = get_storage()
        version = storage.put(key, body)
        locked = False
        if hasattr(storage, "legal_hold") and version:
            storage.legal_hold(key, version, True)
            locked = True
        archive = AuditArchive(from_seq=rows[0].seq, to_seq=rows[-1].seq, record_count=len(rows), sha256=digest, object_key=key,
                               version_id=version, locked=locked)
        session.add(archive)
        await session.flush()
    if rearm:
        nxt = _next_run(clock.now())
        await schedule_timer(session, TIMER, nxt.date().isoformat(), nxt)
    return archive


def _out(a: AuditArchive) -> dict:
    return {"id": a.id, "fromSeq": a.from_seq, "toSeq": a.to_seq, "records": a.record_count, "sha256": a.sha256, "objectKey": a.object_key,
            "locked": a.locked, "archivedAt": a.created_at, "lastVerifiedAt": a.last_verified_at}


async def list_archives(session: AsyncSession, actor: Actor) -> list[dict]:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN, PlatformRole.LEGAL, PlatformRole.RISK_LEAD)
    return [_out(a) for a in (await session.scalars(select(AuditArchive).order_by(AuditArchive.to_seq.desc()).limit(200))).all()]


async def verify(session: AsyncSession, actor: Actor, archive_id: uuid.UUID) -> dict:
    """Read the archive back: its SHA-256 must match, and each record must chain to the one before it."""
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN, PlatformRole.LEGAL, PlatformRole.RISK_LEAD)
    a = await session.get(AuditArchive, archive_id, with_for_update=True)
    if a is None:
        raise NotFound("Archive not found")
    body = get_storage().get(a.object_key, a.version_id)
    problems = []
    if body is None:
        problems.append("The archive file is missing")
    elif hashlib.sha256(body).hexdigest() != a.sha256:
        problems.append("The archive file has changed since it was written")
    else:
        lines = [json.loads(x) for x in gzip.decompress(body).decode().splitlines() if x]
        if len(lines) != a.record_count:
            problems.append("The number of records differs")
        for prev, cur in zip(lines, lines[1:]):
            if cur["prev_hash"] != prev["hash"]:
                problems.append(f"The chain breaks at record {cur['seq']}")
                break
    if not problems:
        a.last_verified_at = clock.now()
    await session.flush()
    return {**_out(a), "ok": not problems, "problems": problems}
