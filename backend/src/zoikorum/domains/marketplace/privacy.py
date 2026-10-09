"""Saved professionals, shortlists, saved searches and specialization suggestions (shared/privacy.py)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.marketplace.models import (
    Collection, CollectionItem, SavedProfessional, SavedSearch, SpecializationSuggestion,
)
from zoikorum.shared import privacy


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    ids = (await session.scalars(select(Collection.id).where(Collection.identity_id == identity_id))).all()
    return {"savedProfessionals": await privacy.rows(session, SavedProfessional, SavedProfessional.identity_id == identity_id),
            "shortlists": await privacy.rows(session, Collection, Collection.identity_id == identity_id),
            "shortlistItems": await privacy.rows(session, CollectionItem, CollectionItem.collection_id.in_(ids)),
            "savedSearches": await privacy.rows(session, SavedSearch, SavedSearch.identity_id == identity_id),
            "specializationSuggestions": await privacy.rows(session, SpecializationSuggestion,
                                                            SpecializationSuggestion.identity_id == identity_id)}


async def erase(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    ids = (await session.scalars(select(Collection.id).where(Collection.identity_id == identity_id))).all()
    await session.execute(delete(CollectionItem).where(CollectionItem.collection_id.in_(ids)))
    await session.execute(delete(Collection).where(Collection.identity_id == identity_id))
    saved = (await session.execute(delete(SavedProfessional).where(SavedProfessional.identity_id == identity_id))).rowcount
    await session.execute(delete(SavedSearch).where(SavedSearch.identity_id == identity_id))
    await session.execute(delete(SpecializationSuggestion).where(SpecializationSuggestion.identity_id == identity_id,
                                                                 SpecializationSuggestion.status == "PENDING"))
    return {"savedItemsDeleted": saved, "shortlistsDeleted": len(ids)}


privacy.register("marketplace", export=export, erase=erase)
