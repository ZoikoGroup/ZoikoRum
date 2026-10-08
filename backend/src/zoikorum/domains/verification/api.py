from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Request, Response, status

from zoikorum.domains.verification import service
from zoikorum.domains.verification.schemas import CaseIn, CaseOut, DecisionIn, EvidenceIn, QueueItemOut, RevokeIn
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.http import Page

router = APIRouter(prefix="/v1/verification", tags=["verification"])


@router.get("/configuration")
async def provider_configuration(actor: CurrentActor):
    from zoikorum.domains.verification.integration import configuration
    return configuration()


@router.post("/cases/{case_id}/hosted-session")
async def hosted_session(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    from zoikorum.domains.verification.integration import hosted
    return await hosted(session, actor, case_id)


@router.post("/webhooks/persona")
async def persona_receipt(request: Request, session: DbSession):
    from zoikorum.domains.verification.integration import receipt
    return await receipt(session, request.headers.get("persona-signature"), await request.body())


@router.post("/cases", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def start_case(body: CaseIn, actor: CurrentActor, session: DbSession):
    return await service.start_case(session, actor, body)


@router.get("/cases/{case_id}", response_model=CaseOut)
async def get_case(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_case(session, actor, case_id)


@router.post("/cases/{case_id}/evidence", response_model=CaseOut)
async def add_evidence(case_id: uuid.UUID, body: EvidenceIn, actor: CurrentActor, session: DbSession):
    return await service.add_evidence(session, actor, case_id, body)


@router.get("/evidence/{evidence_id}/file")
async def evidence_file(evidence_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> Response:
    """Opens an uploaded document (owner or reviewer). Audited; never cached; shown in a sandbox."""
    data, content_type, name = await service.evidence_file(session, actor, evidence_id)
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._- ")[:120] or "document"
    return Response(data, media_type=content_type, headers={
        "Content-Disposition": f'inline; filename="{safe}"', "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.get("/subjects/{subject_type}/{subject_id}", response_model=list[CaseOut])
async def subject_cases(subject_type: Literal["PROFESSIONAL", "FIRM"], subject_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.subject_cases(session, actor, subject_type, subject_id)


@router.get("/review-queue", response_model=Page[QueueItemOut])
async def review_queue(actor: CurrentActor, session: DbSession, cursor: str | None = None,
                       limit: int | None = Query(default=None, ge=1, le=100),
                       status_: Literal["PENDING", "IN_REVIEW", "NEEDS_INFO"] | None = Query(default=None, alias="status")):
    """Compliance officers: open checks, newest first. Each item shows whether its SLA is overdue."""
    return await service.review_queue(session, actor, cursor, limit, status_)


@router.post("/cases/{case_id}/decision", response_model=CaseOut)
async def decide(case_id: uuid.UUID, body: DecisionIn, actor: CurrentActor, session: DbSession):
    return await service.decide(session, actor, case_id, body)


@router.post("/cases/{case_id}/revoke", response_model=CaseOut)
async def revoke(case_id: uuid.UUID, body: RevokeIn, actor: CurrentActor, session: DbSession):
    return await service.revoke(session, actor, case_id, body)
