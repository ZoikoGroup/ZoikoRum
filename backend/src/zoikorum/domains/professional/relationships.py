"""Owner-scoped buyer bookmarks and organisation follows. Following never grants access."""
from __future__ import annotations
import uuid
from typing import Literal
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from zoikorum.domains.professional.models import Professional, BuyerRelationship
from zoikorum.domains.proposal import facade as proposal
from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.identity import facade as identity
from zoikorum.shared.errors import Forbidden, NotFound
from zoikorum.shared.events import record_audit

class RelationshipIn(BaseModel):
    requestId: uuid.UUID
    kind: Literal["BUYER", "ORGANIZATION"]
    emailAlerts: bool = True
    inAppAlerts: bool = True

class AlertIn(BaseModel):
    emailAlerts: bool
    inAppAlerts: bool

async def owner(session, actor):
    pro = await session.scalar(select(Professional).where(Professional.identity_id == actor.identity_id))
    if not pro or pro.status == 'SUSPENDED' or not await identity.account_is_active(session, actor.identity_id):
        raise Forbidden("An active professional account is required")
    return pro

async def output(session, row):
    target = await (identity.get_identity(session, row.target_id) if row.kind == 'BUYER' else buyer.get_organization(session, row.target_id))
    name = target.display_name if row.kind == 'BUYER' and target else target.name if target else 'Unavailable account'
    return {"id": row.id, "kind": row.kind, "targetId": row.target_id, "name": name,
            "emailAlerts": row.email_alerts, "inAppAlerts": row.in_app_alerts, "savedAt": row.created_at}

async def listing(session, actor):
    pro = await owner(session, actor)
    rows = (await session.scalars(select(BuyerRelationship).where(BuyerRelationship.professional_id == pro.id).order_by(BuyerRelationship.created_at.desc()))).all()
    return [await output(session, row) for row in rows]

async def save(session, actor, body):
    pro = await owner(session, actor)
    request = await proposal.get_request(session, body.requestId)
    if request is None or request.professional_id != pro.id:
        raise NotFound("Request not found")
    target = request.buyer_identity_id if body.kind == 'BUYER' else request.organization_id
    await session.execute(insert(BuyerRelationship).values(id=uuid.uuid4(), professional_id=pro.id, kind=body.kind,
        target_id=target, email_alerts=body.emailAlerts, in_app_alerts=body.inAppAlerts).on_conflict_do_nothing(
            constraint='uq_professional_relationship'))
    row = await session.scalar(select(BuyerRelationship).where(BuyerRelationship.professional_id == pro.id,
        BuyerRelationship.kind == body.kind, BuyerRelationship.target_id == target))
    record_audit(session, 'professional.relationship.saved', object_type='BuyerRelationship', object_id=row.id,
                 details={'professionalId': str(pro.id), 'kind': row.kind})
    return await output(session, row)

async def own_row(session, actor, row_id):
    pro = await owner(session, actor)
    row = await session.scalar(select(BuyerRelationship).where(BuyerRelationship.id == row_id,
        BuyerRelationship.professional_id == pro.id).with_for_update())
    if row is None:
        raise NotFound('Relationship not found')
    return row

async def update(session, actor, row_id, body):
    row = await own_row(session, actor, row_id)
    row.email_alerts, row.in_app_alerts = body.emailAlerts, body.inAppAlerts
    record_audit(session, 'professional.relationship.preferences', object_type='BuyerRelationship', object_id=row.id,
                 details=body.model_dump())
    return await output(session, row)

async def remove(session, actor, row_id):
    row = await own_row(session, actor, row_id)
    record_audit(session, 'professional.relationship.removed', object_type='BuyerRelationship', object_id=row.id)
    await session.delete(row)

async def alert_channels(session, identity_id, buyer_id, organization_id):
    pro = await session.scalar(select(Professional).where(Professional.identity_id == identity_id))
    if not pro:
        return True, True
    rows = (await session.scalars(select(BuyerRelationship).where(BuyerRelationship.professional_id == pro.id))).all()
    # A saved buyer preference overrides the organisation follow. Unfollow restores global defaults.
    for kind, target in [('BUYER', buyer_id), ('ORGANIZATION', organization_id)]:
        for row in rows:
            if row.kind == kind and row.target_id == target:
                return row.email_alerts, row.in_app_alerts
    return True, True
