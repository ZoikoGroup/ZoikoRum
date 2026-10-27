from __future__ import annotations

import uuid
from typing import Literal

from datetime import datetime

from fastapi import APIRouter, Query, Response, status

from zoikorum.domains.dispute import service
from zoikorum.domains.dispute.schemas import (
    AgreementIn, AppealIn, AppealDecisionIn, LegalHoldIn, ArbitrationAwardIn, ArbitrationReferIn, AssignIn, ClarificationIn, DecisionIn, DisputeIn,
    DisputeOut, EvidenceIn, RecommendationIn, ReportSubscriptionIn, ResolutionIn,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.http import Page
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


@router.get(f"{D}/dashboard")
async def dashboard(orgId: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """Members of a buyer organisation: open and closed disputes, time to resolution, repeat disputes per professional
    and money frozen per currency."""
    return await service.dashboard(session, actor, orgId)


@router.get(f"{D}/reports/subscription")
async def report_subscription(orgId: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict | None:
    """Organisation Admin: my scheduled dispute report, or null when I have not opted in."""
    from zoikorum.domains.dispute import reports
    return await reports.get_subscription(session, actor, orgId)


@router.put(f"{D}/reports/subscription")
async def set_report_subscription(body: ReportSubscriptionIn, actor: CurrentActor, session: DbSession) -> dict | None:
    """Organisation Admin: opt in to a weekly or monthly dispute report (notified with a CSV link), or stop it (null)."""
    from zoikorum.domains.dispute import reports
    return await reports.set_subscription(session, actor, body.orgId, body.frequency)


@router.get(f"{D}/reports/export")
async def export_report(orgId: uuid.UUID, actor: CurrentActor, session: DbSession, since: datetime | None = Query(None, alias="from"),
                        until: datetime | None = Query(None, alias="to")) -> Response:
    """Organisation Admin or Legal Reviewer: the organisation's disputes for a period (default the last 30 days) as CSV."""
    from zoikorum.domains.dispute import reports
    data, name = await reports.export_csv(session, actor, orgId, since, until)
    return Response(data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.post(D, response_model=DisputeOut, status_code=status.HTTP_201_CREATED)
async def open_dispute(body: DisputeIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """A party opens a dispute on funded milestones; the money is frozen immediately."""
    return await idem.run(session, actor, lambda: service.open_dispute(session, actor, body), status_code=201)


@router.get(D, response_model=Page[DisputeOut])
async def list_disputes(actor: CurrentActor, session: DbSession, role: Literal["buyer", "professional", "operator"] = "buyer",
                        contractId: uuid.UUID | None = None, cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    """Newest first, one page at a time (follow nextCursor)."""
    return await service.list_disputes(session, actor, role, contractId, cursor, limit)


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
async def propose_decision(case_id: uuid.UUID, body: DecisionIn, actor: CurrentActor, session: DbSession):
    """Mediator proposes a platform decision; a second reviewer with the Legal role must approve it."""
    return await service.propose_decision(session, actor, case_id, body)


@router.post(f"{D}/{{case_id}}/decision/approve", response_model=DisputeOut)
async def approve_decision(case_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.approve_decision(session, actor, case_id))



@router.post(f"{D}/{{case_id}}/evidence/messages", response_model=DisputeOut)
async def import_messages(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    """Add the engagement's conversation (with fingerprints) as evidence."""
    return await service.import_messages(session, actor, case_id)


@router.post(f"{D}/{{case_id}}/clarification", response_model=DisputeOut)
async def clarification(case_id: uuid.UUID, body: ClarificationIn, actor: CurrentActor, session: DbSession):
    """Mediator: ask one side a focused question (at most three per dispute)."""
    return await service.request_clarification(session, actor, case_id, body.to, body.question)


@router.post(f"{D}/{{case_id}}/cooldown", response_model=DisputeOut)
async def cooldown(case_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    """Once per dispute per side: pause the current deadline for 24 hours."""
    return await service.cooldown(session, actor, case_id)



@router.get(f"{D}/{{case_id}}/record")
async def case_record(case_id: uuid.UUID, actor: CurrentActor, session: DbSession, format: Literal["pdf", "json"] = "pdf") -> Response:
    """The whole case as one attested file (PDF or JSON), for the parties, the mediator or an authority. Audited."""
    data, name, media = await service.case_record(session, actor, case_id, format)
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.post(f"{D}/{{case_id}}/arbitration", response_model=DisputeOut)
async def refer_to_arbitration(case_id: uuid.UUID, body: ArbitrationReferIn, actor: CurrentActor, session: DbSession):
    """Mediator: refer the case to an outside arbitrator. Money stays frozen until Legal records the award."""
    return await service.refer_to_arbitration(session, actor, case_id, body)


@router.post(f"{D}/{{case_id}}/arbitration/award", response_model=DisputeOut)
async def record_arbitration_award(case_id: uuid.UUID, body: ArbitrationAwardIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """Legal: record the arbitrator's award; the money moves as awarded."""
    return await idem.run(session, actor, lambda: service.record_arbitration_award(session, actor, case_id, body))


@router.post(f"{D}/{{case_id}}/legal-hold", response_model=DisputeOut)
async def legal_hold(case_id: uuid.UUID, body: LegalHoldIn, actor: CurrentActor, session: DbSession):
    """Legal: keep a record regardless of its retention date (litigation, a regulator's request), or lift the hold."""
    return await service.set_legal_hold(session, actor, case_id, body.hold, body.reason)


@router.get("/v1/admin/disputes/retention")
async def retention_queue(actor: CurrentActor, session: DbSession) -> list[dict]:
    """Legal: closed dispute records due for a retention review, and records on legal hold."""
    return await service.retention_queue(session, actor)


@router.post(f"{D}/{{case_id}}/agreements", response_model=DisputeOut)
async def set_agreement(case_id: uuid.UUID, body: AgreementIn, actor: CurrentActor, session: DbSession):
    """A party agrees to (or withdraws from) an opt-in decision path: a binding mediator recommendation, or a decision by
    the buyer enterprise's admin. It applies only once both parties agree, and cannot change after it is used."""
    return await service.set_agreement(session, actor, case_id, body.kind, body.consent)


@router.post(f"{D}/{{case_id}}/enterprise-decision", response_model=DisputeOut)
async def enterprise_decision(case_id: uuid.UUID, body: RecommendationIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """Organisation Admin of the buyer enterprise (agreed path, never the person who opened the dispute): issue a decision.
    It takes effect after a 7-day challenge period unless a party appeals; money moves only when it does."""
    return await idem.run(session, actor, lambda: service.decide_as_enterprise_admin(session, actor, case_id, body))
