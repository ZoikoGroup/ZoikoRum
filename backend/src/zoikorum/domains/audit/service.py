"""Audit ledger: append with hash chaining, chain verification, exports."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.audit.models import AuditRecord, ExportJob
from zoikorum.shared.auth import Actor, OrgRole
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.crypto import canonical_json, sha256_hex
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, record_audit, record_event

GENESIS = "0" * 64
_CHAIN_LOCK = 7_301_001  # pg advisory lock key serialising chain appends

# Never audit audit's own bookkeeping events (would loop forever).
_SKIP = {E.AUDIT_EXPORT_COMPLETED, E.HASH_CHAIN_VALIDATED}


def _material(r: dict) -> bytes:
    return canonical_json(r)


def _record_dict(env: EventEnvelope) -> dict:
    explicit = env.eventType == E.AUDIT_ENTRY_REQUESTED
    return {
        "sourceEventId": str(env.eventId),
        "action": env.payload.get("action") if explicit else env.eventType,
        "actorId": env.metadata.actorId,
        "actorType": env.metadata.actorType,
        "authStrength": env.metadata.authStrength,
        "objectType": env.aggregateType,
        "objectId": env.aggregateId,
        "tenantId": env.tenantId,
        "correlationId": env.correlationId,
        "causationId": env.causationId,
        "policyVersion": env.metadata.policyVersion,
        "evidenceHash": env.payload.get("evidenceHash") if explicit else None,
        "details": env.payload.get("details", {}) if explicit else env.payload,
        "occurredAt": env.occurredAt.isoformat(),
    }


async def append(session: AsyncSession, env: EventEnvelope) -> AuditRecord | None:
    if env.eventType in _SKIP:
        return None
    if await session.scalar(select(AuditRecord.id).where(AuditRecord.source_event_id == env.eventId)):
        return None
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK})
    prev = await session.scalar(select(AuditRecord.hash).order_by(AuditRecord.seq.desc()).limit(1)) or GENESIS
    rec = _record_dict(env)
    digest = sha256_hex(prev.encode() + _material(rec))
    row = AuditRecord(
        source_event_id=env.eventId,
        action=rec["action"],
        actor_id=rec["actorId"],
        actor_type=rec["actorType"],
        auth_strength=rec["authStrength"],
        object_type=rec["objectType"],
        object_id=rec["objectId"],
        tenant_id=rec["tenantId"],
        correlation_id=rec["correlationId"],
        causation_id=rec["causationId"],
        policy_version=rec["policyVersion"],
        evidence_hash=rec["evidenceHash"],
        details=rec["details"],
        occurred_at=env.occurredAt,
        prev_hash=prev,
        hash=digest,
    )
    session.add(row)
    await session.flush()
    return row


def _row_material(r: AuditRecord) -> dict:
    return {
        "sourceEventId": str(r.source_event_id),
        "action": r.action,
        "actorId": r.actor_id,
        "actorType": r.actor_type,
        "authStrength": r.auth_strength,
        "objectType": r.object_type,
        "objectId": r.object_id,
        "tenantId": r.tenant_id,
        "correlationId": r.correlation_id,
        "causationId": r.causation_id,
        "policyVersion": r.policy_version,
        "evidenceHash": r.evidence_hash,
        "details": r.details,
        "occurredAt": r.occurred_at.isoformat(),
    }


async def verify_chain(session: AsyncSession, batch: int = 5000) -> dict:
    """Recompute every hash in order. Any mismatch => HashChainBroken (P0)."""
    prev = GENESIS
    last_seq = 0
    checked = 0
    while True:
        rows = (
            await session.scalars(
                select(AuditRecord).where(AuditRecord.seq > last_seq).order_by(AuditRecord.seq).limit(batch)
            )
        ).all()
        if not rows:
            break
        for r in rows:
            expected = sha256_hex(prev.encode() + _material(_row_material(r)))
            if r.prev_hash != prev or r.hash != expected:
                record_event(session, E.HASH_CHAIN_BROKEN, aggregate_type="AuditChain", aggregate_id="global",
                             payload={"brokenAtSeq": r.seq, "recordId": r.id})
                return {"valid": False, "checked": checked, "brokenAtSeq": r.seq}
            prev = r.hash
            last_seq = r.seq
            checked += 1
    return {"valid": True, "checked": checked, "headHash": prev}


def _authorise_scope(actor: Actor, tenant_id: str | None) -> None:
    if actor.has_capability(Cap.AUDIT_RECORDS_READ):
        # Same rule as every staff tool: staff read the audit trail only with two-step verification on.
        actor.require_capability(Cap.AUDIT_RECORDS_READ)
        return
    if tenant_id and actor.has_org_role(tenant_id, OrgRole.ORG_ADMIN, OrgRole.LEGAL_REVIEWER):
        return
    raise Forbidden("Audit exports require compliance, legal, or organization-admin authority")


async def query(
    session: AsyncSession, actor: Actor, *, tenant_id: str | None, object_type: str | None,
    object_id: str | None, correlation_id: str | None, since: datetime | None, until: datetime | None,
    limit: int = 1000, newest_first: bool = False,
) -> list[AuditRecord]:
    _authorise_scope(actor, tenant_id)
    if not any([tenant_id, object_id, correlation_id]) and not actor.is_operator:
        raise ValidationFailed("Provide tenantId, objectId or correlationId")
    return await _select(session, tenant_id=tenant_id, object_type=object_type, object_id=object_id,
                         correlation_id=correlation_id, since=since, until=until, limit=limit, newest_first=newest_first)


async def _select(session: AsyncSession, *, tenant_id, object_type, object_id, correlation_id, since, until, limit,
                  newest_first=False) -> list[AuditRecord]:
    stmt = select(AuditRecord)
    if tenant_id:
        stmt = stmt.where(AuditRecord.tenant_id == tenant_id)
    if object_type:
        stmt = stmt.where(AuditRecord.object_type == object_type)
    if object_id:
        stmt = stmt.where(AuditRecord.object_id == object_id)
    if correlation_id:
        stmt = stmt.where(AuditRecord.correlation_id == correlation_id)
    if since:
        stmt = stmt.where(AuditRecord.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditRecord.occurred_at < until)
    order = AuditRecord.seq.desc() if newest_first else AuditRecord.seq
    return list((await session.scalars(stmt.order_by(order).limit(min(limit, 50_000)))).all())


def record_to_dict(r: AuditRecord) -> dict:
    d = _row_material(r)
    d.update({"id": str(r.id), "seq": r.seq, "prevHash": r.prev_hash, "hash": r.hash})
    return d


def _scope_json(scope: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in scope.items()}


def _when(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


async def create_export(session: AsyncSession, actor: Actor, scope: dict, fmt: str, justification: str | None = None):
    """An organisation admin's export of their own organisation's trail is made at once. A staff export (any scope) is
    evidence-grade material: it is only requested here and is made once a second person, a Compliance Officer or Legal,
    approves it (admin/approvals.py). Returns the finished job, or the approval request for a staff export."""
    if fmt not in ("json", "csv", "pdf"):
        raise ValidationFailed("format must be json, csv or pdf")
    if actor.has_capability(Cap.AUDIT_EXPORT):
        from zoikorum.domains.admin import facade as admin_facade

        actor.require_capability(Cap.AUDIT_EXPORT)
        if not justification:
            raise ValidationFailed("Say why the export is needed: a second person approves it", code="JUSTIFICATION_REQUIRED")
        return await admin_facade.request_approval(session, actor, "AUDIT_EXPORT", {"scope": _scope_json(scope), "format": fmt},
                                                   justification)
    rows = await query(
        session, actor, tenant_id=scope.get("tenantId"), object_type=scope.get("objectType"),
        object_id=scope.get("objectId"), correlation_id=scope.get("correlationId"),
        since=scope.get("since"), until=scope.get("until"), limit=50_000,
    )
    job = ExportJob(requested_by=actor.identity_id, scope=_scope_json(scope), status="REQUESTED", format=fmt)
    session.add(job)
    await session.flush()
    _fill(session, job, rows)
    return job


async def open_export(session: AsyncSession, requested_by: uuid.UUID, scope: dict, fmt: str) -> uuid.UUID:
    """A staff export waiting for approval: recorded now (status REQUESTED), made only when approved."""
    if fmt not in ("json", "csv", "pdf"):
        raise ValidationFailed("format must be json, csv or pdf")
    job = ExportJob(requested_by=requested_by, scope=_scope_json(scope), status="REQUESTED", format=fmt)
    session.add(job)
    await session.flush()
    return job.id


async def complete_export(session: AsyncSession, export_id: uuid.UUID) -> dict:
    """Makes an approved staff export from the scope it was requested with."""
    job = await session.get(ExportJob, export_id, with_for_update=True)
    if job is None or job.status != "REQUESTED":
        raise Conflict("This export is not waiting for approval", code="EXPORT_NOT_REQUESTED")
    s = job.scope
    rows = await _select(session, tenant_id=s.get("tenantId"), object_type=s.get("objectType"), object_id=s.get("objectId"),
                         correlation_id=s.get("correlationId"), since=_when(s.get("since")), until=_when(s.get("until")),
                         limit=50_000)
    _fill(session, job, rows)
    return {"exportId": job.id, "recordCount": job.record_count}


async def close_export(session: AsyncSession, export_id: uuid.UUID, status: str) -> None:
    """A staff export whose approval request was rejected, expired, cancelled or failed is never made."""
    job = await session.get(ExportJob, export_id, with_for_update=True)
    if job is not None and job.status == "REQUESTED":
        job.status = status


def _fill(session: AsyncSession, job: ExportJob, rows: list[AuditRecord]) -> None:
    fmt = job.format
    records = [record_to_dict(r) for r in rows]
    if fmt in ("json", "pdf"):  # a PDF is drawn from these same records when it is downloaded
        content = json.dumps({"records": records, "attestation": {"recordCount": len(records)}}, default=str)
    else:
        buf = io.StringIO()
        cols = ["seq", "id", "occurredAt", "action", "actorId", "actorType", "authStrength", "objectType",
                "objectId", "tenantId", "correlationId", "causationId", "policyVersion", "evidenceHash", "hash"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
        content = buf.getvalue()
    job.status, job.record_count, job.content = "COMPLETED", len(records), content
    job.content_sha256, job.chain_head_hash = sha256_hex(content), records[-1]["hash"] if records else None
    record_event(session, E.AUDIT_EXPORT_REQUESTED, aggregate_type="AuditExport", aggregate_id=job.id,
                 payload={"exportId": job.id, "scope": job.scope, "format": fmt, "recordCount": len(records)},
                 tenant_id=job.scope.get("tenantId"))


def render_export_pdf(job: ExportJob) -> bytes:
    """The PDF of a finished export: a table of the exported records with the attestation (count, SHA-256 of the stored
    records, chain head) in the subtitle. Same permission as the CSV: it is only reachable through get_export."""
    from zoikorum.shared.report_pdf import render_grid_pdf

    records = json.loads(job.content or "{}").get("records", [])
    rows = [{"seq": r.get("seq"), "occurredAt": str(r.get("occurredAt", ""))[:19].replace("T", " "), "action": r.get("action"),
             "actor": str(r.get("actorId") or "-")[:8], "object": f"{r.get('objectType', '')} {str(r.get('objectId', ''))[:8]}",
             "hash": str(r.get("hash", ""))[:12]} for r in records]
    cols = [("#", 16, "R"), ("Time (UTC)", 38, "L"), ("Action", 80, "L"), ("Actor", 24, "L"), ("Object", 70, "L"), ("Hash", 36, "L")]
    sub = f"{len(records)} records · content SHA-256 {(job.content_sha256 or '')[:16]} · chain head {(job.chain_head_hash or '-')[:16]}"
    return render_grid_pdf("Zoikorum audit log", sub, cols, rows, keys=["seq", "occurredAt", "action", "actor", "object", "hash"],
                           empty="No audit records in scope.")


async def get_export(session: AsyncSession, actor: Actor, export_id: uuid.UUID) -> ExportJob:
    job = await session.get(ExportJob, export_id)
    if job is None:
        raise NotFound("Export not found")
    if job.requested_by != actor.identity_id:
        _authorise_scope(actor, job.scope.get("tenantId"))
    # Every access to evidence-grade material is itself audited (Architecture 13.4).
    record_audit(session, "AuditExportDownloaded", object_type="AuditExport", object_id=job.id,
                 details={"by": str(actor.identity_id)}, evidence_hash=job.content_sha256,
                 tenant_id=job.scope.get("tenantId"))
    return job


async def chain_health(session: AsyncSession) -> list[tuple[str, str, float]]:
    """Metrics (shared/metrics.py): how many times the hourly check has found the audit hash chain broken. Any value
    above 0 is a P0 (tampering or corruption); it stays until the chain is investigated and the alert acknowledged.
    A check that stops running shows in zk_timers_oldest_overdue_seconds."""
    from sqlalchemy import func

    breaks = await session.scalar(select(func.count()).select_from(AuditRecord).where(AuditRecord.action == E.HASH_CHAIN_BROKEN))
    return [("zk_audit_chain_breaks", "Times the audit hash-chain check found tampering (must be 0)", float(breaks or 0))]
