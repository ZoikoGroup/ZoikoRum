"""Contracts the person is party to (shared/privacy.py). Kept by law; an open engagement blocks account deletion."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.contract.models import ChangeOrder, Contract, Signature
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import privacy

OPEN = ("PENDING_SIGNATURE", "ACTIVE", "DISPUTED")


async def _party(session: AsyncSession, identity_id: uuid.UUID):
    pro = await professional_facade.get_professional_by_identity(session, identity_id)
    return or_(Contract.buyer_identity_id == identity_id, *([Contract.professional_id == pro.id] if pro else []))


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    return {"contracts": await privacy.rows(session, Contract, await _party(session, identity_id)),
            "signatures": await privacy.rows(session, Signature, Signature.signer_identity_id == identity_id),
            "changeOrders": await privacy.rows(session, ChangeOrder, ChangeOrder.proposed_by_identity_id == identity_id)}


async def blockers(session: AsyncSession, identity_id: uuid.UUID) -> list[str]:
    n = await session.scalar(select(func.count()).select_from(Contract).where(await _party(session, identity_id),
                                                                              Contract.status.in_(OPEN)))
    return [f"{n} engagement(s) are still open. Complete or end them first."] if n else []


privacy.register("contract", export=export, blockers=blockers,
                 retained="Contracts, signatures, change orders and delivered work (legal and tax record keeping).")
