import uuid
from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from zoikorum.domains.ai import service
from zoikorum.domains.ai.models import PromptVersion, InferenceLog
from zoikorum.domains.proposal import facade as proposal
from zoikorum.domains.professional import facade as professional
from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.contract import facade as contract
from zoikorum.domains.dispute import facade as dispute
from zoikorum.shared.auth import CurrentActor, PlatformRole
from zoikorum.shared.db import DbSession
from zoikorum.shared.errors import NotFound, Conflict
from zoikorum.shared.idempotency import IdempotencyKey
from zoikorum.shared.events import record_audit

router = APIRouter(prefix="/v1/ai", tags=["AI assistance"])


class RequestIn(BaseModel):
    requestId: uuid.UUID


class ContractIn(BaseModel):
    contractId: uuid.UUID


class DisputeIn(BaseModel):
    disputeId: uuid.UUID


class GoldenTest(BaseModel):
    input: str = Field(min_length=1, max_length=10000)
    mustContain: list[str] = Field(min_length=1, max_length=20)


class PromptIn(BaseModel):
    promptKey: Literal["proposal-draft", "contract-summary", "dispute-summary", "match-intent"]
    targetModel: str = Field(min_length=3, max_length=100)
    instructions: str = Field(min_length=30, max_length=10000)
    goldenTests: list[GoldenTest] = Field(min_length=1, max_length=20)


@router.post("/proposal-draft")
async def proposal_draft(body: RequestIn, actor: CurrentActor, session: DbSession):
    r = await proposal.get_request(session, body.requestId)
    pro = await professional.get_professional(session, r.professional_id) if r else None
    if not pro or pro.identity_id != actor.identity_id:
        raise NotFound("Request not found")
    facts = await proposal.assistance_brief(session, r.id)
    if facts["ndaRequired"] and not facts["ndaAccepted"]:
        raise Conflict("Accept the NDA before using request details", code="NDA_REQUIRED")
    fallback = f"Proposal working draft for {facts['service']}\nObjective: {facts['objective']}\nScope: {facts['details']}\nDuration: {facts['duration']}\nConfirm deliverables, exclusions, fees and milestone dates before submitting."
    return await service.infer(session, actor.identity_id, "proposal-draft", r.id, facts, fallback)


@router.post("/contract-summary")
async def contract_summary(body: ContractIn, actor: CurrentActor, session: DbSession):
    c = await contract.get_contract(session, body.contractId)
    pro = await professional.get_professional(session, c.professional_id) if c else None
    if not c or (not await buyer.get_member_roles(session, c.organization_id, actor.identity_id) and (not pro or pro.identity_id != actor.identity_id)):
        raise NotFound("Contract not found")
    facts = await contract.assistance_terms(session, c.id)
    fallback = f"{c.reference}, version {c.contract_version}\nValue: {c.currency} {c.total_minor / 100:.2f}\n" + "\n".join(f"Milestone {m.sequence}: {m.title}; {m.currency} {m.amount_minor / 100:.2f}; due {m.due_date or 'not specified'}" for m in c.milestones)
    return {**await service.infer(session, actor.identity_id, "contract-summary", c.id, facts, fallback), "documentHash": c.terms_hash}


@router.post("/dispute-summary")
async def dispute_summary(body: DisputeIn, actor: CurrentActor, session: DbSession):
    actor.require_platform_role(PlatformRole.MEDIATOR)
    facts = await dispute.assistance_evidence(session, body.disputeId, actor.identity_id)
    if not facts:
        raise NotFound("Assigned dispute not found")
    record_audit(session, "ai.dispute.evidence.read", object_type="DisputeCase", object_id=body.disputeId)
    fallback = f"{facts['reference']}: {facts['category']}\nReported issue: {facts['summary']}\n" + "\n".join(f"Evidence {e['id']} ({e['party']}): {e['description']}" for e in facts["evidence"]) + "\nNo outcome is recommended by this summary."
    return await service.infer(session, actor.identity_id, "dispute-summary", body.disputeId, facts, fallback)


@router.get("/prompts")
async def prompts(actor: CurrentActor, session: DbSession):
    actor.require_platform_role(PlatformRole.AI_SAFETY_REVIEWER)
    return [service.prompt_out(p) for p in (await session.scalars(select(PromptVersion).order_by(PromptVersion.prompt_key, PromptVersion.version.desc()))).all()]


@router.post("/prompts", status_code=201)
async def create_prompt(body: PromptIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.create_prompt(session, actor, body), status_code=201)


@router.post("/prompts/{prompt_id}/approve")
async def approve_prompt(prompt_id: uuid.UUID, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.approve_prompt(session, actor, prompt_id))


@router.post("/prompts/{prompt_id}/retire")
async def retire_prompt(prompt_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    actor.require_platform_role(PlatformRole.AI_SAFETY_REVIEWER); actor.require_step_up()
    p = await session.get(PromptVersion, prompt_id, with_for_update=True)
    if not p:
        raise NotFound("Prompt not found")
    p.status = "RETIRED"
    record_audit(session, "ai.prompt.retired", object_type="PromptVersion", object_id=p.id)
    return service.prompt_out(p)


@router.get("/inferences")
async def inferences(actor: CurrentActor, session: DbSession):
    actor.require_platform_role(PlatformRole.AI_SAFETY_REVIEWER)
    rows = (await session.scalars(select(InferenceLog).order_by(InferenceLog.created_at.desc()).limit(100))).all()
    # Outputs remain within the subject's access scope; governance sees metadata only.
    return [{"id": r.id, "purpose": r.purpose, "model": r.model, "promptVersion": r.prompt_version,
             "inputHash": r.input_sha256, "fallbackUsed": r.fallback_used, "latencyMs": r.latency_ms, "createdAt": r.created_at} for r in rows]
