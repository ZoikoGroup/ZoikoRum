"""Privacy access fulfilment: owning-domain facades, reviewed scope, encrypted expiry."""
import json
import uuid
from datetime import timedelta
from sqlalchemy import select
from zoikorum.config import get_settings
from zoikorum.domains.identity import service
from zoikorum.domains.identity.models import DataRequest, Identity, ConsentRecord
from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.firm import facade as firm
from zoikorum.domains.professional import facade as professional
from zoikorum.domains.marketplace import facade as marketplace
from zoikorum.domains.proposal import facade as proposal
from zoikorum.domains.contract import facade as contract
from zoikorum.domains.messaging import facade as messaging
from zoikorum.domains.notification import facade as notification
from zoikorum.domains.verification import facade as verification
from zoikorum.domains.review import facade as review
from zoikorum.domains.ai import facade as ai
from zoikorum.domains.policy import facade as policy
from zoikorum.domains.payments import facade as payments
from zoikorum.shared import clock
from zoikorum.shared.auth import PlatformRole
from zoikorum.shared.crypto import encrypt_field, decrypt_field
from zoikorum.shared.events import record_audit
from zoikorum.shared.event_catalog import E
from zoikorum.shared.relay import schedule_timer
from zoikorum.shared.errors import NotFound, Conflict
from zoikorum.shared.privacy_exports import portable, export_rows

SECTIONS = {'buyer': buyer, 'firm': firm, 'professional': professional, 'marketplace': marketplace,
            'proposal': proposal, 'contract': contract, 'messaging': messaging, 'notification': notification,
            'verification': verification, 'review': review, 'ai': ai, 'policy': policy}

async def staff(session, actor):
    actor.require_platform_role(PlatformRole.LEGAL, PlatformRole.COMPLIANCE_OFFICER, PlatformRole.PLATFORM_ADMIN)
    actor.require_step_up()

async def queue(session, actor):
    await staff(session, actor)
    rows = (await session.scalars(select(DataRequest).order_by(DataRequest.created_at.desc()).limit(200))).all()
    return [{**service._dr_out(r).model_dump(mode='json'), 'identityId': str(r.identity_id)} for r in rows]

async def assemble(session, identity_id):
    identity = await session.get(Identity, identity_id)
    if not identity:
        raise NotFound('Account not found')
    sections = {'identity': portable(service.to_out(identity, await service._links(session, identity.id)).model_dump(mode='json')),
                'consents': await export_rows(session, ConsentRecord, ConsentRecord.identity_id == identity_id,
                    ['consent_type', 'document_version', 'created_at'])}
    for name, facade in SECTIONS.items():
        sections[name] = await facade.privacy_export(session, identity_id)
    contract_ids = [uuid.UUID(r['id']) for r in sections['contract']['contracts'] if r['buyer_identity_id'] == str(identity_id)]
    pro = await professional.get_professional_by_identity(session, identity_id)
    sections['payments'] = await payments.privacy_export_contracts(session, contract_ids, pro.id if pro else None)
    return {'format': 'zoikorum.personal-data.v1', 'generatedAt': clock.now().isoformat(), 'identityId': str(identity_id),
        'sections': sections, 'scope': {'included': 'Account records and directly owned activity in the listed sections',
        'files': 'Document metadata is included; file copies remain subject to their existing access controls',
        'reviewRequired': ['Internal verification/risk observations', 'Other people’s private data', 'Financial and audit retention exceptions']}}

async def fulfil_access(session, actor, request_id, note):
    await staff(session, actor)
    row = await session.scalar(select(DataRequest).where(DataRequest.id == request_id).with_for_update())
    if not row:
        raise NotFound('Privacy request not found')
    if row.request_type != 'ACCESS':
        raise Conflict('Erasure requires a separate reviewed retention decision', code='RETENTION_REVIEW_REQUIRED')
    if row.status == 'COMPLETED' and row.export_payload_enc:
        return service._dr_out(row)
    export = await assemble(session, row.identity_id)
    export['review'] = {'note': note, 'reviewedAt': clock.now().isoformat()}
    row.export_payload_enc = encrypt_field(json.dumps(export, ensure_ascii=False))
    row.export_expires_at = clock.now() + timedelta(days=get_settings().privacy_export_ttl_days)
    row.reviewed_by, row.review_note = actor.identity_id, note
    row.completed_at, row.status = clock.now(), 'COMPLETED'
    await schedule_timer(session, 'identity.privacy_export_expiry', str(row.id), row.export_expires_at)
    identity = await session.get(Identity, row.identity_id)
    service._evt(session, E.DATA_REQUEST_COMPLETED, identity, dataRequestId=row.id, requestType='ACCESS')
    record_audit(session, 'privacy.access.fulfilled', object_type='DataRequest', object_id=row.id,
        details={'identityId': str(row.identity_id), 'sections': list(export['sections'])})
    return service._dr_out(row)

async def download(session, actor, request_id):
    actor.require_step_up()
    row = await session.scalar(select(DataRequest).where(DataRequest.id == request_id,
        DataRequest.identity_id == actor.identity_id).with_for_update())
    if not row:
        raise NotFound('Privacy request not found')
    if not row.export_payload_enc or not row.export_expires_at or row.export_expires_at <= clock.now():
        raise Conflict('This data copy is unavailable or expired; request a new copy', code='PRIVACY_EXPORT_UNAVAILABLE')
    record_audit(session, 'privacy.access.downloaded', object_type='DataRequest', object_id=row.id)
    return json.loads(decrypt_field(row.export_payload_enc))


async def expire_export(session, request_id):
    row = await session.get(DataRequest, uuid.UUID(request_id), with_for_update=True)
    if row and row.export_expires_at and row.export_expires_at <= clock.now():
        row.export_payload_enc = None
