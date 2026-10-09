"""Professional profile personal data (shared/privacy.py)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.professional.models import CredentialClaim, Offering, Professional, SavedBuyer
from zoikorum.domains.professional.service import PROFILE_STATES, _evt, _offering_evt
from zoikorum.shared import privacy
from zoikorum.shared.event_catalog import E

DELETED_NAME = "Deleted professional"


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    pro = await session.scalar(select(Professional).where(Professional.identity_id == identity_id))
    if pro is None:
        return {}
    return {"profile": privacy.row(pro),
            "offerings": await privacy.rows(session, Offering, Offering.professional_id == pro.id),
            "credentials": await privacy.rows(session, CredentialClaim, CredentialClaim.professional_id == pro.id),
            "savedBuyers": await privacy.rows(session, SavedBuyer, SavedBuyer.professional_id == pro.id)}


async def erase(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    """The profile leaves search and no longer describes the person; engagement history keeps its anonymised name."""
    pro = await session.scalar(select(Professional).where(Professional.identity_id == identity_id).with_for_update())
    if pro is None:
        return {}
    if pro.status == "PUBLISHED":
        PROFILE_STATES.assert_can(pro.status, "UNPUBLISHED")
        pro.status = "UNPUBLISHED"
        _evt(session, E.PROFILE_UNPUBLISHED, pro)  # search drops it
    pro.display_name, pro.legal_name, pro.headline, pro.bio = DELETED_NAME, None, None, None
    pro.city, pro.website, pro.languages = None, None, []
    pro.photo_key = pro.photo_content_type = pro.photo_sha256 = None
    _evt(session, E.PROFILE_UPDATED, pro, changes=["erased"])
    paused = 0
    for o in (await session.scalars(select(Offering).where(Offering.professional_id == pro.id, Offering.status == "ACTIVE")
                                    .with_for_update())).all():
        o.status = "PAUSED"
        _offering_evt(session, E.SERVICE_OFFERING_STATUS_CHANGED, pro, o)
        paused += 1
    saved = (await session.execute(delete(SavedBuyer).where(SavedBuyer.professional_id == pro.id))).rowcount
    return {"profileCleared": True, "offeringsPaused": paused, "savedBuyersDeleted": saved}


privacy.register("professional", export=export, erase=erase,
                 retained="Credential records that a verification relied on, for the verification retention period.")
