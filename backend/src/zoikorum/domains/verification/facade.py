"""Verification facade - read-only interface other domains use."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.verification.models import VerificationCase


@dataclass(frozen=True)
class CheckStatus:
    case_id: uuid.UUID
    verification_type: str  # IDENTITY|CREDENTIAL|JURISDICTION|RESTRICTIONS|BACKGROUND|INSURANCE|FIRM_REGISTRATION
    status: str  # PENDING|IN_REVIEW|NEEDS_INFO|VERIFIED|FAILED|EXPIRED|REVOKED
    label: str  # e.g. "CPA license (California)"
    jurisdiction: str | None
    verified_at: datetime | None
    expires_at: datetime | None
    public_reason: str | None  # plain language when FAILED/NEEDS_INFO
    credential_claim_id: uuid.UUID | None = None  # CREDENTIAL checks: the professional's claim
    specialization: str | None = None  # CREDENTIAL checks: taxonomy slug the credential supports


async def get_checks(session: AsyncSession, subject_type: str, subject_id: uuid.UUID) -> list[CheckStatus]:
    """subject_type: PROFESSIONAL | FIRM. Latest case per (type, credential)."""
    rows = (await session.scalars(select(VerificationCase).where(
        VerificationCase.subject_type == subject_type, VerificationCase.subject_id == subject_id)
        .order_by(VerificationCase.created_at.desc()))).all()
    latest: dict[tuple, VerificationCase] = {}
    for c in rows:  # newest first: the first case seen per key wins
        latest.setdefault((c.verification_type, c.credential_claim_id, c.jurisdiction if c.credential_claim_id is None else None), c)
    return [CheckStatus(c.id, c.verification_type, c.status, c.label, c.jurisdiction, c.verified_at, c.expires_at,
                        c.public_reason, c.credential_claim_id, c.specialization) for c in latest.values()]


async def open_case_counts(session: AsyncSession) -> dict[str, int]:
    """Open checks waiting for people, and how many are past their published service level."""
    from sqlalchemy import func

    from zoikorum.shared import clock

    open_states = ("PENDING", "IN_REVIEW", "NEEDS_INFO")
    total = await session.scalar(select(func.count()).select_from(VerificationCase)
                                 .where(VerificationCase.status.in_(open_states))) or 0
    overdue = await session.scalar(select(func.count()).select_from(VerificationCase).where(
        VerificationCase.status.in_(("PENDING", "IN_REVIEW")), VerificationCase.estimated_completion < clock.now())) or 0
    return {"open": total, "overdue": overdue}
