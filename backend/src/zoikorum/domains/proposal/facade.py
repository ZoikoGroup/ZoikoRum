"""Proposal facade - CONTRACT. Signatures and DTOs are fixed; implement bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


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
    raise NotImplementedError


async def get_proposal(session: AsyncSession, proposal_id: uuid.UUID) -> ProposalSummary | None:
    raise NotImplementedError
