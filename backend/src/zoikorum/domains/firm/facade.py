"""Firm facade - CONTRACT. Signatures and DTOs are fixed; implement bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class FirmSummary:
    id: uuid.UUID
    legal_name: str
    trading_name: str | None
    hq_country: str
    size_band: str  # 1-5 | 6-20 | 21-100 | 100+
    status: str  # PENDING_VERIFICATION | VERIFIED | SUSPENDED
    has_verified_representative: bool


async def get_firm(session: AsyncSession, firm_id: uuid.UUID) -> FirmSummary | None:
    raise NotImplementedError


async def member_roles(session: AsyncSession, firm_id: uuid.UUID, identity_id: uuid.UUID) -> frozenset[str]:
    """FIRM_ADMIN | FIRM_MEMBER | AUTHORIZED_REPRESENTATIVE. Empty if not a member."""
    raise NotImplementedError
