"""Public, read-only interface of the identity domain for other domains.

Returns plain DTOs - never ORM objects. In a split deployment this module
becomes an HTTP/gRPC client with the same signatures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity.models import Identity


@dataclass(frozen=True)
class IdentitySummary:
    id: uuid.UUID
    email: str
    display_name: str
    country: str
    status: str
    email_confirmed: bool
    mfa_enabled: bool


def _summary(i: Identity) -> IdentitySummary:
    return IdentitySummary(
        id=i.id, email=i.email, display_name=i.display_name, country=i.country, status=i.status,
        email_confirmed=i.email_confirmed_at is not None, mfa_enabled=i.mfa_enabled_at is not None,
    )


async def get_identity(session: AsyncSession, identity_id: uuid.UUID) -> IdentitySummary | None:
    i = await session.get(Identity, identity_id)
    return _summary(i) if i else None


async def get_identities(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, IdentitySummary]:
    if not ids:
        return {}
    rows = (await session.scalars(select(Identity).where(Identity.id.in_(ids)))).all()
    return {r.id: _summary(r) for r in rows}


async def find_by_email(session: AsyncSession, email: str) -> IdentitySummary | None:
    i = await session.scalar(select(Identity).where(Identity.email == email.lower()))
    return _summary(i) if i else None
