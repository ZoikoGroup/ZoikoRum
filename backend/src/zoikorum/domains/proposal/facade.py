"""Proposal facade - CONTRACT. Signatures and DTOs are fixed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.proposal.models import Proposal, ProposalRequest


@dataclass(frozen=True)
class RequestSummary:
    id: uuid.UUID
    organization_id: uuid.UUID
    buyer_identity_id: uuid.UUID
    professional_id: uuid.UUID
    offering_id: uuid.UUID | None
    engagement_type: str
    status: str
    nda_required: bool


@dataclass(frozen=True)
class ProposalSummary:
    id: uuid.UUID
    request_id: uuid.UUID
    organization_id: uuid.UUID
    buyer_identity_id: uuid.UUID
    professional_id: uuid.UUID
    status: str
    total_minor: int
    currency: str
    policy_version_id: uuid.UUID | None


async def get_request(session: AsyncSession, request_id: uuid.UUID) -> RequestSummary | None:
    r = await session.get(ProposalRequest, request_id)
    if r is None:
        return None
    return RequestSummary(id=r.id, organization_id=r.organization_id, buyer_identity_id=r.buyer_identity_id,
                          professional_id=r.professional_id, offering_id=r.offering_id, engagement_type=r.engagement_type,
                          status=r.status, nda_required=r.nda_required)


async def get_proposal(session: AsyncSession, proposal_id: uuid.UUID) -> ProposalSummary | None:
    p = await session.get(Proposal, proposal_id)
    if p is None:
        return None
    return ProposalSummary(id=p.id, request_id=p.request_id, organization_id=p.organization_id,
                           buyer_identity_id=p.buyer_identity_id, professional_id=p.professional_id, status=p.status,
                           total_minor=p.total_minor, currency=p.currency, policy_version_id=None)


async def response_stats(session: AsyncSession, professional_id: uuid.UUID) -> dict[str, float | int | None]:
    """How quickly a professional answers requests (first proposal sent, or a decline), for the public profile."""
    from statistics import median

    from sqlalchemy import select

    reqs = (await session.scalars(select(ProposalRequest).where(
        ProposalRequest.professional_id == professional_id, ProposalRequest.sent_at.is_not(None)))).all()
    if not reqs:
        return {"requests": 0, "responded": 0, "medianHours": None}
    sent = {r.id: r.sent_at for r in reqs}
    first = {p.request_id: p.submitted_at for p in (await session.scalars(select(Proposal).where(
        Proposal.request_id.in_(list(sent)), Proposal.submitted_at.is_not(None)))).all()}
    hours = []
    for r in reqs:
        answered = first.get(r.id) or (r.closed_at if r.status == "DECLINED" else None)
        if answered:
            hours.append(max(0.0, (answered - r.sent_at).total_seconds() / 3600))
    return {"requests": len(reqs), "responded": len(hours), "medianHours": round(median(hours), 1) if hours else None}
