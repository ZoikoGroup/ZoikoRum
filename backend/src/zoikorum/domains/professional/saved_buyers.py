"""Saved buyers (Professional Dashboard s.17): a professional's own client list with private notes and alert settings.

Only organisations that have already sent the professional a request can be saved or offered as candidates: there is
no buyer directory and no way to reach buyers who have not made contact (no cold outreach, Trust & Safety charter).
"Alerts" means requests from that organisation are always emailed and marked as from a saved buyer (notification
domain, via ``facade.saved_buyer_alerts``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.professional.models import SavedBuyer
from zoikorum.domains.professional.schemas import BuyerCandidateOut, SavedBuyerIn, SavedBuyerOut, SavedBuyerPatch
from zoikorum.domains.professional.service import _mine
from zoikorum.shared.auth import Actor
from zoikorum.shared.errors import Conflict, NotFound, ValidationFailed

MAX_SAVED = 500


async def _relationships(session: AsyncSession, professional_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    from zoikorum.domains.contract import facade as contract_facade
    from zoikorum.domains.proposal import facade as proposal_facade

    requests = await proposal_facade.buyer_relationships(session, professional_id)
    engagements = await contract_facade.engagements_by_organization(session, professional_id)
    out: dict[uuid.UUID, dict] = {}
    for org in set(requests) | set(engagements):
        r, e = requests.get(org, {}), engagements.get(org, {})
        last = [d for d in (r.get("lastRequestAt"), e.get("lastEngagementAt")) if d]
        out[org] = {"requests": r.get("requests", 0), "engagements": e.get("engagements", 0),
                    "completed": e.get("completed", 0), "lastActivityAt": max(last) if last else None}
    return out


def _recent_first(b) -> tuple:
    """Most recent activity first; organisations with no dated activity last, by name."""
    return (b.lastActivityAt is None, -(b.lastActivityAt.timestamp() if b.lastActivityAt else 0), b.name.lower())


async def _org(session: AsyncSession, org_id: uuid.UUID):
    org = await buyer_facade.get_organization(session, org_id)
    return (org.name, org.country) if org else ("Organisation no longer available", None)


async def candidates(session: AsyncSession, actor: Actor) -> list[BuyerCandidateOut]:
    """Organisations that have contacted the professional, with whether each is already saved."""
    pro = await _mine(session, actor)
    rel = await _relationships(session, pro.id)
    saved = set((await session.scalars(select(SavedBuyer.organization_id).where(SavedBuyer.professional_id == pro.id))).all())
    out = []
    for org_id, stats in rel.items():
        name, country = await _org(session, org_id)
        out.append(BuyerCandidateOut(organizationId=org_id, name=name, country=country, saved=org_id in saved, **stats))
    return sorted(out, key=_recent_first)


async def _out(session: AsyncSession, row: SavedBuyer, rel: dict[uuid.UUID, dict]) -> SavedBuyerOut:
    name, country = await _org(session, row.organization_id)
    stats = rel.get(row.organization_id, {"requests": 0, "engagements": 0, "completed": 0, "lastActivityAt": None})
    return SavedBuyerOut(id=row.id, organizationId=row.organization_id, name=name, country=country, note=row.note,
                         alerts=row.alerts, savedAt=row.created_at, **stats)


async def mine(session: AsyncSession, actor: Actor) -> list[SavedBuyerOut]:
    pro = await _mine(session, actor)
    rows = (await session.scalars(select(SavedBuyer).where(SavedBuyer.professional_id == pro.id))).all()
    rel = await _relationships(session, pro.id)
    return sorted([await _out(session, r, rel) for r in rows], key=_recent_first)


async def save(session: AsyncSession, actor: Actor, body: SavedBuyerIn) -> SavedBuyerOut:
    pro = await _mine(session, actor, lock=True)
    rel = await _relationships(session, pro.id)
    if body.organizationId not in rel:
        raise ValidationFailed("You can only save organisations that have sent you a request", code="NO_RELATIONSHIP")
    existing = await session.scalar(select(SavedBuyer).where(SavedBuyer.professional_id == pro.id,
                                                             SavedBuyer.organization_id == body.organizationId))
    if existing:
        return await _out(session, existing, rel)
    count = len((await session.scalars(select(SavedBuyer.id).where(SavedBuyer.professional_id == pro.id))).all())
    if count >= MAX_SAVED:
        raise Conflict(f"You can save up to {MAX_SAVED} buyers", code="TOO_MANY_SAVED")
    row = SavedBuyer(professional_id=pro.id, organization_id=body.organizationId, note=(body.note or "").strip() or None,
                     alerts=body.alerts)
    session.add(row)
    await session.flush()
    return await _out(session, row, rel)


async def _own(session: AsyncSession, actor: Actor, saved_id: uuid.UUID) -> SavedBuyer:
    pro = await _mine(session, actor)
    row = await session.get(SavedBuyer, saved_id, with_for_update=True)
    if row is None or row.professional_id != pro.id:
        raise NotFound("Saved buyer not found")
    return row


async def update(session: AsyncSession, actor: Actor, saved_id: uuid.UUID, body: SavedBuyerPatch) -> SavedBuyerOut:
    row = await _own(session, actor, saved_id)
    if body.note is not None:
        row.note = body.note.strip() or None
    if body.alerts is not None:
        row.alerts = body.alerts
    await session.flush()
    return await _out(session, row, await _relationships(session, row.professional_id))


async def remove(session: AsyncSession, actor: Actor, saved_id: uuid.UUID) -> None:
    await session.delete(await _own(session, actor, saved_id))
