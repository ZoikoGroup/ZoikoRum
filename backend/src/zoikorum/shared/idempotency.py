"""API idempotency (Architecture 7.1 / Handbook ch. 12).

Every commercial mutation endpoint takes an ``Idempotency-Key`` header:

    @router.post("/v1/escrow/{id}/fund")
    async def fund(id: UUID, session: DbSession, actor: CurrentActor, idem: IdempotencyKey):
        return await idem.run(session, actor, lambda: service.fund(session, actor, id))

The key record is written in the SAME transaction as the business change, so
"stored response" and "side effect" can never diverge. A concurrent duplicate
blocks on the unique key until the first transaction commits, then replays.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.shared.errors import IdempotencyKeyRequired, IdempotencyKeyReused
from zoikorum.shared.platform_models import IdempotencyRecord

_IN_PROGRESS = 0


class Idempotency:
    def __init__(self, key: str | None, method: str, path: str, body: bytes, required: bool):
        self.key = key
        self.method = method
        self.path = path
        self.request_hash = hashlib.sha256(body).hexdigest()
        self.required = required

    async def run(
        self,
        session: AsyncSession,
        actor: Any,
        operation: Callable[[], Awaitable[Any]],
        *,
        status_code: int = 200,
    ) -> Any:
        if not self.key:
            if self.required:
                raise IdempotencyKeyRequired()
            return await operation()

        actor_id = getattr(actor, "identity_id", None) or "anonymous"
        scope = f"{actor_id}:{self.method}:{self.path}:{self.key}"[:300]
        inserted = await session.execute(
            pg_insert(IdempotencyRecord)
            .values(scope=scope, request_hash=self.request_hash, response_status=_IN_PROGRESS)
            .on_conflict_do_nothing()
            .returning(IdempotencyRecord.scope)
        )
        if inserted.scalar_one_or_none() is None:
            existing = await session.get(IdempotencyRecord, scope)
            if existing is None:  # pragma: no cover - deleted between statements
                return await operation()
            if existing.request_hash != self.request_hash:
                raise IdempotencyKeyReused()
            return JSONResponse(
                content=existing.response_body,
                status_code=existing.response_status,
                headers={"Idempotent-Replayed": "true"},
            )

        result = await operation()
        body = jsonable_encoder(result)
        await session.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.scope == scope)
            .values(response_status=status_code, response_body=body)
        )
        return result


def _dependency(required: bool):
    async def dep(
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
    ) -> Idempotency:
        body = await request.body()
        return Idempotency(idempotency_key, request.method, request.url.path, body, required)

    return dep


# Required on commercial mutations (proposals, contracts, escrow, payments, disputes).
IdempotencyKey = Annotated[Idempotency, Depends(_dependency(required=True))]
# Optional - honoured when the client sends it.
OptionalIdempotencyKey = Annotated[Idempotency, Depends(_dependency(required=False))]


async def lookup(session: AsyncSession, scope: str) -> IdempotencyRecord | None:
    return await session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.scope == scope))


# ---- Every other change: replay by key (Handbook ch. 12: Idempotency-Key on all mutation endpoints) ------------------

class IdempotencyMiddleware:
    """Honours ``Idempotency-Key`` on every signed-in POST/PUT/PATCH/DELETE: a retry with the same key and body gets the
    first answer back (header ``Idempotent-Replayed: true``) instead of doing the change twice; the same key with a
    different body is refused; a retry while the first is still running gets 409. Commercial endpoints additionally
    store their answer in the same transaction as the change (``IdempotencyKey`` above). Only successful JSON answers
    are kept; a failed request can be retried with the same key."""

    METHODS = {"POST", "PUT", "PATCH", "DELETE"}
    MAX_STORED = 512 * 1024

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in self.METHODS:
            return await self.app(scope, receive, send)
        from starlette.requests import Request

        request = Request(scope, receive)
        key = request.headers.get("idempotency-key")
        if not key:
            return await self.app(scope, receive, send)
        from zoikorum.shared.http import caller_key, problem

        kind, who = caller_key(request)
        if kind != "user":  # sign-up and sign-in have their own duplicate protection
            return await self.app(scope, receive, send)
        body = await request.body()

        async def replay_receive():
            return {"type": "http.request", "body": body, "more_body": False}

        record_scope = f"mw:{who}:{scope['method']}:{scope['path']}:{key}"[:300]
        request_hash = hashlib.sha256(body).hexdigest()
        from zoikorum.shared.db import session_factory

        async with session_factory()() as session, session.begin():
            inserted = await session.execute(
                pg_insert(IdempotencyRecord)
                .values(scope=record_scope, request_hash=request_hash, response_status=_IN_PROGRESS)
                .on_conflict_do_nothing().returning(IdempotencyRecord.scope))
            first = inserted.scalar_one_or_none() is not None
            existing = None if first else await session.get(IdempotencyRecord, record_scope)
        if existing is not None:
            from zoikorum.shared.errors import Conflict

            if existing.request_hash != request_hash:
                return await problem(IdempotencyKeyReused())(scope, replay_receive, send)
            if existing.response_status == _IN_PROGRESS:
                return await problem(Conflict("This request is still being processed. Wait a moment, then reload.",
                                              code="REQUEST_IN_PROGRESS"))(scope, replay_receive, send)
            return await JSONResponse(existing.response_body, status_code=existing.response_status,
                                      headers={"Idempotent-Replayed": "true"})(scope, replay_receive, send)

        status, chunks, is_json = 0, [], False

        async def capture(message):
            nonlocal status, is_json
            if message["type"] == "http.response.start":
                status = message["status"]
                is_json = any(k.lower() == b"content-type" and b"json" in v for k, v in message.get("headers", []))
            elif message["type"] == "http.response.body" and sum(map(len, chunks)) <= self.MAX_STORED:
                chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay_receive, capture)
        finally:
            raw = b"".join(chunks)
            keep = 200 <= status < 300 and is_json and raw and len(raw) <= self.MAX_STORED
            async with session_factory()() as session, session.begin():
                if keep:
                    import json

                    await session.execute(update(IdempotencyRecord).where(IdempotencyRecord.scope == record_scope)
                                          .values(response_status=status, response_body=json.loads(raw)))
                else:
                    from sqlalchemy import delete

                    await session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.scope == record_scope))
