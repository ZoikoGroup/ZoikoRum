from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Response, status

from zoikorum.domains.dispute import service
from zoikorum.domains.dispute.schemas import AppealIn, AppealDecisionIn, AssignIn, DisputeIn, DisputeOut, EvidenceIn, RecommendationIn, ResolutionIn
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.idempotency import IdempotencyKey
from zoikorum.shared.uploads import file_response

router = APIRouter(tags=["disputes"])
D = "/v1/disputes"


@router.get(f"{D}/{{case_id}}/appeal")
async def get_appeal(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_appeal(session, actor, case_id)


@router.post(f"{D}/{{case_id}}/appeal", status_code=201)
async def file_appeal(case_id: uuid.UUID, body: AppealIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.file_appeal(session, actor, case_id, body), status_code=201)


@router.post(f"{D}/{{case_id}}/appeal/decision")
async def decide_appeal(case_id: uuid.UUID, body: AppealDecisionIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.decide_appeal(session, actor, case_id, body))


@router.get(f"{D}/{{case_id}}/appeal/files/{{sha256}}")
async def appeal_file(case_id: uuid.UUID, sha256: str, actor: CurrentActor, session: DbSession):
    return file_response(*await service.appeal_file(session, actor, case_id, sha256))


@router.post(D, response_model=DisputeOut, status_code=status.HTTP_201_CREATED)
async def open_dispute(body: DisputeIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """A party opens a dispute on funded milestones; the money is frozen immediately."""
    return await idem.run(session, actor, lambda: service.open_dispute(session, actor, body), status_code=201)


@router.get(D, response_model=list[DisputeOut])
async def list_disputes(actor: CurrentActor, session: DbSession, role: Literal["buyer", "professional", "operator"] = "buyer",
                        contractId: uuid.UUID | None = None):
    return await service.list_disputes(session, actor, role, contractId)


@router.get(f"{D}/{{case_id}}", response_model=DisputeOut)
async def get_dispute(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_dispute(session, actor, case_id)


@router.get(f"{D}/{{case_id}}/files/{{sha256}}")
async def evidence_file(case_id: uuid.UUID, sha256: str, actor: CurrentActor, session: DbSession) -> Response:
    """Opens an evidence file (both parties, mediator, legal). Audited."""
    return file_response(*await service.evidence_file(session, actor, case_id, sha256))


@router.post(f"{D}/{{case_id}}/evidence", response_model=DisputeOut)
async def add_evidence(case_id: uuid.UUID, body: EvidenceIn, actor: CurrentActor, session: DbSession):
    return await service.add_evidence(session, actor, case_id, body)


@router.post(f"{D}/{{case_id}}/evidence/complete", response_model=DisputeOut)
async def evidence_complete(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.evidence_complete(session, actor, case_id)


@router.post(f"{D}/{{case_id}}/resolution-proposals", response_model=DisputeOut)
async def propose(case_id: uuid.UUID, body: ResolutionIn, actor: CurrentActor, session: DbSession):
    return await service.propose(session, actor, case_id, body)


@router.post("/v1/resolution-proposals/{proposal_id}/accept", response_model=DisputeOut)
async def accept_proposal(proposal_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.respond(session, actor, proposal_id, True))


@router.post("/v1/resolution-proposals/{proposal_id}/reject", response_model=DisputeOut)
async def reject_proposal(proposal_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.respond(session, actor, proposal_id, False)


@router.post(f"{D}/{{case_id}}/escalate", response_model=DisputeOut)
async def escalate(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.escalate(session, actor, case_id)


@router.post(f"{D}/{{case_id}}/assign-mediator", response_model=DisputeOut)
async def assign_mediator(case_id: uuid.UUID, body: AssignIn, actor: CurrentActor, session: DbSession):
    return await service.assign_mediator(session, actor, case_id, body)


@router.post(f"{D}/{{case_id}}/recommendation", response_model=DisputeOut)
async def recommend(case_id: uuid.UUID, body: RecommendationIn, actor: CurrentActor, session: DbSession):
    return await service.recommend(session, actor, case_id, body)


@router.post(f"{D}/{{case_id}}/recommendation/accept", response_model=DisputeOut)
async def accept_recommendation(case_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.answer_recommendation(session, actor, case_id, True))


@router.post(f"{D}/{{case_id}}/recommendation/reject", response_model=DisputeOut)
async def reject_recommendation(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.answer_recommendation(session, actor, case_id, False)


@router.post(f"{D}/{{case_id}}/decision", response_model=DisputeOut)
async def propose_decision(case_id: uuid.UUID, body: RecommendationIn, actor: CurrentActor, session: DbSession):
    """Mediator proposes a platform decision; a second reviewer with the Legal role must approve it."""
    return await service.propose_decision(session, actor, case_id, body)


@router.post(f"{D}/{{case_id}}/decision/approve", response_model=DisputeOut)
async def approve_decision(case_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.approve_decision(session, actor, case_id))
