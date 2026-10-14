from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Request, Response, status

from zoikorum.config import get_settings
from zoikorum.domains.identity import duplicates, passkeys, privacy_requests, service
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
    MfaResetIn,
    MfaVerifyIn,
    PasskeyLoginIn,
    PasskeyOptionsIn,
    PasskeyOut,
    PasskeyRegisterIn,
    PasskeyStepUpIn,
    RecoveryCodesOut,
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
from zoikorum.shared.errors import RateLimited, Unauthenticated
from zoikorum.shared.http import Page, enforce_budget

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
    await enforce_budget("login-email", body.email.lower(), 10, 10, "Too many sign-in attempts for this account. Wait a minute and try again.")
    # Own transaction: a failed attempt must still commit its lockout counter.
    async with session_factory()() as session:
        async with session.begin():
            result = await service.login(session, body.email, body.password, body.totpCode, _ua(request), body.recoveryCode,
                                         body.portal)
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
    # A few reset emails an hour per address: nobody can flood someone's inbox from many addresses.
    await enforce_budget("reset-email", str(body.email).lower(), 3, 3, "A reset email was sent recently. Check your inbox, or try again later.")
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


@router.post("/auth/mfa/verify", response_model=RecoveryCodesOut)
async def mfa_verify(body: MfaVerifyIn, actor: CurrentActor, session: DbSession) -> RecoveryCodesOut:
    """Turns two-step verification on and returns one-time recovery codes (shown only now)."""
    return RecoveryCodesOut(recoveryCodes=await service.verify_mfa(session, actor, body.totpCode))


@router.post("/auth/mfa/recovery-codes", response_model=RecoveryCodesOut)
async def mfa_recovery_codes(actor: CurrentActor, session: DbSession) -> RecoveryCodesOut:
    """Replace all recovery codes (needs a fresh two-step confirmation)."""
    return RecoveryCodesOut(recoveryCodes=await service.regenerate_recovery_codes(session, actor))


@router.post("/auth/step-up", response_model=TokenPair)
async def step_up(body: StepUpIn, request: Request, actor: CurrentActor) -> TokenPair:
    # Own transaction: a wrong code must still commit its lockout counter.
    async with session_factory()() as session:
        async with session.begin():
            result = await service.step_up(session, actor, body.totpCode, _ua(request))
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return result


# ---- Passkeys ----------------------------------------------------------------------------------------------------------

@router.post("/auth/passkey/options")
async def passkey_login_options(session: DbSession) -> dict:
    """Start signing in with a passkey: the browser picks one of the passkeys it holds for this site."""
    return await passkeys.login_options(session)


@router.post("/auth/passkey", response_model=AuthOut)
async def passkey_login(body: PasskeyLoginIn, request: Request) -> AuthOut:
    # Own transaction: a failed attempt must still commit its lockout counter and use up the challenge.
    async with session_factory()() as session:
        async with session.begin():
            result = await passkeys.login(session, body.credential, _ua(request), body.portal)
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return result


@router.post("/auth/step-up/passkey/options")
async def passkey_step_up_options(actor: CurrentActor, session: DbSession) -> dict:
    return await passkeys.step_up_options(session, actor)


@router.post("/auth/step-up/passkey", response_model=TokenPair)
async def passkey_step_up(body: PasskeyStepUpIn, request: Request, actor: CurrentActor) -> TokenPair:
    """Confirm a sensitive action with a passkey instead of the 6-digit code."""
    async with session_factory()() as session:
        async with session.begin():
            result = await passkeys.step_up(session, actor, body.credential, _ua(request))
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return result


@router.get("/me/passkeys", response_model=list[PasskeyOut])
async def my_passkeys(actor: CurrentActor, session: DbSession):
    return await passkeys.list_passkeys(session, actor)


@router.post("/me/passkeys/options")
async def passkey_registration_options(body: PasskeyOptionsIn, actor: CurrentActor, session: DbSession) -> dict:
    """Start adding a passkey (needs the account password)."""
    await enforce_budget("passkey-add", str(actor.identity_id), 5, 5, "Too many attempts. Wait a minute and try again.")
    return await passkeys.registration_options(session, actor, body.password)


@router.post("/me/passkeys", response_model=PasskeyOut, status_code=status.HTTP_201_CREATED)
async def add_passkey(body: PasskeyRegisterIn, actor: CurrentActor, session: DbSession):
    return await passkeys.register(session, actor, body.name, body.credential)


@router.delete("/me/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_passkey(passkey_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await passkeys.remove(session, actor, passkey_id)


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
    try:
        token = await service.resend_email_confirmation(session, actor)
    except RateLimited:
        if get_settings().env not in ("local", "development"):  # tests and servers keep the one-a-minute limit
            raise
        # Local development has no inbox: hand out the link again instead of making the developer wait (no email sent).
        return ResendConfirmationOut(message="Development mode: no email is sent locally.",
                                     emailConfirmationToken=await service.email_confirmation_link_token(session, actor))
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


@router.post("/admin/identities/{identity_id}/mfa-reset", response_model=IdentityOut)
async def mfa_reset(identity_id: uuid.UUID, body: MfaResetIn, actor: CurrentActor, session: DbSession) -> IdentityOut:
    """Platform Admin: remove two-step verification for someone who lost their authenticator and recovery codes, after
    confirming who they are. They set it up again at their next sign-in."""
    return service.to_out(await service.reset_mfa(session, actor, identity_id, body.reason), [])


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


@router.get("/admin/duplicate-accounts", response_model=Page[DuplicateOut])
async def duplicate_queue(actor: CurrentActor, session: DbSession, cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    """Oldest first, one page at a time (follow nextCursor)."""
    return await duplicates.queue(session, actor, cursor, limit)


@router.post("/admin/duplicate-accounts/{suspicion_id}/resolve", response_model=DuplicateOut)
async def resolve_duplicate(suspicion_id: uuid.UUID, body: DuplicateResolveIn, actor: CurrentActor, session: DbSession):
    """Support decision (step-up): MERGED closes the duplicate and keeps the chosen account; NOT_DUPLICATE dismisses."""
    return await duplicates.resolve(session, actor, suspicion_id, body)
