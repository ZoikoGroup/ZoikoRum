"""Verification facade - CONTRACT. Signatures and DTOs are fixed; implement bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


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


async def get_checks(session: AsyncSession, subject_type: str, subject_id: uuid.UUID) -> list[CheckStatus]:
    """subject_type: PROFESSIONAL | FIRM. Latest case per (type, credential)."""
    raise NotImplementedError
