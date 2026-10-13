"""Dispute facade - CONTRACT. Signatures and DTOs are fixed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.dispute.models import DisputeCase


@dataclass(frozen=True)
class DisputeSummary:
    id: uuid.UUID
    contract_id: uuid.UUID
    milestone_ids: tuple[uuid.UUID, ...]
    category: str
    status: str
    initiated_by_identity_id: uuid.UUID | None  # None for automated platform triggers


def _summary(c: DisputeCase) -> DisputeSummary:
    return DisputeSummary(c.id, c.contract_id, tuple(uuid.UUID(m) for m in c.milestone_ids), c.category, c.status, c.initiated_by)


async def get_dispute(session: AsyncSession, dispute_id: uuid.UUID) -> DisputeSummary | None:
    c = await session.get(DisputeCase, dispute_id)
    return _summary(c) if c else None


async def open_disputes_for_contract(session: AsyncSession, contract_id: uuid.UUID) -> list[DisputeSummary]:
    from zoikorum.domains.dispute.service import open_for_contract

    return [_summary(c) for c in await open_for_contract(session, contract_id)]


async def outcome_stats(session: AsyncSession, professional_id: uuid.UUID) -> dict:
    from sqlalchemy import select
    rows = (await session.scalars(select(DisputeCase).where(DisputeCase.professional_id == professional_id,
                                                          DisputeCase.status.in_(("DECIDED", "ENFORCED", "CLOSED"))))).all()
    return {"resolvedDisputedContracts": len({r.contract_id for r in rows}),
            "adverseOutcomes": len({r.contract_id for r in rows if (r.decision or {}).get("outcome") in ("FULL_REFUND", "PARTIAL_REFUND", "TERMINATION")})}


async def assistance_evidence(session: AsyncSession, dispute_id: uuid.UUID, reviewer_id: uuid.UUID) -> dict | None:
    from sqlalchemy import select
    from zoikorum.domains.dispute.models import EvidenceItem
    c = await session.get(DisputeCase, dispute_id)
    if not c or c.mediator_identity_id != reviewer_id:
        return None
    evidence = (await session.scalars(select(EvidenceItem).where(EvidenceItem.case_id == c.id))).all()
    return {"reference": c.reference, "category": c.category, "summary": c.summary, "context": c.context,
            "evidence": [{"id": str(e.id), "party": e.party, "type": e.evidence_type, "description": e.description,
                          "files": [{"name": f["name"], "sha256": f["sha256"]} for f in e.items]} for e in evidence]}
