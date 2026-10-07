from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Query, Response
from zoikorum.domains.messaging import service
from zoikorum.domains.messaging.schemas import MessageIn, MessageOut, ReadIn, ThreadIn, ThreadOut, UploadIn, AttachmentOut, UnreadSummaryOut
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.http import Page
from zoikorum.shared.idempotency import IdempotencyKey

router = APIRouter(tags=["messaging"])


@router.post("/v1/threads", response_model=ThreadOut, status_code=201)
@router.post("/v1/messaging/threads", response_model=ThreadOut, status_code=201, include_in_schema=False)
async def open_thread(body: ThreadIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.open_thread(session, actor, body), status_code=201)


@router.get("/v1/threads", response_model=Page[ThreadOut])
@router.get("/v1/messaging/threads", response_model=Page[ThreadOut], include_in_schema=False)
async def list_threads(actor: CurrentActor, session: DbSession, cursor: str | None = None,
    contextType: str | None = Query(None, pattern="^(PROPOSAL_REQUEST|CONTRACT|DISPUTE)$"),
    contextId: uuid.UUID | None = None,
    limit: int = Query(30, ge=1, le=100)):
    return await service.list_threads(session, actor, cursor, limit, context_type=contextType, context_id=contextId)


@router.get("/v1/threads/summary", response_model=UnreadSummaryOut)
@router.get("/v1/messaging/threads/summary", response_model=UnreadSummaryOut, include_in_schema=False)
async def summary(actor: CurrentActor, session: DbSession):
    return await service.unread_summary(session, actor)


@router.get("/v1/threads/{thread_id}", response_model=ThreadOut)
@router.get("/v1/messaging/threads/{thread_id}", response_model=ThreadOut, include_in_schema=False)
async def get_thread(thread_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    thread, can_send = await service.checked_thread(session, actor, thread_id)
    return await service.thread_out(session, actor, thread, can_send)


@router.get("/v1/threads/{thread_id}/messages", response_model=Page[MessageOut])
@router.get("/v1/messaging/threads/{thread_id}/messages", response_model=Page[MessageOut], include_in_schema=False)
async def messages(thread_id: uuid.UUID, actor: CurrentActor, session: DbSession,
    before: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=100)):
    return await service.list_messages(session, actor, thread_id, before, limit)


@router.post("/v1/threads/{thread_id}/messages", response_model=MessageOut, status_code=201)
@router.post("/v1/messaging/threads/{thread_id}/messages", response_model=MessageOut, status_code=201, include_in_schema=False)
async def send(thread_id: uuid.UUID, body: MessageIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.send_message(session, actor, thread_id, body), status_code=201)


@router.post("/v1/threads/{thread_id}/read", status_code=204)
@router.post("/v1/messaging/threads/{thread_id}/read", status_code=204, include_in_schema=False)
async def read(thread_id: uuid.UUID, body: ReadIn, actor: CurrentActor, session: DbSession):
    await service.mark_read(session, actor, thread_id, body.throughSequence)


@router.post("/v1/threads/{thread_id}/attachments", response_model=AttachmentOut, status_code=201)
@router.post("/v1/messaging/threads/{thread_id}/attachments", response_model=AttachmentOut, status_code=201, include_in_schema=False)
async def upload(thread_id: uuid.UUID, body: UploadIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    return await idem.run(session, actor, lambda: service.upload(session, actor, thread_id, body), status_code=201)


@router.get("/v1/threads/{thread_id}/attachments/{file_id}")
@router.get("/v1/messaging/threads/{thread_id}/attachments/{file_id}", include_in_schema=False)
async def download(thread_id: uuid.UUID, file_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    file, data = await service.download(session, actor, thread_id, file_id)
    return Response(data, media_type=file.content_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file.name)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})
