from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from zoikorum.domains.support import service
from zoikorum.domains.support.schemas import SupportReplyIn, SupportRequestIn, SupportRequestOut
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession

router = APIRouter(tags=["support"])


@router.post("/v1/support/requests", response_model=SupportRequestOut, status_code=201)
async def open_request(body: SupportRequestIn, actor: CurrentActor, session: DbSession):
    """Ask for help. Attach the page, engagement or error reference so the agent does not need to ask."""
    return await service.open_request(session, actor, body)


@router.get("/v1/support/requests", response_model=list[SupportRequestOut])
async def my_requests(actor: CurrentActor, session: DbSession):
    return await service.my_requests(session, actor)


@router.get("/v1/support/requests/{request_id}", response_model=SupportRequestOut)
async def get_request(request_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_mine(session, actor, request_id)


@router.post("/v1/support/requests/{request_id}/messages", response_model=SupportRequestOut)
async def reply(request_id: uuid.UUID, body: SupportReplyIn, actor: CurrentActor, session: DbSession):
    return await service.reply_mine(session, actor, request_id, body)


@router.post("/v1/support/requests/{request_id}/resolve", response_model=SupportRequestOut)
async def resolve(request_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.resolve_mine(session, actor, request_id)


@router.get("/v1/admin/support/requests", response_model=list[SupportRequestOut])
async def queue(actor: CurrentActor, session: DbSession, status: str | None = Query(default=None)):
    """Support agents: open requests, late first answers first."""
    return await service.queue(session, actor, status)


@router.get("/v1/admin/support/requests/{request_id}", response_model=SupportRequestOut)
async def agent_get(request_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_for_agent(session, actor, request_id)


@router.post("/v1/admin/support/requests/{request_id}/messages", response_model=SupportRequestOut)
async def agent_reply(request_id: uuid.UUID, body: SupportReplyIn, actor: CurrentActor, session: DbSession):
    return await service.agent_reply(session, actor, request_id, body)
