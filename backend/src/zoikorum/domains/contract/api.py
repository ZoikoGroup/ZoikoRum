from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from zoikorum.domains.contract import service
from zoikorum.domains.contract.schemas import ContractOut, ContractSummaryOut, PartialOfferIn, RevisionIn, SignIn, SubmitIn
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.http import Page
from zoikorum.shared.idempotency import IdempotencyKey
from zoikorum.shared.uploads import file_response

router = APIRouter(tags=["contracts"])
Role = Literal["buyer", "professional"]


@router.get("/v1/contracts", response_model=Page[ContractOut])
async def list_contracts(actor: CurrentActor, session: DbSession, role: Role = "buyer", status_: str | None = Query(default=None, alias="status"),
                         cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    return await service.list_contracts(session, actor, role, status_, cursor, limit)


@router.get("/v1/contracts/summary", response_model=ContractSummaryOut)
async def summary(actor: CurrentActor, session: DbSession, role: Role = "buyer"):
    return await service.summary(session, actor, role)


@router.get("/v1/contracts/{contract_id}", response_model=ContractOut)
async def get_contract(contract_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_contract(session, actor, contract_id)


@router.get("/v1/contracts/{contract_id}/document", response_class=PlainTextResponse)
async def document(contract_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    """The full agreement text. Every read is recorded in the audit log."""
    text, sha = await service.get_document(session, actor, contract_id)
    return PlainTextResponse(text, headers={"X-Document-SHA256": sha})


@router.get("/v1/contracts/{contract_id}/files/{sha256}")
async def delivered_file(contract_id: uuid.UUID, sha256: str, actor: CurrentActor, session: DbSession) -> Response:
    """Opens a file the professional delivered with a milestone. Audited."""
    return file_response(*await service.submission_file(session, actor, contract_id, sha256))


@router.post("/v1/contracts/{contract_id}/sign", response_model=ContractOut)
async def sign(contract_id: uuid.UUID, body: SignIn, request: Request, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """Buyer signs first, then the professional countersigns. Needs a fresh two-step confirmation."""
    ip = request.client.host if request.client else None
    return await idem.run(session, actor, lambda: service.sign(session, actor, contract_id, body, ip))


@router.post("/v1/milestones/{milestone_id}/submit", response_model=ContractOut)
async def submit(milestone_id: uuid.UUID, body: SubmitIn, actor: CurrentActor, session: DbSession):
    return await service.submit_milestone(session, actor, milestone_id, body)


@router.post("/v1/milestones/{milestone_id}/accept", response_model=ContractOut)
async def accept(milestone_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.accept_milestone(session, actor, milestone_id))


class CancelCyclesIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/v1/contracts/{contract_id}/cancel-remaining-cycles", response_model=ContractOut)
async def cancel_remaining_cycles(contract_id: uuid.UUID, body: CancelCyclesIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """Retainers: the buyer cancels the cycles that have not been funded yet. Funded cycles are unaffected."""
    return await idem.run(session, actor, lambda: service.cancel_remaining_cycles(session, actor, contract_id, body.reason))


@router.post("/v1/milestones/{milestone_id}/partial-acceptance", response_model=ContractOut)
async def offer_partial(milestone_id: uuid.UUID, body: PartialOfferIn, actor: CurrentActor, session: DbSession):
    """Buyer: offer to accept submitted work for less (with a reason). Released only if the professional agrees."""
    return await service.offer_partial_acceptance(session, actor, milestone_id, body)


@router.post("/v1/milestones/{milestone_id}/partial-acceptance/{answer}", response_model=ContractOut)
async def answer_partial(milestone_id: uuid.UUID, answer: Literal["agree", "decline"], actor: CurrentActor, session: DbSession,
                         idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.answer_partial_acceptance(session, actor, milestone_id, answer == "agree"))


@router.post("/v1/milestones/{milestone_id}/request-revision", response_model=ContractOut)
async def request_revision(milestone_id: uuid.UUID, body: RevisionIn, actor: CurrentActor, session: DbSession):
    return await service.request_revision(session, actor, milestone_id, body)
