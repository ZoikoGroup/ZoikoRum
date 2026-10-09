"""Immutable context-bound messages; every operation checks live participants."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from pathlib import PurePath

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.contract import facade as contract
from zoikorum.domains.identity import facade as identity
from zoikorum.domains.professional import facade as professional
from zoikorum.domains.proposal import facade as proposal
from zoikorum.domains.messaging.models import Attachment, DisputeContext, Message, ReadPosition, Thread
from zoikorum.domains.messaging.schemas import AttachmentOut, MessageIn, MessageOut, ThreadIn, ThreadOut, UploadIn
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.http import Page
from zoikorum.shared.storage import get_storage


async def context_info(session, kind, context_id):
    if kind == "PROPOSAL_REQUEST":
        obj = await proposal.get_request(session, context_id)
        access = await proposal.messaging_access(session, context_id)
        if not obj or not access or obj.status == "DRAFT":
            raise NotFound("Sent request not found")
        return obj, access[0], access[1], access[2]
    if kind == "CONTRACT":
        obj = await contract.get_contract(session, context_id)
        if not obj:
            raise NotFound("Engagement not found")
        access = await proposal.messaging_access(session, obj.request_id)
        return obj, access[0] if access else "Engagement", True, obj.status in {"GENERATED", "PENDING_SIGNATURE", "ACTIVE"}
    if kind == "DISPUTE":
        case = await session.get(DisputeContext, context_id)
        if not case:
            raise NotFound("Dispute not found")
        obj = await contract.get_contract(session, case.contract_id)
        if not obj:
            raise NotFound("Engagement not found")
        access = await proposal.messaging_access(session, obj.request_id)
        title = f"Dispute · {access[0]}" if access else "Dispute"
        return obj, title, True, False
    # Disputes use structured submissions; freeform chat is never enabled.
    raise Conflict("Dispute communication belongs in the structured dispute workspace", code="DISPUTE_WORKSPACE_REQUIRED")


async def authorize(session, actor, kind, context_id):
    account = await identity.get_identity(session, actor.identity_id)
    if not account or account.status != "ACTIVE":
        raise Forbidden("An active account is required")
    obj, title, nda, can_send = await context_info(session, kind, context_id)
    pro = await professional.get_professional(session, obj.professional_id)
    member = await buyer.get_member_roles(session, obj.organization_id, actor.identity_id)
    owns = pro and pro.identity_id == actor.identity_id
    if not member and not owns:
        raise NotFound("Conversation not found")
    if owns and not nda and not member:
        raise Forbidden("Accept the request NDA before accessing its conversation", code="NDA_REQUIRED")
    org = await buyer.get_organization(session, obj.organization_id)
    can_send = can_send and bool(org and org.status == "ACTIVE") and bool(pro and pro.status != "SUSPENDED")
    return obj, title, can_send


async def ensure_thread(session, kind, context_id):
    obj, title, _, _ = await context_info(session, kind, context_id)
    thread_id = uuid.uuid4()
    result = await session.execute(insert(Thread).values(id=thread_id, context_type=kind, context_id=context_id,
        organization_id=obj.organization_id, professional_id=obj.professional_id, title=title,
        sequence=0, locked=False).on_conflict_do_nothing(index_elements=["context_type", "context_id"]).returning(Thread.id))
    if result.scalar_one_or_none():
        record_event(session, E.THREAD_CREATED, aggregate_type="Thread", aggregate_id=thread_id,
            tenant_id=obj.organization_id, payload={"contextType": kind, "contextId": str(context_id)})
    return await session.scalar(select(Thread).where(Thread.context_type == kind, Thread.context_id == context_id))


async def checked_thread(session, actor, thread_id, *, write=False):
    thread = await session.scalar(select(Thread).where(Thread.id == thread_id).with_for_update() if write
        else select(Thread).where(Thread.id == thread_id))
    if not thread:
        raise NotFound("Conversation not found")
    obj, _, can_send = await authorize(session, actor, thread.context_type, thread.context_id)
    agreement = await contract.get_contract_by_request(session, obj.id) if thread.context_type == "PROPOSAL_REQUEST" else obj
    if agreement and thread.context_type == "PROPOSAL_REQUEST":
        can_send = can_send and agreement.status in {"GENERATED", "PENDING_SIGNATURE", "ACTIVE"}
    if agreement:
        open_case = await session.scalar(select(DisputeContext.dispute_id).where(
            DisputeContext.contract_id == agreement.id, DisputeContext.is_open.is_(True)).limit(1))
        can_send = can_send and not open_case
        obj = agreement
    disputed = getattr(obj, "status", "") == "DISPUTED" or any(m.status == "DISPUTED" for m in getattr(obj, "milestones", ()))
    if write and (thread.locked or disputed or not can_send):
        raise Conflict("This conversation is read-only; use the dispute workspace for disputed work", code="THREAD_READ_ONLY")
    return thread, can_send and not thread.locked and not disputed


async def thread_out(session, actor, thread, can_send):
    pos = await session.scalar(select(ReadPosition.sequence).where(ReadPosition.thread_id == thread.id,
        ReadPosition.identity_id == actor.identity_id)) or 0
    unread = await session.scalar(select(func.count()).select_from(Message).where(Message.thread_id == thread.id,
        Message.sequence > pos, or_(Message.sender_identity_id.is_(None), Message.sender_identity_id != actor.identity_id))) or 0
    latest = await session.scalar(select(Message).where(Message.thread_id == thread.id).order_by(Message.sequence.desc()).limit(1))
    pro = await professional.get_professional(session, thread.professional_id)
    org = await buyer.get_organization(session, thread.organization_id)
    counterpart = pro.display_name if pro and pro.identity_id != actor.identity_id else org.name if org else "Organisation"
    is_professional = bool(pro and pro.identity_id == actor.identity_id)
    return ThreadOut(id=thread.id, contextType=thread.context_type, contextId=thread.context_id, title=thread.title,
        locked=not can_send, lockReason=thread.lock_reason or ("Conversation is read-only" if not can_send else None),
        canSend=can_send, unreadCount=unread, lastSequence=thread.sequence, updatedAt=thread.updated_at,
        counterpartName=counterpart, viewerRole="PROFESSIONAL" if is_professional else "BUYER",
        professionalId=thread.professional_id, photoUrl=pro.photo_url if pro and not is_professional else None,
        headline=pro.headline if pro and not is_professional else "Customer",
        country=org.country if org and is_professional else pro.country if pro else None,
        lastMessage=latest.body[:160] if latest else "No messages yet",
        lastMessageFromSystem=bool(latest and latest.sender_identity_id is None), createdAt=thread.created_at)


async def open_thread(session, actor, body: ThreadIn):
    if body.contextType == "DISPUTE":
        raise Conflict(
            "Dispute workspaces are created from the dispute lifecycle",
            code="DISPUTE_THREAD_SYSTEM_CREATED",
        )
    await authorize(session, actor, body.contextType, body.contextId)
    thread = await ensure_thread(session, body.contextType, body.contextId)
    _, can_send = await checked_thread(session, actor, thread.id)
    return await thread_out(session, actor, thread, can_send)


async def list_threads(session, actor, before=None, limit=30, *, context_type=None, context_id=None):
    orgs = await buyer.list_identity_organizations(session, actor.identity_id)
    pro = await professional.get_professional_by_identity(session, actor.identity_id)
    stmt = select(Thread).where(or_(Thread.organization_id.in_(orgs),
        Thread.professional_id == pro.id if pro else False))
    if context_type:
        stmt = stmt.where(Thread.context_type == context_type)
    if context_id:
        stmt = stmt.where(Thread.context_id == context_id)
    from zoikorum.shared.http import decode_cursor, encode_cursor

    position = decode_cursor(before)
    visible = []
    exhausted = False
    while len(visible) <= limit and not exhausted:
        batch_stmt = stmt.order_by(Thread.updated_at.desc(), Thread.id.desc()).limit(100)
        if position:
            date, row_id = position
            batch_stmt = batch_stmt.where(
                or_(Thread.updated_at < date, (Thread.updated_at == date) & (Thread.id < row_id))
            )
        rows = list((await session.scalars(batch_stmt)).all())
        if not rows:
            break
        for thread in rows:
            position = (thread.updated_at, thread.id)
            try:
                _, can_send = await checked_thread(session, actor, thread.id)
            except (Forbidden, NotFound):
                continue
            visible.append(await thread_out(session, actor, thread, can_send))
            if len(visible) > limit:
                break
        exhausted = len(rows) < 100

    next_cursor = None
    if len(visible) > limit:
        last = visible[limit - 1]
        next_cursor = encode_cursor(last.updatedAt, last.id)
    elif not exhausted and position:
        next_cursor = encode_cursor(*position)
    return Page(items=visible[:limit], nextCursor=next_cursor)


async def unread_summary(session, actor):
    account = await identity.get_identity(session, actor.identity_id)
    if not account or account.status != "ACTIVE":
        raise Forbidden("An active account is required")
    orgs = await buyer.list_identity_organizations(session, actor.identity_id)
    pro = await professional.get_professional_by_identity(session, actor.identity_id)
    rows = (await session.execute(select(Thread.id, func.count(Message.id)).join(Message, Message.thread_id == Thread.id)
        .outerjoin(ReadPosition, and_(ReadPosition.thread_id == Thread.id, ReadPosition.identity_id == actor.identity_id))
        .where(or_(Thread.organization_id.in_(orgs), Thread.professional_id == pro.id if pro else False),
            Message.sequence > func.coalesce(ReadPosition.sequence, 0),
            or_(Message.sender_identity_id.is_(None), Message.sender_identity_id != actor.identity_id))
        .group_by(Thread.id))).all()
    counts = []
    for thread_id, count in rows:
        try:
            await checked_thread(session, actor, thread_id)
        except (Forbidden, NotFound):
            continue
        counts.append(count)
    return {"unreadThreads": len(counts), "unreadMessages": sum(counts)}


def attachment_out(a):
    return AttachmentOut(id=a.id, name=a.name, contentType=a.content_type, size=a.size_bytes,
        sha256=a.sha256, fileVersion=a.file_version, uploadedAt=a.created_at)


async def message_out(session, message):
    files = {str(a.id): a for a in (await session.scalars(select(Attachment).where(
        Attachment.id.in_([uuid.UUID(i) for i in message.attachment_ids])))).all()} if message.attachment_ids else {}
    return MessageOut(id=message.id, sequence=message.sequence, senderIdentityId=message.sender_identity_id,
        senderName=message.sender_name, body=message.body, attachments=[attachment_out(files[i]) for i in message.attachment_ids],
        contentHash=message.content_hash, sentAt=message.created_at)


async def list_messages(session, actor, thread_id, before=None, limit=50):
    await checked_thread(session, actor, thread_id)
    stmt = select(Message).where(Message.thread_id == thread_id).order_by(Message.sequence.desc())
    if before is not None:
        stmt = stmt.where(Message.sequence < before)
    rows = list((await session.scalars(stmt.limit(limit + 1))).all())
    return {"items": [await message_out(session, m) for m in rows[:limit]],
        "nextCursor": str(rows[limit - 1].sequence) if len(rows) > limit else None}


def signals(body):
    flags = []
    if re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", body, re.I): flags.append("CONTACT_EMAIL")
    if re.search(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)", body): flags.append("CONTACT_PHONE")
    if re.search(r"(?:paypal\.me|cash\.app|venmo\.com|buy\.stripe\.com|wise\.com)/", body, re.I): flags.append("OFF_PLATFORM_PAYMENT")
    if re.search(r"\b(?:kill you|hurt you|idiot|stupid|fuck you)\b", body, re.I): flags.append("POSSIBLE_HARASSMENT")
    return flags


async def append_message(session, thread, body, *, sender=None, name="Zoikorum", files=(), event_id=None):
    if event_id:
        existing = await session.scalar(
            select(Message).where(Message.thread_id == thread.id, Message.source_event_id == event_id)
        )
        if existing:
            return existing
    thread.sequence += 1
    now = clock.now()
    thread.updated_at = now
    canonical = {"threadId": str(thread.id), "sequence": thread.sequence, "senderId": str(sender) if sender else None,
        "senderName": name, "body": body, "attachments": [{"id": str(a.id), "sha256": a.sha256, "version": a.file_version} for a in files],
        "sentAt": now.isoformat(), "sourceEventId": str(event_id) if event_id else None}
    msg = Message(id=uuid.uuid4(), thread_id=thread.id, sequence=thread.sequence, sender_identity_id=sender,
        sender_name=name, body=body, attachment_ids=[str(a.id) for a in files], source_event_id=event_id,
        content_hash=hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        flags=signals(body) if sender else [], created_at=now)
    session.add(msg)
    await session.flush()
    record_event(session, E.MESSAGE_SENT, aggregate_type="Message", aggregate_id=msg.id, tenant_id=thread.organization_id,
        payload={"threadId": str(thread.id), "contextType": thread.context_type, "contextId": str(thread.context_id),
            "senderIdentityId": str(sender) if sender else None, "contentHash": msg.content_hash, "sequence": msg.sequence})
    if msg.flags:
        record_event(session, E.MESSAGE_FLAGGED, aggregate_type="Message", aggregate_id=msg.id, tenant_id=thread.organization_id,
            payload={"threadId": str(thread.id), "reasonCodes": msg.flags, "senderIdentityId": str(sender)})
    return msg


async def send_message(session, actor, thread_id, body: MessageIn):
    thread, _ = await checked_thread(session, actor, thread_id, write=True)
    files = []
    for attachment_id in body.attachments:
        file = await session.get(Attachment, attachment_id)
        if not file or file.thread_id != thread.id or file.uploaded_by != actor.identity_id:
            raise ValidationFailed("Only your own uploads in this conversation can be attached")
        files.append(file)
    account = await identity.get_identity(session, actor.identity_id)
    msg = await append_message(session, thread, body.body, sender=actor.identity_id, name=account.display_name, files=files)
    return await message_out(session, msg)


async def mark_read(session, actor, thread_id, through):
    thread, _ = await checked_thread(session, actor, thread_id)
    if through > thread.sequence:
        raise ValidationFailed("Read position exceeds the last message")
    await session.execute(insert(ReadPosition).values(id=uuid.uuid4(), thread_id=thread_id, identity_id=actor.identity_id,
        sequence=through).on_conflict_do_update(index_elements=["thread_id", "identity_id"],
            set_={"sequence": func.greatest(ReadPosition.sequence, through), "updated_at": clock.now()}))


async def upload(session, actor, thread_id, body: UploadIn):
    thread, _ = await checked_thread(session, actor, thread_id, write=True)
    if PurePath(body.name).name != body.name or any(c in body.name for c in '/\\') or any(ord(c) < 32 for c in body.name):
        raise ValidationFailed("Invalid filename")
    try:
        data = base64.b64decode(body.dataBase64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValidationFailed("Invalid file encoding") from exc
    if not data or len(data) > 10 * 1024 * 1024:
        raise ValidationFailed("Files must be between 1 byte and 10 MB")
    from zoikorum.domains.messaging.files import validate_file
    content_type = validate_file(body.name, data)
    version = (await session.scalar(select(func.max(Attachment.file_version)).where(
        Attachment.thread_id == thread.id, Attachment.name == body.name)) or 0) + 1
    file_id = uuid.uuid4()
    key = f"messaging/{thread.id}/{file_id}"
    get_storage().put(key, data)
    a = Attachment(id=file_id, thread_id=thread.id, uploaded_by=actor.identity_id, name=body.name,
        content_type=content_type, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), storage_key=key,
        file_version=version)
    session.add(a)
    await session.flush()
    record_audit(session, "messaging.attachment_uploaded", object_type="Attachment", object_id=a.id,
        evidence_hash=a.sha256, tenant_id=thread.organization_id, details={"threadId": str(thread.id), "version": version})
    return attachment_out(a)


async def download(session, actor, thread_id, file_id):
    thread, _ = await checked_thread(session, actor, thread_id)
    a = await session.get(Attachment, file_id)
    if not a or a.thread_id != thread.id:
        raise NotFound("File not found")
    shared = await session.scalar(select(Message.id).where(Message.thread_id == thread.id,
        Message.attachment_ids.contains([str(a.id)])).limit(1))
    if not shared and a.uploaded_by != actor.identity_id:
        raise NotFound("File not found")
    data = get_storage().get(a.storage_key)
    if data is None or hashlib.sha256(data).hexdigest() != a.sha256:
        raise Conflict("Stored file is unavailable or failed its integrity check", code="FILE_INTEGRITY_FAILED")
    record_audit(session, "messaging.attachment_downloaded", object_type="Attachment", object_id=a.id,
        tenant_id=thread.organization_id, evidence_hash=a.sha256)
    return a, data


async def _lifecycle_thread(session, kind, context_id, event, body):
    thread = await ensure_thread(session, kind, context_id)
    thread = await session.scalar(select(Thread).where(Thread.id == thread.id).with_for_update())
    await append_message(session, thread, body, event_id=event.eventId)
    return thread


async def on_request_created(session, event):
    request_id = uuid.UUID(str(event.payload.get("requestId") or event.aggregateId))
    await _lifecycle_thread(session, "PROPOSAL_REQUEST", request_id, event, "A professional request was sent.")


async def on_contract_activated(session, event):
    contract_id = uuid.UUID(str(event.payload.get("contractId") or event.aggregateId))
    await _lifecycle_thread(session, "CONTRACT", contract_id, event, "The engagement is active.")


async def on_lifecycle(session, event, body):
    contract_id = event.payload.get("contractId")
    request_id = event.payload.get("requestId")
    if contract_id:
        if await contract.get_contract(session, uuid.UUID(str(contract_id))):
            await _lifecycle_thread(session, "CONTRACT", uuid.UUID(str(contract_id)), event, body)
    elif request_id:
        request = await proposal.get_request(session, uuid.UUID(str(request_id)))
        if request and request.status != "DRAFT":
            await _lifecycle_thread(session, "PROPOSAL_REQUEST", request.id, event, body)


async def _set_locked(session, thread, locked, event, reason):
    if thread.locked == locked:
        return
    thread.locked = locked
    thread.lock_reason = reason if locked else None
    thread.updated_at = clock.now()
    record_event(
        session,
        E.THREAD_LOCKED if locked else E.THREAD_UNLOCKED,
        aggregate_type="Thread",
        aggregate_id=thread.id,
        tenant_id=thread.organization_id,
        payload={"contextType": thread.context_type, "contextId": str(thread.context_id), "reason": reason},
    )
    await append_message(
        session,
        thread,
        "Direct messaging is paused while the dispute is active." if locked
        else "The dispute is closed. Direct messaging is available again.",
        event_id=event.eventId,
    )


async def on_dispute_initiated(session, event):
    dispute_id = uuid.UUID(str(event.payload.get("disputeId") or event.aggregateId))
    contract_id = uuid.UUID(str(event.payload["contractId"]))
    agreement = await contract.get_contract(session, contract_id)
    if not agreement:
        return
    now = clock.now()
    await session.execute(
        insert(DisputeContext).values(
            dispute_id=dispute_id,
            contract_id=contract_id,
            category=str(event.payload.get("category") or "OTHER"),
            initiated_by_identity_id=(
                uuid.UUID(str(event.payload["initiatedBy"])) if event.payload.get("initiatedBy") else None
            ),
            is_open=True,
            created_at=event.occurredAt,
            updated_at=event.occurredAt,
        ).on_conflict_do_update(
            index_elements=[DisputeContext.dispute_id],
            set_={
                "contract_id": contract_id,
                "category": str(event.payload.get("category") or "OTHER"),
                "initiated_by_identity_id": (
                    uuid.UUID(str(event.payload["initiatedBy"])) if event.payload.get("initiatedBy") else None
                ),
                "is_open": True,
                "updated_at": event.occurredAt,
            },
            where=DisputeContext.updated_at < event.occurredAt,
        )
    )
    reason = "A dispute is open for this engagement."
    current_case = await session.get(DisputeContext, dispute_id, populate_existing=True)
    if not current_case.is_open:
        return
    for kind, context_id in (("CONTRACT", agreement.id), ("PROPOSAL_REQUEST", agreement.request_id)):
        thread = await session.scalar(
            select(Thread).where(Thread.context_type == kind, Thread.context_id == context_id).with_for_update()
        )
        if thread:
            await _set_locked(session, thread, True, event, reason)
    await _ensure_dispute_thread(session, dispute_id, agreement, event)


async def on_dispute_closed(session, event):
    dispute_id = uuid.UUID(str(event.payload.get("disputeId") or event.aggregateId))
    case = await session.get(DisputeContext, dispute_id)
    if not case and not event.payload.get("contractId"):
        raise ValidationFailed("A dispute closure must identify its engagement")
    contract_id = uuid.UUID(str(event.payload.get("contractId") or case.contract_id))
    agreement = await contract.get_contract(session, contract_id)
    if not agreement:
        return
    await session.execute(insert(DisputeContext).values(dispute_id=dispute_id, contract_id=contract_id,
        category=str(event.payload.get("category") or "OTHER"), is_open=False,
        created_at=event.occurredAt, updated_at=event.occurredAt).on_conflict_do_update(
            index_elements=[DisputeContext.dispute_id], set_={"is_open": False, "updated_at": event.occurredAt},
            where=DisputeContext.updated_at <= event.occurredAt))
    await session.flush()
    for kind, context_id in (("CONTRACT", agreement.id), ("PROPOSAL_REQUEST", agreement.request_id)):
        thread = await session.scalar(
            select(Thread).where(Thread.context_type == kind, Thread.context_id == context_id).with_for_update()
        )
        has_open_disputes = await session.scalar(
            select(DisputeContext.dispute_id)
            .where(DisputeContext.contract_id == agreement.id, DisputeContext.is_open.is_(True))
            .limit(1)
        )
        if thread and not has_open_disputes:
            await _set_locked(session, thread, False, event, "All disputes for this engagement are closed.")


async def _ensure_dispute_thread(session, dispute_id, agreement, event):
    access = await proposal.messaging_access(session, agreement.request_id)
    title = f"Dispute · {access[0]}" if access else "Dispute"
    thread_id = uuid.uuid4()
    result = await session.execute(
        insert(Thread).values(
            id=thread_id,
            context_type="DISPUTE",
            context_id=dispute_id,
            organization_id=agreement.organization_id,
            professional_id=agreement.professional_id,
            title=title,
            sequence=0,
            locked=True,
            lock_reason="Dispute communication is handled in the structured dispute workspace.",
        ).on_conflict_do_nothing(index_elements=["context_type", "context_id"]).returning(Thread.id)
    )
    if result.scalar_one_or_none():
        record_event(
            session,
            E.THREAD_CREATED,
            aggregate_type="Thread",
            aggregate_id=thread_id,
            tenant_id=agreement.organization_id,
            payload={"contextType": "DISPUTE", "contextId": str(dispute_id)},
        )
    thread = await session.scalar(
        select(Thread).where(Thread.context_type == "DISPUTE", Thread.context_id == dispute_id).with_for_update()
    )
    await append_message(session, thread, "A dispute workspace has been opened.", event_id=event.eventId)
