"""Privacy orchestration must use the owning domains' facades.

The former draft queried nonexistent tables and silently erased unreviewed data.
Fulfilment requires a scoped export and a reviewed retention decision.
"""
from __future__ import annotations

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from zoikorum.domains.identity import facade as identity
from zoikorum.shared.errors import NotFound, Conflict


async def export_user_data(session: AsyncSession, user_id: UUID) -> dict:
    """Identity-only section; callers must compose all other domain sections."""
    account = await identity.get_identity(session, user_id)
    if account is None:
        raise NotFound("Account not found")
    return {"identity": {"id": str(account.id), "email": account.email,
                         "displayName": account.display_name, "country": account.country},
            "scope": "IDENTITY_ONLY", "complete": False}


async def anonymize_user_data(session: AsyncSession, user_id: UUID) -> None:
    """Never erase records without an approved, domain-specific retention plan."""
    if await identity.get_identity(session, user_id) is None:
        raise NotFound("Account not found")
    raise Conflict("Erasure requires a reviewed retention plan and owning-domain fulfilment",
                   code="RETENTION_REVIEW_REQUIRED")
