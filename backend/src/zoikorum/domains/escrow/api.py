from __future__ import annotations

import uuid

from fastapi import APIRouter

from zoikorum.domains.escrow import service
from zoikorum.domains.escrow.schemas import EscrowOut, FundIn, LedgerLineOut
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.idempotency import IdempotencyKey

router = APIRouter(prefix="/v1/escrow", tags=["escrow"])
# Deliberately no endpoint releases money: release happens only when a milestone is accepted (MILESTONE_ACCEPTED).


@router.get("/by-contract/{contract_id}", response_model=EscrowOut)
async def by_contract(contract_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_by_contract(session, actor, contract_id)


@router.get("/{account_id}", response_model=EscrowOut)
async def get_account(account_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_account(session, actor, account_id)


@router.get("/{account_id}/ledger", response_model=list[LedgerLineOut])
async def ledger(account_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.ledger(session, actor, account_id)


@router.post("/{account_id}/fund", response_model=EscrowOut)
async def fund(account_id: uuid.UUID, body: FundIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """Buyer funds milestones. The money is captured by the payment provider, then held until acceptance."""
    return await idem.run(session, actor, lambda: service.fund(session, actor, account_id, body))
