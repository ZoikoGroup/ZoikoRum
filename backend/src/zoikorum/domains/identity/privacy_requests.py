"""Privacy requests: download my data (ACCESS) and delete my account (ERASURE) - Regulator pack s.9, GDPR art. 15/17.

ACCESS: RECEIVED -> COMPLETED. The worker builds one JSON file from every domain (shared/privacy.py), stores it, and the
owner downloads it with a fresh two-step check for ``ZK_DATA_EXPORT_DAYS``; every download is audited.
ERASURE: needs a fresh two-step check (a stolen session must not delete an account), then SCHEDULED for
``ZK_ERASURE_COOLING_OFF_DAYS`` and cancellable until then (the person is emailed). When it is due: if anything is still
open (engagement, dispute, money on its way, sole administrator of a team) -> BLOCKED with the reasons; otherwise every
domain erases or anonymises its data, the account is anonymised last, and the request is COMPLETED.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.identity.models import DataRequest, Identity
from zoikorum.domains.identity.schemas import DataRequestOut
from zoikorum.shared import clock, privacy
from zoikorum.shared.auth import Actor
from zoikorum.shared.errors import Conflict, NotFound
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.relay import cancel_timer, schedule_timer
from zoikorum.shared.storage import get_storage

TIMER_ERASURE = "identity.erasure_due"
OPEN = {"ACCESS": ("RECEIVED",), "ERASURE": ("SCHEDULED",)}


def out(r: DataRequest) -> DataRequestOut:
    now = clock.now()
    return DataRequestOut(
        id=r.id, requestType=r.request_type, status=r.status, createdAt=r.created_at, completedAt=r.completed_at,
        scheduledFor=r.scheduled_for, expiresAt=r.expires_at,
        downloadable=bool(r.request_type == "ACCESS" and r.status == "COMPLETED" and r.export_key and r.expires_at and r.expires_at > now),
        reasons=list((r.detail or {}).get("reasons", [])),
        retained=privacy.retention_notes() if r.request_type == "ERASURE" else {})


def _evt(session: AsyncSession, event_type: str, r: DataRequest, **extra) -> None:
    record_event(session, event_type, aggregate_type="DataRequest", aggregate_id=r.id,
                 payload={"identityId": r.identity_id, "dataRequestId": r.id, "requestType": r.request_type, **extra})


async def create(session: AsyncSession, actor: Actor, request_type: str) -> DataRequestOut:
    if request_type == "ERASURE":
        actor.require_step_up()
    identity = await session.get(Identity, actor.identity_id, with_for_update=True)  # one request at a time per person
    if identity is None:
        raise NotFound("Account not found")
    existing = await session.scalar(select(DataRequest).where(
        DataRequest.identity_id == identity.id, DataRequest.request_type == request_type,
        DataRequest.status.in_(OPEN[request_type])))
    if existing:
        return out(existing)
    now = clock.now()
    r = DataRequest(identity_id=identity.id, request_type=request_type, detail={},
                    status="SCHEDULED" if request_type == "ERASURE" else "RECEIVED")
    if request_type == "ERASURE":
        r.scheduled_for = now + timedelta(days=get_settings().erasure_cooling_off_days)
    session.add(r)
    await session.flush()
    if request_type == "ERASURE":
        await schedule_timer(session, TIMER_ERASURE, str(r.id), r.scheduled_for, {"dataRequestId": str(r.id)})
    _evt(session, E.DATA_REQUEST_CREATED, r, scheduledFor=r.scheduled_for)
    return out(r)


async def mine(session: AsyncSession, actor: Actor) -> list[DataRequestOut]:
    rows = (await session.scalars(select(DataRequest).where(DataRequest.identity_id == actor.identity_id)
                                  .order_by(DataRequest.created_at.desc()))).all()
    return [out(r) for r in rows]


async def _own(session: AsyncSession, actor: Actor, request_id: uuid.UUID, lock: bool = False) -> DataRequest:
    r = await session.get(DataRequest, request_id, with_for_update=lock)
    if r is None or r.identity_id != actor.identity_id:
        raise NotFound("Request not found")
    return r


async def cancel(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> DataRequestOut:
    r = await _own(session, actor, request_id, lock=True)
    if r.request_type != "ERASURE" or r.status != "SCHEDULED":
        raise Conflict("Only a scheduled account deletion can be cancelled", code="NOT_CANCELLABLE")
    r.status, r.completed_at = "CANCELLED", clock.now()
    await cancel_timer(session, TIMER_ERASURE, str(r.id))
    _evt(session, E.DATA_REQUEST_CANCELLED, r)
    return out(r)


async def download(session: AsyncSession, actor: Actor, request_id: uuid.UUID) -> tuple[bytes, str]:
    actor.require_step_up()  # the file holds everything about the person
    r = await _own(session, actor, request_id)
    if r.request_type != "ACCESS" or r.status != "COMPLETED" or not r.export_key:
        raise Conflict("This export is not ready yet", code="EXPORT_NOT_READY")
    if r.expires_at is None or r.expires_at <= clock.now():
        raise Conflict("This export has expired. Ask for a new one.", code="EXPORT_EXPIRED")
    data = get_storage().get(r.export_key)
    if data is None:
        raise NotFound("Export file not found", code="EXPORT_MISSING")
    record_audit(session, "identity.data_export.downloaded", object_type="DataRequest", object_id=r.id,
                 tenant_id=r.identity_id)
    return data, f"zoikorum-data-{r.created_at:%Y-%m-%d}.json"


async def build_export(session: AsyncSession, request_id: uuid.UUID) -> None:
    """Worker: consumer of DATA_REQUEST_CREATED for ACCESS requests. Idempotent."""
    r = await session.get(DataRequest, request_id, with_for_update=True)
    if r is None or r.request_type != "ACCESS" or r.status != "RECEIVED":
        return
    now = clock.now()
    body = {"generatedAt": now.isoformat(), "format": "zoikorum-personal-data/1",
            "about": "Everything Zoikorum holds about your account, grouped by area. Uploaded documents are listed "
                     "by name and fingerprint; ask support for copies.",
            "keptByLaw": privacy.retention_notes(),
            "data": await privacy.export_all(session, r.identity_id)}
    key = f"privacy/{r.identity_id}/{r.id}.json"
    get_storage().put(key, json.dumps(body, indent=2, ensure_ascii=False, default=str).encode())
    r.export_key, r.status, r.completed_at = key, "COMPLETED", now
    r.expires_at = now + timedelta(days=get_settings().data_export_days)
    _evt(session, E.DATA_REQUEST_COMPLETED, r, expiresAt=r.expires_at)


async def run_erasure(session: AsyncSession, payload: dict) -> None:
    """Timer: the cooling-off period is over. Late or repeated timers do nothing."""
    r = await session.get(DataRequest, uuid.UUID(payload["dataRequestId"]), with_for_update=True)
    if r is None or r.request_type != "ERASURE" or r.status != "SCHEDULED":
        return
    reasons = await privacy.erasure_blockers(session, r.identity_id)
    now = clock.now()
    if reasons:
        r.status, r.completed_at, r.detail = "BLOCKED", now, {"reasons": reasons}
        _evt(session, E.DATA_REQUEST_BLOCKED, r, reasons=reasons)
        return
    summary = await privacy.erase_all(session, r.identity_id, last="identity")
    r.status, r.completed_at, r.detail = "COMPLETED", now, {"summary": summary}
    _evt(session, E.DATA_REQUEST_COMPLETED, r)
    record_audit(session, "identity.account.erased", object_type="Identity", object_id=r.identity_id,
                 tenant_id=r.identity_id, details={"dataRequestId": str(r.id), "areas": sorted(summary)})
