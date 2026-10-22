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


async def intent_refs(session: AsyncSession, funding_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str | None]]:
    """Per escrow funding: the payment provider that took the money and its reference for the payment."""
    from zoikorum.domains.payments.models import PaymentIntent

    if not funding_ids:
        return {}
    rows = (await session.execute(select(PaymentIntent.funding_id, PaymentIntent.provider, PaymentIntent.provider_ref)
                                  .where(PaymentIntent.funding_id.in_(funding_ids)))).all()
    return {fid: (provider, ref) for fid, provider, ref in rows}


# ---- Financial exceptions closed by hand, through maker-checker approval (admin/approvals.py) -------------------------

async def check_ops_resolution(session: AsyncSession, kind: str, item_id: uuid.UUID) -> None:
    """Refuses a resolution for an unknown kind of item or one already resolved."""
    from zoikorum.domains.payments.operations import check_resolution
    await check_resolution(session, kind, item_id)


async def apply_ops_resolution(session: AsyncSession, kind: str, item_id: uuid.UUID, outcome: str, note: str,
                               requested_by: uuid.UUID, approved_by: uuid.UUID) -> None:
    """Records the approved outcome (RECOVERED | WRITTEN_OFF | SETTLED_OUTSIDE) of a failed payout, failed refund or
    chargeback loss."""
    from zoikorum.domains.payments.operations import apply_resolution
    await apply_resolution(session, kind, item_id, outcome, note, requested_by, approved_by)
