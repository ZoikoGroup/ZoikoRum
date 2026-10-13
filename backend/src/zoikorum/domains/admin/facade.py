"""Administration / Trust & Safety facade - CONTRACT. Implement bodies."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def active_restrictions(session: AsyncSession, subject_type: str, subject_id: uuid.UUID) -> tuple[str, ...]:
    """Active enforcement actions for a subject (IDENTITY|PROFESSIONAL|ORGANIZATION),
    e.g. ("VISIBILITY_REDUCTION",). Empty tuple when clean."""
    from sqlalchemy import select, or_
    from zoikorum.domains.admin.models import EnforcementCase
    from zoikorum.shared import clock
    rows = (await session.scalars(select(EnforcementCase.action).where(
        EnforcementCase.subject_type == subject_type, EnforcementCase.subject_id == subject_id,
        EnforcementCase.status == "ACTIVE", or_(EnforcementCase.expires_at.is_(None), EnforcementCase.expires_at > clock.now())))).all()
    return tuple(sorted(set(rows)))
