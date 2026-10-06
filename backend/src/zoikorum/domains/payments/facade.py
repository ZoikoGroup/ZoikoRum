"""Payments facade - CONTRACT. Signatures are fixed."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def has_valid_payout_account(session: AsyncSession, professional_id: uuid.UUID) -> bool:
    from zoikorum.domains.payments.service import has_valid_payout_account as check

    return await check(session, professional_id)
