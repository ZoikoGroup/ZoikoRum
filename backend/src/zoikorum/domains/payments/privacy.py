"""Payouts and the payout account (shared/privacy.py). Kept for tax; a payout on its way blocks account deletion."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.payments.models import Payout, PayoutAccount
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import privacy

IN_FLIGHT = ("QUEUED", "INITIATED", "PENDING")


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    pro = await professional_facade.get_professional_by_identity(session, identity_id)
    if pro is None:
        return {}
    return {"payoutAccount": await privacy.rows(session, PayoutAccount, PayoutAccount.professional_id == pro.id,
                                                exclude=("provider_account_ref",)),
            "payouts": await privacy.rows(session, Payout, Payout.professional_id == pro.id)}


async def blockers(session: AsyncSession, identity_id: uuid.UUID) -> list[str]:
    pro = await professional_facade.get_professional_by_identity(session, identity_id)
    if pro is None:
        return []
    n = await session.scalar(select(func.count()).select_from(Payout).where(Payout.professional_id == pro.id,
                                                                            Payout.status.in_(IN_FLIGHT)))
    return [f"{n} payout(s) are still on their way to your bank."] if n else []


privacy.register("payments", export=export, blockers=blockers,
                 retained="Payments, payouts, refunds and invoices (tax and accounting law).")
