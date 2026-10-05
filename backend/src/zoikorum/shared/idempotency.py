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
