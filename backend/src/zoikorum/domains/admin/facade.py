"""Administration / Trust & Safety facade - CONTRACT. Implement bodies."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def active_restrictions(session: AsyncSession, subject_type: str, subject_id: uuid.UUID) -> tuple[str, ...]:
    """Active enforcement actions for a subject (IDENTITY|PROFESSIONAL|ORGANIZATION),
    e.g. ("VISIBILITY_REDUCTION",). Empty tuple when clean."""
    raise NotImplementedError
