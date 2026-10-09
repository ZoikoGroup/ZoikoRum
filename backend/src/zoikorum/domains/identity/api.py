from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Request, Response, status

from zoikorum.config import get_settings
from zoikorum.domains.identity import duplicates, privacy_requests, service
from zoikorum.domains.identity.schemas import (
    DataRequestIn,
    DuplicateAnswerIn,
    DuplicateOut,
    DuplicateResolveIn,
    DataRequestOut,
    MePatch,
    ResendConfirmationOut,
    UserOut,
    SessionOut,
    AddPersonaIn,
    AuthOut,
    ConfirmEmailIn,
    ForgotPasswordIn,
    ForgotPasswordOut,
    GrantRoleIn,
    IdentityOut,
    LoginIn,
    MfaEnrollOut,
    MfaVerifyIn,
    RefreshIn,
    RegisterIn,
    RegisterOut,
    ResetPasswordIn,
    StaffMemberOut,
    StepUpIn,
    TokenPair,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession, session_factory
from zoikorum.shared.errors import Unauthenticated
from zoikorum.shared.http import Page

router = APIRouter(prefix="/v1", tags=["identity"])


def _ua(request: Request) -> str | None:
    return request.headers.get("User-Agent")


def _expose_dev_tokens() -> bool:
    # Local development and tests only: everywhere else (staging included) links arrive by email, never in a response.
    return get_settings().env in ("local", "development", "test")


@router.post("/auth/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, request: Request, session: DbSession) -> RegisterOut:
    identity, pair, confirm = await service.register(session, body, _ua(request))
    return RegisterOut(
        tokens=pair,
        user=service.to_out(identity, []),
        emailConfirmationToken=confirm if _expose_dev_tokens() else None,
    )


@router.post("/auth/confirm-email", response_model=IdentityOut)
async def confirm_email(body: ConfirmEmailIn, session: DbSession) -> IdentityOut:
    identity = await service.confirm_email(session, body.token)
    return service.to_out(identity, [])


@router.post("/auth/login", response_model=AuthOut)
async def login(body: LoginIn, request: Request) -> AuthOut:
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


@router.post("/auth/password/forgot", response_model=ForgotPasswordOut, status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: ForgotPasswordIn, session: DbSession) -> ForgotPasswordOut:
    token = await service.request_password_reset(session, body.email)
    # Same response whether or not the email exists (no account enumeration).
    return ForgotPasswordOut(resetToken=token if _expose_dev_tokens() else None)


@router.post("/auth/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: ResetPasswordIn, session: DbSession) -> None:
    await service.reset_password(session, body.token, body.newPassword)


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


@router.patch("/me", response_model=IdentityOut)
async def update_me(body: MePatch, actor: CurrentActor, session: DbSession) -> IdentityOut:
    """Settings > Account: display name, phone (stored encrypted), language, time zone."""
    return await service.update_me(session, actor, body)


@router.get("/me/sessions", response_model=list[SessionOut])
async def my_sessions(actor: CurrentActor, session: DbSession):
    """Settings > Security: devices currently signed in."""
    return await service.list_sessions(session, actor)


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out_device(session_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.revoke_session(session, actor, session_id)


@router.post("/me/email-confirmation", response_model=ResendConfirmationOut)
async def resend_email_confirmation(actor: CurrentActor, session: DbSession) -> ResendConfirmationOut:
    """Send a new email-confirmation link (at most one a minute)."""
    token = await service.resend_email_confirmation(session, actor)
    return ResendConfirmationOut(emailConfirmationToken=token if _expose_dev_tokens() else None)


@router.post("/me/data-requests", response_model=DataRequestOut, status_code=status.HTTP_201_CREATED)
async def create_data_request(body: DataRequestIn, actor: CurrentActor, session: DbSession):
    """Settings > Privacy: download my data (ACCESS) or delete my account (ERASURE, two-step check, 14-day cooling-off)."""
    return await privacy_requests.create(session, actor, body.requestType)


@router.post("/me/data-requests/{request_id}/cancel", response_model=DataRequestOut)
async def cancel_data_request(request_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    """Cancel a scheduled account deletion."""
    return await privacy_requests.cancel(session, actor, request_id)


@router.get("/me/data-requests/{request_id}/download")
async def download_data_export(request_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> Response:
    """The data export file (two-step check; audited; never cached)."""
    data, name = await privacy_requests.download(session, actor, request_id)
    return Response(data, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/me/data-requests", response_model=list[DataRequestOut])
async def data_requests(actor: CurrentActor, session: DbSession):
    return await privacy_requests.mine(session, actor)


@router.post("/me/account-types", response_model=AuthOut)
async def add_account_type(body: AddPersonaIn, request: Request, actor: CurrentActor, session: DbSession) -> AuthOut:
    """Add Buyer or Professional to an existing account; returns fresh tokens with the new role."""
    return await service.add_persona(session, actor, body.accountType, _ua(request))


# ---- Platform staff administration (Platform Admin, MFA + step-up) -------------

@router.get("/admin/staff", response_model=list[StaffMemberOut])
async def list_staff(actor: CurrentActor, session: DbSession) -> list[StaffMemberOut]:
    return await service.list_staff(session, actor)


@router.post("/admin/identities/{identity_id}/platform-roles", response_model=IdentityOut)
async def grant_role(identity_id: uuid.UUID, body: GrantRoleIn, actor: CurrentActor, session: DbSession) -> IdentityOut:
    identity = await service.grant_platform_role(session, actor, identity_id, body.role)
    return service.to_out(identity, [])


@router.delete("/admin/identities/{identity_id}/platform-roles/{role}", response_model=IdentityOut)
async def revoke_role(identity_id: uuid.UUID, role: str, actor: CurrentActor, session: DbSession) -> IdentityOut:
    identity = await service.revoke_platform_role(session, actor, identity_id, role)
    return service.to_out(identity, [])


@router.get("/admin/users", response_model=Page[UserOut])
async def list_users(actor: CurrentActor, session: DbSession, q: str | None = Query(default=None, max_length=200),
                     role: str | None = None, status_: Literal["ACTIVE", "SUSPENDED", "DELETED"] | None = Query(default=None, alias="status"),
                     cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    """Platform Admin / Trust & Safety: every account, searchable. Reads are audited."""
    return await service.list_users(session, actor, q, role, status_, cursor, limit)


@router.get("/admin/identities/lookup", response_model=StaffMemberOut)
async def lookup_identity(email: str, actor: CurrentActor, session: DbSession) -> StaffMemberOut:
    """Find an account by email so an admin can grant it a staff role."""
    return await service.lookup_by_email(session, actor, email)



@router.get("/me/duplicate-accounts", response_model=list[DuplicateOut])
async def my_duplicates(actor: CurrentActor, session: DbSession):
    """Possible duplicate accounts for the signed-in person (Onboarding s.20)."""
    return await duplicates.mine(session, actor)


@router.post("/me/duplicate-accounts/{suspicion_id}/answer", response_model=DuplicateOut)
async def answer_duplicate(suspicion_id: uuid.UUID, body: DuplicateAnswerIn, actor: CurrentActor, session: DbSession):
    """Ask support to merge the accounts, or say the other account is not yours."""
    return await duplicates.answer(session, actor, suspicion_id, body)


@router.get("/admin/duplicate-accounts", response_model=list[DuplicateOut])
async def duplicate_queue(actor: CurrentActor, session: DbSession):
    return await duplicates.queue(session, actor)


@router.post("/admin/duplicate-accounts/{suspicion_id}/resolve", response_model=DuplicateOut)
async def resolve_duplicate(suspicion_id: uuid.UUID, body: DuplicateResolveIn, actor: CurrentActor, session: DbSession):
    """Support decision (step-up): MERGED closes the duplicate and keeps the chosen account; NOT_DUPLICATE dismisses."""
    return await duplicates.resolve(session, actor, suspicion_id, body)
