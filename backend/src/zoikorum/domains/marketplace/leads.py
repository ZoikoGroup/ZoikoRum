"""Sign-up referral codes and public procurement-pack / security-review requests (marketplace growth inputs).

Neither creates an account or exposes anything about other people: a referral code is stored against the person who
typed it, and a procurement request is a lead for the Zoikorum team to answer by email.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.marketplace.models import ProcurementRequest, ReferralAttribution
from zoikorum.domains.marketplace.schemas import ProcurementRequestIn, ProcurementRequestOut, ReferralIn, ReferralOut
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared.auth import Actor
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.errors import Conflict, NotFound
from zoikorum.shared.events import record_audit


def _referral_out(r: ReferralAttribution) -> ReferralOut:
    return ReferralOut(code=r.code, recordedAt=r.created_at)


async def record_referral(session: AsyncSession, actor: Actor, body: ReferralIn) -> ReferralOut:
    """Store the code typed at sign-up. Repeating the same code is harmless; a different one is refused."""
    code = body.code.strip().upper()
    existing = await session.scalar(select(ReferralAttribution).where(ReferralAttribution.identity_id == actor.identity_id))
    if existing:
        if existing.code != code:
            raise Conflict("A referral code is already recorded for your account", code="REFERRAL_ALREADY_RECORDED")
        return _referral_out(existing)
    row = ReferralAttribution(identity_id=actor.identity_id, code=code, source="SIGN_UP")
    session.add(row)
    await session.flush()
    record_audit(session, "marketplace.referral.recorded", object_type="Identity", object_id=actor.identity_id,
                 details={"code": code})
    return _referral_out(row)


async def my_referral(session: AsyncSession, actor: Actor) -> ReferralOut | None:
    row = await session.scalar(select(ReferralAttribution).where(ReferralAttribution.identity_id == actor.identity_id))
    return _referral_out(row) if row else None


def _request_out(r: ProcurementRequest, staff: bool = False) -> ProcurementRequestOut:
    return ProcurementRequestOut(id=r.id, reference=r.reference, kind=r.kind, professionalId=r.professional_id, status=r.status,
                                 createdAt=r.created_at, name=r.name if staff else None, organization=r.organization if staff else None,
                                 email=r.email if staff else None, message=r.message if staff else None)


async def open_procurement_request(session: AsyncSession, actor: Actor | None, body: ProcurementRequestIn) -> ProcurementRequestOut:
    if body.professionalId:
        pro = await professional_facade.get_professional(session, body.professionalId)
        if pro is None or pro.status != "PUBLISHED":
            raise NotFound("Professional not found")
    r = ProcurementRequest(reference="ZK-PRC-" + uuid.uuid4().hex[:8].upper(), kind=body.kind, professional_id=body.professionalId,
                           requester_identity_id=actor.identity_id if actor else None, name=body.name.strip(),
                           organization=body.organization.strip(), email=str(body.email).lower(), message=body.message.strip(), status="NEW")
    session.add(r)
    await session.flush()
    # Who asked stays in the request row (staff only); the audit entry carries no contact details.
    record_audit(session, "marketplace.procurement_request.opened", object_type="ProcurementRequest", object_id=r.id,
                 details={"reference": r.reference, "kind": r.kind, "professionalId": str(r.professional_id) if r.professional_id else None,
                          "signedIn": actor is not None})
    return _request_out(r)


async def list_procurement_requests(session: AsyncSession, actor: Actor, status: str | None) -> list[ProcurementRequestOut]:
    actor.require_capability(Cap.SUPPORT_READ)
    q = select(ProcurementRequest).order_by(ProcurementRequest.created_at.desc(), ProcurementRequest.id).limit(200)
    if status:
        q = q.where(ProcurementRequest.status == status)
    rows = (await session.scalars(q)).all()
    record_audit(session, "marketplace.procurement_request.listed", object_type="ProcurementRequest", object_id=actor.identity_id,
                 details={"count": len(rows)})
    return [_request_out(r, staff=True) for r in rows]
