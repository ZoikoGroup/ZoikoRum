from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from zoikorum.domains.admin.facade import ApprovalRequestOut

from zoikorum.domains.audit import service
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.db import DbSession

router = APIRouter(prefix="/v1/audit", tags=["audit"])


class ExportIn(BaseModel):
    tenantId: str | None = None
    objectType: str | None = None
    objectId: str | None = None
    correlationId: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    format: Literal["json", "csv", "pdf"] = "json"
    # Staff exports only: why the export is needed, for the Compliance Officer or Legal who approves it.
    justification: str | None = Field(default=None, min_length=10, max_length=2000)


class ExportOut(BaseModel):
    id: uuid.UUID
    status: str
    format: str
    recordCount: int | None
    contentSha256: str | None
    chainHeadHash: str | None
    createdAt: datetime


def _out(job) -> ExportOut:
    return ExportOut(id=job.id, status=job.status, format=job.format, recordCount=job.record_count,
                     contentSha256=job.content_sha256, chainHeadHash=job.chain_head_hash, createdAt=job.created_at)


@router.get("/records")
async def list_records(
    actor: CurrentActor,
    session: DbSession,
    tenantId: str | None = None,
    objectType: str | None = None,
    objectId: str | None = None,
    correlationId: str | None = None,
    limit: int = Query(default=200, le=1000),
    newestFirst: bool = False,  # activity feeds: latest records first
) -> dict:
    rows = await service.query(session, actor, tenant_id=tenantId, object_type=objectType, object_id=objectId,
                               correlation_id=correlationId, since=None, until=None, limit=limit, newest_first=newestFirst)
    return {"items": [service.record_to_dict(r) for r in rows]}


@router.post("/exports", response_model=ExportOut | ApprovalRequestOut, status_code=status.HTTP_201_CREATED,
             responses={202: {"model": ApprovalRequestOut, "description": "Staff export requested: it is made only once "
                              "a Compliance Officer or Legal (not the requester) approves the approval request returned."}})
async def create_export(body: ExportIn, actor: CurrentActor, session: DbSession, response: Response):
    """An organisation admin's export of their organisation's trail: made at once (201). A staff export: 202 with an
    approval request (status REQUESTED); the export itself (GET /v1/audit/exports/{payload.exportId}) stays REQUESTED
    until a second person approves it, then COMPLETED."""
    scope = body.model_dump(exclude={"format", "justification"}, exclude_none=True)
    result = await service.create_export(session, actor, scope, body.format, body.justification)
    if isinstance(result, dict):
        response.status_code = status.HTTP_202_ACCEPTED
        return result
    return _out(result)


@router.get("/exports/{export_id}", response_model=ExportOut)
async def get_export(export_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> ExportOut:
    return _out(await service.get_export(session, actor, export_id))


@router.get("/exports/{export_id}/download")
async def download_export(export_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> Response:
    job = await service.get_export(session, actor, export_id)
    if job.status != "COMPLETED":
        from zoikorum.shared.errors import Conflict
        raise Conflict("This export has not been made: it is waiting for approval or was not approved", code="EXPORT_NOT_READY")
    headers = {"X-Content-SHA256": job.content_sha256 or ""}
    if job.format == "pdf":
        return Response(content=service.render_export_pdf(job), media_type="application/pdf", headers=headers)
    media = "application/json" if job.format == "json" else "text/csv"
    return Response(content=job.content or "", media_type=media, headers=headers)


@router.post("/chain/verify")
async def verify_chain(actor: CurrentActor, session: DbSession) -> dict:
    actor.require_capability(Cap.AUDIT_CHAIN_VERIFY)
    return await service.verify_chain(session)
