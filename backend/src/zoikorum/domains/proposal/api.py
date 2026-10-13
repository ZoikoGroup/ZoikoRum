from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel

from zoikorum.domains.proposal import service
from zoikorum.domains.proposal.schemas import (
    ProposalAttachmentsIn,
    CancelIn, DeclineIn, ProposalIn, ProposalOut, RejectIn, RequestIn, RequestOut, RequestSummaryOut, RevisionIn,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.http import Page
from zoikorum.shared.idempotency import IdempotencyKey
from zoikorum.shared.uploads import file_response

router = APIRouter(tags=["proposals"])
R = "/v1/proposal-requests"
P = "/v1/proposals"
Role = Literal["buyer", "professional"]


class SendIn(BaseModel):
    acknowledged: bool = False


# ---- Requests --------------------------------------------------------------------------

@router.post(R, response_model=list[RequestOut], status_code=status.HTTP_201_CREATED)
async def create_requests(body: RequestIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """Buyer: send one requirement to 1-3 chosen professionals (or save it as a draft)."""
    return await idem.run(session, actor, lambda: service.create_requests(session, actor, body), status_code=201)


@router.get(R, response_model=Page[RequestOut])
async def list_requests(actor: CurrentActor, session: DbSession, role: Role = "buyer", status_: str | None = Query(default=None, alias="status"),
                        cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    return await service.list_requests(session, actor, role, status_, cursor, limit)


@router.get(f"{R}/summary", response_model=RequestSummaryOut)
async def summary(actor: CurrentActor, session: DbSession, role: Role = "buyer"):
    return await service.summary(session, actor, role)


@router.get(f"{R}/{{request_id}}", response_model=RequestOut)
async def get_request(request_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_request(session, actor, request_id)


@router.get(f"{R}/{{request_id}}/attachments/{{sha256}}")
async def attachment(request_id: uuid.UUID, sha256: str, actor: CurrentActor, session: DbSession) -> Response:
    """Opens a request attachment (buyer's organisation, or the professional after any NDA). Audited."""
    return file_response(*await service.attachment_file(session, actor, request_id, sha256))


@router.post(f"{R}/{{request_id}}/send", response_model=list[RequestOut])
async def send(request_id: uuid.UUID, body: SendIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.send_drafts(session, actor, request_id, body.acknowledged))


@router.post(f"{R}/{{request_id}}/cancel", response_model=RequestOut)
async def cancel(request_id: uuid.UUID, body: CancelIn, actor: CurrentActor, session: DbSession):
    return await service.cancel_request(session, actor, request_id, body)


@router.post(f"{R}/{{request_id}}/accept-nda", response_model=RequestOut)
async def accept_nda(request_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.accept_nda(session, actor, request_id)


@router.post(f"{R}/{{request_id}}/decline", response_model=RequestOut)
async def decline(request_id: uuid.UUID, body: DeclineIn, actor: CurrentActor, session: DbSession):
    return await service.decline_request(session, actor, request_id, body)


@router.post(f"{R}/{{request_id}}/proposals", response_model=ProposalOut, status_code=status.HTTP_201_CREATED)
async def create_proposal(request_id: uuid.UUID, body: ProposalIn, actor: CurrentActor, session: DbSession):
    return await service.create_proposal(session, actor, request_id, body)


@router.get(f"{R}/{{request_id}}/proposals", response_model=list[ProposalOut])
async def request_proposals(request_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.request_proposals(session, actor, request_id)


# ---- Proposals -------------------------------------------------------------------------

@router.get(f"{P}/{{proposal_id}}", response_model=ProposalOut)
async def get_proposal(proposal_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_proposal(session, actor, proposal_id)


@router.patch(f"{P}/{{proposal_id}}", response_model=ProposalOut)
async def update_proposal(proposal_id: uuid.UUID, body: ProposalIn, actor: CurrentActor, session: DbSession):
    return await service.update_proposal(session, actor, proposal_id, body)


@router.post(f"{P}/{{proposal_id}}/attachments", response_model=ProposalOut)
async def add_proposal_attachments(proposal_id: uuid.UUID, body: ProposalAttachmentsIn, actor: CurrentActor, session: DbSession):
    """Professional: attach up to 3 files (portfolio items or supporting documents) while drafting or revising."""
    return await service.add_proposal_attachments(session, actor, proposal_id, body)


@router.delete(f"{P}/{{proposal_id}}/attachments/{{sha256}}", response_model=ProposalOut)
async def remove_proposal_attachment(proposal_id: uuid.UUID, sha256: str, actor: CurrentActor, session: DbSession):
    return await service.remove_proposal_attachment(session, actor, proposal_id, sha256)


@router.get(f"{P}/{{proposal_id}}/attachments/{{sha256}}")
async def proposal_attachment(proposal_id: uuid.UUID, sha256: str, actor: CurrentActor, session: DbSession) -> Response:
    """Opens a proposal attachment (the professional, or the buyer's organisation once sent). Audited."""
    return file_response(*await service.proposal_attachment_file(session, actor, proposal_id, sha256))


@router.post(f"{P}/{{proposal_id}}/submit", response_model=ProposalOut)
async def submit(proposal_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.submit_proposal(session, actor, proposal_id))


@router.post(f"{P}/{{proposal_id}}/withdraw", response_model=ProposalOut)
async def withdraw(proposal_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.withdraw_proposal(session, actor, proposal_id)


@router.post(f"{P}/{{proposal_id}}/request-revision", response_model=ProposalOut)
async def request_revision(proposal_id: uuid.UUID, body: RevisionIn, actor: CurrentActor, session: DbSession):
    return await service.request_revision(session, actor, proposal_id, body)


@router.post(f"{P}/{{proposal_id}}/reject", response_model=ProposalOut)
async def reject(proposal_id: uuid.UUID, body: RejectIn, actor: CurrentActor, session: DbSession):
    return await service.reject_proposal(session, actor, proposal_id, body)


@router.post(f"{P}/{{proposal_id}}/accept", response_model=ProposalOut)
async def accept(proposal_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.accept_proposal(session, actor, proposal_id))
