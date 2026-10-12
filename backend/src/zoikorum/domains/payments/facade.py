"""Payments facade - CONTRACT. Signatures are fixed."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def has_valid_payout_account(session: AsyncSession, professional_id: uuid.UUID) -> bool:
    from zoikorum.domains.payments.service import has_valid_payout_account as check

    return await check(session, professional_id)


async def payment_started(session: AsyncSession, funding_id: uuid.UUID) -> bool:
    """Whether a charge was ever created for this funding (it may still be waiting for the buyer at checkout)."""
    from zoikorum.domains.payments.models import PaymentIntent

    return bool(await session.scalar(select(PaymentIntent.id).where(PaymentIntent.funding_id == funding_id)))


def require_available() -> None:
    from zoikorum.domains.payments.integration import configuration
    from zoikorum.shared.errors import ServiceUnavailable
    if not configuration()["configured"]:
        raise ServiceUnavailable("Payment integration is not configured; no funding was requested", code="INTEGRATION_NOT_CONFIGURED")
