from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.proposal import service
from zoikorum.shared.relay import on_timer


@on_timer(service.TIMER_EXPIRY)
async def on_expiry(session: AsyncSession, key: str, payload: dict) -> None:
    """A sent proposal past its validity date expires and can no longer be accepted."""
    await service.expire(session, payload)
