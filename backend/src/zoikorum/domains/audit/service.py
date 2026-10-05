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
from zoikorum.shared.auth import Actor, OrgRole, PlatformRole
from zoikorum.shared.crypto import canonical_json, sha256_hex
from zoikorum.shared.errors import Forbidden, NotFound, ValidationFailed
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
    if actor.has_platform_role(PlatformRole.COMPLIANCE_OFFICER, PlatformRole.LEGAL, PlatformRole.PLATFORM_ADMIN):
        return
    if tenant_id and actor.has_org_role(tenant_id, OrgRole.ORG_ADMIN, OrgRole.LEGAL_REVIEWER):
        return
    raise Forbidden("Audit exports require compliance, legal, or organization-admin authority")


async def query(
    session: AsyncSession, actor: Actor, *, tenant_id: str | None, object_type: str | None,
    object_id: str | None, correlation_id: str | None, since: datetime | None, until: datetime | None,
    limit: int = 1000,
) -> list[AuditRecord]:
    _authorise_scope(actor, tenant_id)
    if not any([tenant_id, object_id, correlation_id]) and not actor.is_operator:
        raise ValidationFailed("Provide tenantId, objectId or correlationId")
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
    return list((await session.scalars(stmt.order_by(AuditRecord.seq).limit(min(limit, 50_000)))).all())


def record_to_dict(r: AuditRecord) -> dict:
    d = _row_material(r)
    d.update({"id": str(r.id), "seq": r.seq, "prevHash": r.prev_hash, "hash": r.hash})
    return d


async def create_export(session: AsyncSession, actor: Actor, scope: dict, fmt: str) -> ExportJob:
    if fmt not in ("json", "csv"):
        raise ValidationFailed("format must be json or csv")
    rows = await query(
        session, actor, tenant_id=scope.get("tenantId"), object_type=scope.get("objectType"),
        object_id=scope.get("objectId"), correlation_id=scope.get("correlationId"),
        since=scope.get("since"), until=scope.get("until"), limit=50_000,
    )
    records = [record_to_dict(r) for r in rows]
    if fmt == "json":
        content = json.dumps({"records": records, "attestation": {"recordCount": len(records)}}, default=str)
    else:
        buf = io.StringIO()
        cols = ["seq", "id", "occurredAt", "action", "actorId", "actorType", "authStrength", "objectType",
                "objectId", "tenantId", "correlationId", "causationId", "policyVersion", "evidenceHash", "hash"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
        content = buf.getvalue()
    job = ExportJob(
        requested_by=actor.identity_id,
        scope={k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in scope.items()},
        status="COMPLETED",
        format=fmt,
        record_count=len(records),
        content=content,
        content_sha256=sha256_hex(content),
        chain_head_hash=records[-1]["hash"] if records else None,
    )
    session.add(job)
    await session.flush()
    record_event(session, E.AUDIT_EXPORT_REQUESTED, aggregate_type="AuditExport", aggregate_id=job.id,
                 payload={"exportId": job.id, "scope": job.scope, "format": fmt, "recordCount": len(records)},
                 tenant_id=scope.get("tenantId"))
    return job


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
