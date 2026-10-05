from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from zoikorum.config import get_settings
from zoikorum.domains.identity import service
from zoikorum.domains.identity.schemas import (
    ConfirmEmailIn,
    GrantRoleIn,
    IdentityOut,
    LoginIn,
    MfaEnrollOut,
    MfaVerifyIn,
    RefreshIn,
    RegisterIn,
    RegisterOut,
    StepUpIn,
    TokenPair,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession, session_factory
from zoikorum.shared.errors import Unauthenticated

router = APIRouter(prefix="/v1", tags=["identity"])


def _ua(request: Request) -> str | None:
    return request.headers.get("User-Agent")


@router.post("/auth/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, request: Request, session: DbSession) -> RegisterOut:
    identity, pair, confirm = await service.register(session, body, _ua(request))
    expose = get_settings().env != "production"
    return RegisterOut(
        identity=service.to_out(identity, []),
        tokens=pair,
        emailConfirmationToken=confirm if expose else None,
    )


@router.post("/auth/confirm-email", response_model=IdentityOut)
async def confirm_email(body: ConfirmEmailIn, session: DbSession) -> IdentityOut:
    identity = await service.confirm_email(session, body.token)
    return service.to_out(identity, [])


@router.post("/auth/login", response_model=TokenPair)
async def login(body: LoginIn, request: Request) -> TokenPair:
    # Own transaction: a failed attempt must still commit its lockout counter.
    async with session_factory()() as session:
        async with session.begin():
            result = await service.login(session, body.email, body.password, body.totpCode, _ua(request))
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return result


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn, request: Request) -> TokenPair:
    # Own transaction: refresh-token reuse must revoke the family even though we reject.
    async with session_factory()() as session:
        async with session.begin():
            result = await service.refresh(session, body.refreshToken, _ua(request))
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return result


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(actor: CurrentActor, session: DbSession) -> None:
    await service.logout(session, actor)


@router.post("/auth/mfa/enroll", response_model=MfaEnrollOut)
async def mfa_enroll(actor: CurrentActor, session: DbSession) -> MfaEnrollOut:
    secret, uri = await service.enroll_mfa(session, actor)
    return MfaEnrollOut(secret=secret, otpauthUri=uri)


@router.post("/auth/mfa/verify", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_verify(body: MfaVerifyIn, actor: CurrentActor, session: DbSession) -> None:
    await service.verify_mfa(session, actor, body.totpCode)


@router.post("/auth/step-up", response_model=TokenPair)
async def step_up(body: StepUpIn, request: Request, actor: CurrentActor, session: DbSession) -> TokenPair:
    return await service.step_up(session, actor, body.totpCode, _ua(request))


@router.get("/me", response_model=IdentityOut)
async def me(actor: CurrentActor, session: DbSession) -> IdentityOut:
    return await service.get_me(session, actor)


@router.post("/admin/identities/{identity_id}/platform-roles", response_model=IdentityOut)
async def grant_role(identity_id: uuid.UUID, body: GrantRoleIn, actor: CurrentActor, session: DbSession) -> IdentityOut:
    identity = await service.grant_platform_role(session, actor, identity_id, body.role)
    return service.to_out(identity, [])
