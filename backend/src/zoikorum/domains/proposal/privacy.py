"""Requests the person sent and proposals they wrote (shared/privacy.py). Kept with the engagement record."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.proposal.models import Proposal, ProposalRequest
from zoikorum.shared import privacy


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    pro = await professional_facade.get_professional_by_identity(session, identity_id)
    return {"requestsSent": await privacy.rows(session, ProposalRequest, ProposalRequest.buyer_identity_id == identity_id),
            "requestsReceived": await privacy.rows(session, ProposalRequest, ProposalRequest.professional_id == pro.id) if pro else [],
            "proposalsWritten": await privacy.rows(session, Proposal, Proposal.professional_id == pro.id) if pro else []}


privacy.register("proposal", export=export,
                 retained="Requests and proposals that led to an engagement, with the contract record.")
