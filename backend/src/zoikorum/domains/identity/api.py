from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from zoikorum.config import get_settings
from zoikorum.shared.errors import ValidationFailed
from pydantic import BaseModel, Field
from zoikorum.domains.identity import duplicates, passkeys, privacy_requests, risk, service
from zoikorum.domains.identity.schemas import (
    MfaVerifyOut,
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
from zoikorum.domains.admin import facade as admin_facade
from zoikorum.domains.admin.facade import ApprovalRequestOut
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession, session_factory
from zoikorum.shared.errors import RateLimited, Unauthenticated
from zoikorum.shared.http import Page, enforce_budget

# risk.bind_request keeps the caller's address and coarse location for the sign-in risk signals (identity/risk.py).
router = APIRouter(prefix="/v1", tags=["identity"], dependencies=[Depends(risk.bind_request)])
# Outside /v1: the public signing keys (RFC 8414 / OpenID-style well-known address), mounted by main.py.
root_router = APIRouter(tags=["identity"])


def _ua(request: Request) -> str | None:
    return request.headers.get("User-Agent")


# The web app keeps its refresh token in an HttpOnly cookie that page scripts cannot read, so an injected script cannot
# steal a long-lived sign-in (Handbook: session security). The browser marks its requests with X-Zk-Client: web; when
# the cookie is used the refresh token is never put in a response body. Other API clients keep the token in the body.
REFRESH_COOKIE = "zk_refresh"


def _cookie_mode(request: Request) -> bool:
    return request.headers.get("X-Zk-Client") == "web" or REFRESH_COOKIE in request.cookies


def _issue(request: Request, response: Response, pair: TokenPair) -> TokenPair:
    if not _cookie_mode(request):
        return pair
    s = get_settings()
    response.set_cookie(REFRESH_COOKIE, pair.refreshToken, max_age=s.refresh_token_ttl_seconds, path="/v1/auth",
                        httponly=True, samesite="strict", secure=s.env not in ("local", "development", "test"))
    return pair.model_copy(update={"refreshToken": ""})


def _forget(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/v1/auth")


def _expose_dev_tokens() -> bool:
    # Local development and tests only: everywhere else (staging included) links arrive by email, never in a response.
    return get_settings().env in ("local", "development", "test")


@router.post("/auth/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, request: Request, response: Response, session: DbSession) -> RegisterOut:
    identity, pair, confirm = await service.register(session, body, _ua(request))
    return RegisterOut(
        tokens=_issue(request, response, pair),
        user=service.to_out(identity, []),
        emailConfirmationToken=confirm if _expose_dev_tokens() else None,
    )


@router.post("/auth/confirm-email", response_model=IdentityOut)
async def confirm_email(body: ConfirmEmailIn, session: DbSession) -> IdentityOut:
    identity = await service.confirm_email(session, body.token)
    return service.to_out(identity, [])


@router.post("/auth/login", response_model=AuthOut)
async def login(body: LoginIn, request: Request, response: Response) -> AuthOut:
    await enforce_budget("login-email", body.email.lower(), 10, 10, "Too many sign-in attempts for this account. Wait a minute and try again.")
    # Own transaction: a failed attempt must still commit its lockout counter.
    async with session_factory()() as session:
        async with session.begin():
            result = await service.login(session, body.email, body.password, body.totpCode, _ua(request), body.recoveryCode,
                                         body.portal)
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return result.model_copy(update={"tokens": _issue(request, response, result.tokens)})


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn, request: Request, response: Response) -> TokenPair:
    token = body.refreshToken or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise Unauthenticated("Please sign in again", code="SESSION_EXPIRED")
    # Own transaction: refresh-token reuse must revoke the family even though we reject.
    async with session_factory()() as session:
        async with session.begin():
            result = await service.refresh(session, token, _ua(request))
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return _issue(request, response, result)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(actor: CurrentActor, session: DbSession, response: Response) -> None:
    await service.logout(session, actor)
    _forget(response)


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


@router.post("/auth/mfa/verify", response_model=MfaVerifyOut)
async def mfa_verify(body: MfaVerifyIn, request: Request, response: Response, actor: CurrentActor, session: DbSession) -> MfaVerifyOut:
    """Turns two-step verification on, returns one-time recovery codes (shown only now) and upgrades this sign-in to a
    two-step session (the same code cannot be used again for a step-up)."""
    codes = await service.verify_mfa(session, actor, body.totpCode)
    if not codes:  # already on: nothing new to issue
        return MfaVerifyOut(recoveryCodes=[])
    pair = await service.elevate_after_enrollment(session, actor, _ua(request))
    return MfaVerifyOut(recoveryCodes=codes, tokens=_issue(request, response, pair))


@router.post("/auth/mfa/recovery-codes", response_model=RecoveryCodesOut)
async def mfa_recovery_codes(actor: CurrentActor, session: DbSession) -> RecoveryCodesOut:
    """Replace all recovery codes (needs a fresh two-step confirmation)."""
    return RecoveryCodesOut(recoveryCodes=await service.regenerate_recovery_codes(session, actor))


@router.post("/auth/step-up", response_model=TokenPair)
async def step_up(body: StepUpIn, request: Request, response: Response, actor: CurrentActor) -> TokenPair:
    # Own transaction: a wrong code must still commit its lockout counter.
    async with session_factory()() as session:
        async with session.begin():
            result = await service.step_up(session, actor, body.totpCode, _ua(request))
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return _issue(request, response, result)


# ---- Passkeys ----------------------------------------------------------------------------------------------------------

@router.post("/auth/passkey/options")
async def passkey_login_options(session: DbSession) -> dict:
    """Start signing in with a passkey: the browser picks one of the passkeys it holds for this site."""
    return await passkeys.login_options(session)


@router.post("/auth/passkey", response_model=AuthOut)
async def passkey_login(body: PasskeyLoginIn, request: Request, response: Response) -> AuthOut:
    # Own transaction: a failed attempt must still commit its lockout counter and use up the challenge.
    async with session_factory()() as session:
        async with session.begin():
            result = await passkeys.login(session, body.credential, _ua(request), body.portal)
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return result.model_copy(update={"tokens": _issue(request, response, result.tokens)})


@router.post("/auth/step-up/passkey/options")
async def passkey_step_up_options(actor: CurrentActor, session: DbSession) -> dict:
    return await passkeys.step_up_options(session, actor)


@router.post("/auth/step-up/passkey", response_model=TokenPair)
async def passkey_step_up(body: PasskeyStepUpIn, request: Request, response: Response, actor: CurrentActor) -> TokenPair:
    """Confirm a sensitive action with a passkey instead of the 6-digit code."""
    async with session_factory()() as session:
        async with session.begin():
            result = await passkeys.step_up(session, actor, body.credential, _ua(request))
    if isinstance(result, service.LoginFailure):
        raise Unauthenticated(result.detail, code=result.code)
    return _issue(request, response, result)


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
async def add_account_type(body: AddPersonaIn, request: Request, response: Response, actor: CurrentActor,
                           session: DbSession) -> AuthOut:
    """Add Buyer or Professional to an existing account; returns fresh tokens with the new role."""
    result = await service.add_persona(session, actor, body.accountType, _ua(request))
    return result.model_copy(update={"tokens": _issue(request, response, result.tokens)})


@router.delete("/me/account-types/{account_type}", response_model=AuthOut)
async def remove_account_type(account_type: Literal["BUYER", "PROFESSIONAL"], request: Request, response: Response,
                              actor: CurrentActor, session: DbSession) -> AuthOut:
    """Remove Buyer or Professional from an account that holds more than one role."""
    result = await service.remove_persona(session, actor, account_type, _ua(request))
    return result.model_copy(update={"tokens": _issue(request, response, result.tokens)})


# ---- Platform staff administration (Platform Admin, MFA + step-up) -------------

@router.get("/admin/staff", response_model=list[StaffMemberOut])
async def list_staff(actor: CurrentActor, session: DbSession) -> list[StaffMemberOut]:
    return await service.list_staff(session, actor)


@router.post("/admin/identities/{identity_id}/platform-roles", status_code=status.HTTP_202_ACCEPTED,
             response_model=ApprovalRequestOut)
async def grant_role(identity_id: uuid.UUID, body: GrantRoleIn, actor: CurrentActor, session: DbSession) -> dict:
    """Platform Admin: ask to grant a staff role, optionally until ``expiresAt`` (just-in-time). 202: a maker-checker
    approval request (GRANT_PLATFORM_ROLE, status REQUESTED). The role is granted only when another Platform Admin, not
    the person receiving it, approves it. Nobody can ask for a role for themselves."""
    payload = {"identityId": str(identity_id), "role": body.role,
               "expiresAt": body.expiresAt.isoformat() if body.expiresAt else None}
    return await admin_facade.request_approval(session, actor, "GRANT_PLATFORM_ROLE", payload, body.justification)


@router.post("/admin/identities/{identity_id}/mfa-reset", response_model=IdentityOut)
async def mfa_reset(identity_id: uuid.UUID, body: MfaResetIn, actor: CurrentActor, session: DbSession) -> IdentityOut:
    """Platform Admin: remove two-step verification for someone who lost their authenticator and recovery codes, after
    confirming who they are. They set it up again at their next sign-in."""
    return service.to_out(await service.reset_mfa(session, actor, identity_id, body.reason), [])


@router.delete("/admin/identities/{identity_id}/platform-roles/{role}", status_code=status.HTTP_202_ACCEPTED,
               response_model=ApprovalRequestOut)
async def revoke_role(identity_id: uuid.UUID, role: str, actor: CurrentActor, session: DbSession,
                      justification: str = Query(min_length=10, max_length=2000)) -> dict:
    """Platform Admin: ask to remove a staff role. 202: a maker-checker approval request (REVOKE_PLATFORM_ROLE). When
    another Platform Admin approves it the role is removed and the person is signed out everywhere."""
    return await admin_facade.request_approval(session, actor, "REVOKE_PLATFORM_ROLE",
                                               {"identityId": str(identity_id), "role": role}, justification)


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


# ---- Single sign-on and SCIM (identity/sso.py, identity/scim.py) ---------------------------------------------------------

class SsoStartIn(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    provider: Literal["google", "microsoft"] | None = None


class SsoCallbackIn(BaseModel):
    code: str = Field(min_length=1, max_length=4000)
    state: str = Field(min_length=1, max_length=100)


class SsoConnectionIn(BaseModel):
    # OIDC: issuer, client id and secret. SAML: the identity provider's metadata XML, or its entity id, sign-on address
    # and signing certificate.
    protocol: Literal["OIDC", "SAML"] = "OIDC"
    issuer: str | None = Field(default=None, min_length=8, max_length=500, pattern=r"^https://")
    clientId: str | None = Field(default=None, min_length=1, max_length=300)
    samlMetadataXml: str | None = Field(default=None, max_length=200_000)
    samlEntityId: str | None = Field(default=None, max_length=500)
    samlSsoUrl: str | None = Field(default=None, max_length=1000)
    samlCertificate: str | None = Field(default=None, max_length=20_000)
    # SCIM groups to organisation roles, e.g. {"Finance approvers": "APPROVER"}; null: keep the current map.
    groupRoleMap: dict[str, Literal["REQUESTER", "APPROVER", "BUDGET_OWNER", "LEGAL_REVIEWER", "EXCEPTION_AUTHORITY"]] | None = None
    clientSecret: str | None = Field(default=None, max_length=2000)  # empty on update: keep the stored one
    emailDomains: list[str] = Field(min_length=1, max_length=20)
    enforce: bool = False
    justInTime: bool = True
    defaultRoles: list[Literal["REQUESTER", "APPROVER", "BUDGET_OWNER", "LEGAL_REVIEWER", "EXCEPTION_AUTHORITY"]] = ["REQUESTER"]
    enabled: bool = True


@router.get("/auth/sso/providers")
async def sso_providers() -> dict:
    """Which of Google and Microsoft sign-in this installation offers."""
    from zoikorum.domains.identity import sso
    return sso.providers()


@router.post("/auth/sso/start")
async def sso_start(body: SsoStartIn, session: DbSession) -> dict:
    """Where to send the browser: the organisation's identity provider (by email domain), Google or Microsoft."""
    from zoikorum.domains.identity import sso
    await enforce_budget("sso-start", body.email or body.provider or "", 20, 20, "Too many sign-in attempts. Wait a minute and try again.")
    return await sso.start(session, email=body.email, provider=body.provider)


@router.post("/auth/sso/link")
async def sso_link(body: SsoStartIn, actor: CurrentActor, session: DbSession) -> dict:
    """Signed in: connect Google or Microsoft to this account (needs a fresh two-step check)."""
    from zoikorum.domains.identity import sso
    if not body.provider:
        raise ValidationFailed("Choose Google or Microsoft")
    actor.require_step_up()
    return await sso.start(session, provider=body.provider, link_actor=actor)


@router.post("/auth/sso/callback", response_model=AuthOut)
async def sso_callback(body: SsoCallbackIn, request: Request, response: Response) -> AuthOut:
    from zoikorum.domains.identity import sso
    async with session_factory()() as session:
        async with session.begin():
            result = await sso.callback(session, body.code, body.state, _ua(request))
    return result.model_copy(update={"tokens": _issue(request, response, result.tokens)})


@router.get("/organizations/{org_id}/sso")
async def get_sso(org_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    from zoikorum.domains.identity import sso
    return await sso.get_connection(session, actor, org_id)


@router.put("/organizations/{org_id}/sso")
async def set_sso(org_id: uuid.UUID, body: SsoConnectionIn, actor: CurrentActor, session: DbSession) -> dict:
    """Organisation Admin: connect the organisation's OpenID Connect identity provider (Okta, Entra ID, Google Workspace...)."""
    from zoikorum.domains.identity import sso
    return await sso.set_connection(session, actor, org_id, body)


@router.post("/organizations/{org_id}/sso/scim-token")
async def scim_token(org_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """Organisation Admin: a new SCIM token for automatic provisioning (shown once; the old one stops working)."""
    from zoikorum.domains.identity import sso
    return await sso.rotate_scim_token(session, actor, org_id)


@router.get("/scim/v2/ServiceProviderConfig")
async def scim_config() -> dict:
    from zoikorum.domains.identity import scim
    return scim.SERVICE_PROVIDER_CONFIG


@router.get("/scim/v2/Users")
async def scim_list(request: Request, session: DbSession, filter: str | None = None, startIndex: int = 1, count: int = 100) -> dict:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    return await scim.list_users(session, c, filter, max(1, startIndex), max(0, min(count, 200)))


@router.post("/scim/v2/Users", status_code=status.HTTP_201_CREATED)
async def scim_create(body: dict, request: Request, session: DbSession) -> dict:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    return await scim.create_user(session, c, body)


@router.get("/scim/v2/Users/{user_id}")
async def scim_get(user_id: str, request: Request, session: DbSession) -> dict:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    return await scim.get_user(session, c, user_id)


@router.put("/scim/v2/Users/{user_id}")
@router.patch("/scim/v2/Users/{user_id}")
async def scim_update(user_id: str, body: dict, request: Request, session: DbSession) -> dict:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    return await scim.update_user(session, c, user_id, body)


@router.delete("/scim/v2/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def scim_delete(user_id: str, request: Request, session: DbSession) -> Response:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    await scim.delete_user(session, c, user_id)
    return Response(status_code=204)



# ---- SAML 2.0 service provider (identity/saml.py) -------------------------------------------------------------------------

@router.get("/auth/saml/metadata", response_class=Response)
async def saml_metadata() -> Response:
    """This service provider's SAML metadata (entity id and assertion consumer service), for the identity provider."""
    from zoikorum.domains.identity import saml
    return Response(saml.sp_metadata(), media_type="application/samlmetadata+xml")


@router.post("/auth/saml/acs", status_code=status.HTTP_303_SEE_OTHER, response_class=Response)
async def saml_acs(request: Request) -> Response:
    """Assertion consumer service (HTTP-POST binding): the identity provider posts SAMLResponse and RelayState here; the
    browser is sent on to the web app's /sso/callback with a one-time code, which POST /v1/auth/sso/callback redeems."""
    from urllib.parse import parse_qs

    from zoikorum.domains.identity import sso
    body = await request.body()
    if len(body) > 512 * 1024:
        raise ValidationFailed("The sign-in response is too large")
    form = parse_qs(body.decode("utf-8", "replace"), max_num_fields=10)
    await enforce_budget("saml-acs", request.client.host if request.client else "", 30, 30, "Too many sign-in attempts.")
    # Own transaction: a refused response must still burn its request.
    async with session_factory()() as session:
        async with session.begin():
            target = await sso.saml_acs(session, (form.get("SAMLResponse") or [None])[0], (form.get("RelayState") or [None])[0])
    return Response(status_code=303, headers={"Location": target, "Cache-Control": "no-store"})


# ---- SCIM 2.0 Groups (identity/scim.py) -------------------------------------------------------------------------------------

@router.get("/scim/v2/Groups")
async def scim_groups(request: Request, session: DbSession, filter: str | None = None, startIndex: int = 1, count: int = 100) -> dict:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    return await scim.list_groups(session, c, filter, max(1, startIndex), max(0, min(count, 200)))


@router.post("/scim/v2/Groups", status_code=status.HTTP_201_CREATED)
async def scim_group_create(body: dict, request: Request, session: DbSession) -> dict:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    return await scim.create_group(session, c, body)


@router.get("/scim/v2/Groups/{group_id}")
async def scim_group(group_id: str, request: Request, session: DbSession) -> dict:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    return await scim.get_group(session, c, group_id)


@router.put("/scim/v2/Groups/{group_id}")
@router.patch("/scim/v2/Groups/{group_id}")
async def scim_group_update(group_id: str, body: dict, request: Request, session: DbSession) -> dict:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    return await scim.update_group(session, c, group_id, body)


@router.delete("/scim/v2/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def scim_group_delete(group_id: str, request: Request, session: DbSession) -> Response:
    from zoikorum.domains.identity import scim
    c = await scim.connection_for(session, request.headers.get("Authorization"))
    await scim.delete_group(session, c, group_id)
    return Response(status_code=204)


# ---- Enterprise session policy (identity/session_policy.py) -----------------------------------------------------------------

class SessionPolicyIn(BaseModel):
    maxSessionSeconds: int | None = Field(default=None, ge=900, le=90 * 24 * 3600)
    idleTimeoutSeconds: int | None = Field(default=None, ge=300, le=30 * 24 * 3600)
    requireMfa: bool = False
    allowedIdps: list[Literal["PASSWORD", "PASSKEY", "OIDC", "SAML", "GOOGLE", "MICROSOFT"]] = Field(default_factory=list, max_length=6)


@router.get("/organizations/{org_id}/session-policy")
async def get_session_policy(org_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """The organisation's rules for its members' sessions (Organisation Admin)."""
    from zoikorum.domains.identity import session_policy
    return await session_policy.get_policy(session, actor, org_id)


@router.put("/organizations/{org_id}/session-policy")
async def set_session_policy(org_id: uuid.UUID, body: SessionPolicyIn, actor: CurrentActor, session: DbSession) -> dict:
    """Set the session rules (needs a fresh two-step check). Members' sessions follow them from their next refresh."""
    from zoikorum.domains.identity import session_policy
    return await session_policy.set_policy(session, actor, org_id, body)


# ---- Sign-in risk signals (identity/risk.py) ----------------------------------------------------------------------------------

@router.get("/me/sign-in-signals")
async def my_sign_in_signals(actor: CurrentActor, session: DbSession) -> list[dict]:
    """My recent sign-ins with advisory risk signals (new device, new country, impossible travel, velocity)."""
    return await service.sign_in_signals(session, actor)


@router.get("/admin/identities/{identity_id}/sign-in-signals")
async def account_sign_in_signals(identity_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> list[dict]:
    """Staff (account access): an account's recent sign-ins with their risk signals."""
    actor.require_capability("accounts.read")
    return await service.sign_in_signals(session, actor, identity_id)


# ---- Public signing keys (shared/signing_keys.py) -----------------------------------------------------------------------------

@root_router.get("/.well-known/jwks.json")
async def jwks(response: Response) -> dict:
    """The public keys Zoikorum's RS256 sign-in tokens are signed with (empty while tokens use the shared secret)."""
    from zoikorum.shared import signing_keys
    response.headers["Cache-Control"] = "public, max-age=300"
    return signing_keys.jwks()
