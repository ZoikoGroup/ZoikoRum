"""Verification facade - read-only interface other domains use."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
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
    """subject_type: PROFESSIONAL | FIRM | IDENTITY. Latest case per (type, credential)."""
    rows = (await session.scalars(select(VerificationCase).where(
        VerificationCase.subject_type == subject_type, VerificationCase.subject_id == subject_id)
        .order_by(VerificationCase.created_at.desc()))).all()
    latest: dict[tuple, VerificationCase] = {}
    for c in rows:  # newest first: the first case seen per key wins
        latest.setdefault((c.verification_type, c.credential_claim_id, c.jurisdiction if c.credential_claim_id is None else None), c)
    return [CheckStatus(c.id, c.verification_type, c.status, c.label, c.jurisdiction, c.verified_at, c.expires_at,
                        c.public_reason, c.credential_claim_id, c.specialization) for c in latest.values()]


async def identity_verified(session: AsyncSession, identity_id: uuid.UUID, professional_id: uuid.UUID | None = None) -> bool:
    """Whether a person's identity is verified: their own check, or the identity check on their professional profile."""
    subjects = [(VerificationCase.subject_type == "IDENTITY") & (VerificationCase.subject_id == identity_id)]
    if professional_id:
        subjects.append((VerificationCase.subject_type == "PROFESSIONAL") & (VerificationCase.subject_id == professional_id))
    return bool(await session.scalar(select(VerificationCase.id).where(
        or_(*subjects), VerificationCase.verification_type == "IDENTITY", VerificationCase.status == "VERIFIED").limit(1)))


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


async def open_case_subjects(session: AsyncSession) -> dict[str, set[uuid.UUID]]:
    """Subjects with a check still waiting for a decision, by subject type (PROFESSIONAL | FIRM | IDENTITY)."""
    out: dict[str, set[uuid.UUID]] = {}
    for subject_type, subject_id in (await session.execute(select(VerificationCase.subject_type, VerificationCase.subject_id)
                                                           .where(VerificationCase.status.in_(("PENDING", "IN_REVIEW", "NEEDS_INFO")))
                                                           .distinct())).all():
        out.setdefault(subject_type, set()).add(subject_id)
    return out


async def case_exists(session: AsyncSession, case_id: uuid.UUID) -> bool:
    """A verification case with this id (staff case ownership checks the case is real)."""
    return await session.get(VerificationCase, case_id) is not None


async def appeal_exists(session: AsyncSession, appeal_id: uuid.UUID) -> bool:
    from zoikorum.domains.verification.models import Appeal

    return await session.get(Appeal, appeal_id) is not None


async def credential_expiries(session: AsyncSession, since, until) -> int:
    """Verified credentials, licences, insurance or jurisdiction checks that lapsed in the period without being renewed
    first (board brief: credential-expiry incidents). A check replaced by its renewal is not an incident."""
    from sqlalchemy import func

    return await session.scalar(select(func.count()).select_from(VerificationCase).where(
        VerificationCase.status == "EXPIRED", VerificationCase.verification_type.in_(("CREDENTIAL", "INSURANCE", "JURISDICTION")),
        func.coalesce(VerificationCase.reason_code, "") != "RENEWED",
        VerificationCase.updated_at >= since, VerificationCase.updated_at < until)) or 0
