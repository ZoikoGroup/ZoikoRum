from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.audit import service
from zoikorum.shared import clock
from zoikorum.shared.events import ALL, EventEnvelope, subscribe
from zoikorum.shared.relay import on_timer, schedule_timer


@subscribe(ALL, consumer="audit.ledger")
async def write_audit_record(session: AsyncSession, event: EventEnvelope) -> None:
    """Every domain event becomes an immutable, hash-chained audit record."""
    await service.append(session, event)


@on_timer("audit.chain_validation")
async def validate_chain(session: AsyncSession, key: str, payload: dict) -> None:
    """Hourly hash-chain validation (Architecture 8.2). Re-arms itself."""
    await service.verify_chain(session)
    nxt = clock.now() + timedelta(hours=1)
    await schedule_timer(session, "audit.chain_validation", nxt.strftime("%Y%m%d%H"), nxt)
