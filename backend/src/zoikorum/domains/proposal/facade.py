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
