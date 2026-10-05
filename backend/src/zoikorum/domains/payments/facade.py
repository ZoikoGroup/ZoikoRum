"""Payments facade - CONTRACT. Signatures are fixed; implement bodies."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def has_valid_payout_account(session: AsyncSession, professional_id: uuid.UUID) -> bool:
    raise NotImplementedError
