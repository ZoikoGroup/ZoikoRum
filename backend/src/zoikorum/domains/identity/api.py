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


@router.post("/auth/logout", status_code=status.HTTP_200_OK)
async def logout(actor: CurrentActor, session: DbSession) -> None:
    await service.logout(session, actor)


@router.post("/auth/password/forgot", response_model=ForgotPasswordOut, status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: ForgotPasswordIn, session: DbSession) -> ForgotPasswordOut:
    token = await service.request_password_reset(session, body.email)
    # Same response whether or not the email exists (no account enumeration).
    return ForgotPasswordOut(resetToken=token if _expose_dev_tokens() else None)


@router.post("/auth/password/reset", status_code=status.HTTP_200_OK)
async def reset_password(body: ResetPasswordIn, session: DbSession) -> None:
    await service.reset_password(session, body.token, body.newPassword)


@router.post("/auth/mfa/enroll", response_model=MfaEnrollOut)
async def mfa_enroll(actor: CurrentActor, session: DbSession) -> MfaEnrollOut:
    secret, uri = await service.enroll_mfa(session, actor)
    return MfaEnrollOut(secret=secret, otpauthUri=uri)


@router.post("/auth/mfa/verify", status_code=status.HTTP_200_OK)
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


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_200_OK)
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


# Browser WebAuthn ceremonies. Public authentication options contain no account hints.
from pydantic import BaseModel, Field
from zoikorum.domains.identity import passkeys

class PasskeyResponseIn(BaseModel):
    challengeId: uuid.UUID
    credential: dict
    label: str = Field(default="Passkey", min_length=1, max_length=100)

@router.get("/me/passkeys")
async def my_passkeys(actor: CurrentActor, session: DbSession):
    return await passkeys.listing(session, actor)

@router.post("/me/passkeys/options")
async def registration_options(actor: CurrentActor, session: DbSession):
    return await passkeys.begin(session, actor=actor, registration=True)

@router.post("/me/passkeys", status_code=201)
async def register_passkey(body: PasskeyResponseIn, actor: CurrentActor, session: DbSession):
    await passkeys.register(session, actor, body.challengeId, body.credential, body.label)
    return {"registered": True}

@router.delete("/me/passkeys/{key_id}", status_code=204)
async def delete_passkey(key_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    await passkeys.remove(session, actor, key_id)

@router.post("/auth/passkeys/options")
async def authentication_options(session: DbSession):
    return await passkeys.begin(session)

@router.post("/auth/passkeys/verify", response_model=AuthOut)
async def authenticate_passkey(body: PasskeyResponseIn, request: Request, session: DbSession):
    return await passkeys.authenticate(session, body.challengeId, body.credential, _ua(request))

@router.post("/auth/passkeys/step-up/options")
async def passkey_step_up_options(actor: CurrentActor, session: DbSession):
    return await passkeys.begin(session, actor=actor)

@router.post("/auth/passkeys/step-up", response_model=AuthOut)
async def passkey_step_up(body: PasskeyResponseIn, request: Request, actor: CurrentActor, session: DbSession):
    return await passkeys.authenticate(session, body.challengeId, body.credential, _ua(request), actor)


from zoikorum.domains.identity import enterprise

class EnterpriseCallbackIn(BaseModel):
    state: uuid.UUID
    browserToken: str = Field(min_length=32, max_length=200)
    code: str = Field(min_length=1, max_length=8192)

@router.post("/auth/enterprise/start")
async def enterprise_start(session: DbSession):
    return await enterprise.begin(session)

@router.post("/auth/enterprise/complete", response_model=AuthOut)
async def enterprise_complete(body: EnterpriseCallbackIn, request: Request, session: DbSession):
    return await enterprise.complete(session, body.state, body.browserToken, body.code, _ua(request))

@router.post("/scim/v2/Users", status_code=201)
async def scim_create(body: enterprise.ScimUserIn, request: Request, session: DbSession):
    org = await enterprise.authorize_scim(session, request.headers.get("Authorization"))
    return await enterprise.provision(session, org, body)

@router.get("/scim/v2/Users/{account_id}")
async def scim_get(account_id: uuid.UUID, request: Request, session: DbSession):
    org = await enterprise.authorize_scim(session, request.headers.get("Authorization"))
    return await enterprise.scim_out(session, await enterprise.get_scim_account(session, org, account_id))

@router.get("/scim/v2/Users")
async def scim_list(request: Request, session: DbSession, filter: str | None = None, startIndex: int = 1, count: int = 100):
    import re
    from sqlalchemy import select
    from zoikorum.domains.identity.models import FederationAccount, Identity
    from zoikorum.shared.errors import ValidationFailed
    org = await enterprise.authorize_scim(session, request.headers.get("Authorization"))
    statement = select(FederationAccount).join(Identity).where(FederationAccount.organization_id == org.id)
    if filter:
        match = re.fullmatch(r'userName eq "([^"\\]+)"', filter)
        if not match:
            raise ValidationFailed("Only userName equality filtering is supported")
        statement = statement.where(Identity.email == match[1].lower())
    rows = list((await session.scalars(statement.order_by(FederationAccount.id))).all())
    if startIndex < 1 or count < 0 or count > 200:
        raise ValidationFailed("Invalid provisioning pagination")
    selected = rows[startIndex-1:startIndex-1+count]
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "totalResults": len(rows),
        "startIndex": startIndex, "itemsPerPage": len(selected),
        "Resources": [await enterprise.scim_out(session, r) for r in selected]}

@router.put("/scim/v2/Users/{account_id}")
async def scim_replace(account_id: uuid.UUID, body: enterprise.ScimUserIn, request: Request, session: DbSession):
    org = await enterprise.authorize_scim(session, request.headers.get("Authorization"))
    account = await enterprise.get_scim_account(session, org, account_id)
    current = await enterprise.scim_out(session, account)
    from zoikorum.shared.errors import ValidationFailed
    if str(body.externalId) != account.subject or str(body.userName).lower() != current["userName"]:
        raise ValidationFailed("Changing the federation subject or email requires verified account linking")
    return await enterprise.change_active(session, org, account_id, body.active, body.displayName)

@router.patch("/scim/v2/Users/{account_id}")
async def scim_patch(account_id: uuid.UUID, body: dict, request: Request, session: DbSession):
    org = await enterprise.authorize_scim(session, request.headers.get("Authorization"))
    from zoikorum.shared.errors import ValidationFailed
    current = await enterprise.scim_out(session, await enterprise.get_scim_account(session, org, account_id))
    active, display_name = current["active"], current["displayName"]
    operations = body.get("Operations")
    if not isinstance(operations, list) or not operations:
        raise ValidationFailed("Provisioning operations are required")
    for operation in operations:
        if not isinstance(operation, dict) or str(operation.get("op", "")).lower() not in ("replace", "add"):
            raise ValidationFailed("Unsupported provisioning operation")
        path, value = operation.get("path"), operation.get("value")
        updates = value if path is None and isinstance(value, dict) else {path: value}
        for attribute, value in updates.items():
            if attribute == "active" and isinstance(value, bool):
                active = value
            elif attribute == "displayName" and isinstance(value, str) and 1 <= len(value) <= 200:
                display_name = value
            else:
                raise ValidationFailed("Only active and displayName may be patched")
    return await enterprise.change_active(session, org, account_id, active, display_name)

@router.delete("/scim/v2/Users/{account_id}", status_code=204)
async def scim_delete(account_id: uuid.UUID, request: Request, session: DbSession):
    org = await enterprise.authorize_scim(session, request.headers.get("Authorization"))
    await enterprise.change_active(session, org, account_id, False)


from fastapi.responses import RedirectResponse
from zoikorum.domains.identity import saml

class SamlHandoffIn(BaseModel):
    state: uuid.UUID
    browserToken: str = Field(min_length=32, max_length=200)
    handoff: str = Field(min_length=32, max_length=200)

@router.post("/auth/saml/start")
async def saml_start(session: DbSession):
    return await saml.begin(session)

@router.post("/auth/saml/acs")
async def saml_acs(request: Request, session: DbSession):
    from urllib.parse import parse_qs
    from zoikorum.shared.errors import ValidationFailed
    raw = await request.body()
    if len(raw) > 1024 * 1024 or request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise ValidationFailed("A bounded SAML form response is required")
    try:
        fields = parse_qs(raw.decode('utf-8'), max_num_fields=5)
        response, state = fields['SAMLResponse'], fields['RelayState']
        if len(response) != 1 or len(state) != 1:
            raise ValueError()
        state = uuid.UUID(state[0])
    except (ValueError, KeyError, UnicodeError) as error:
        raise ValidationFailed("Invalid SAML response form") from error
    redirect = await saml.receive(session, response[0], state)
    return RedirectResponse(redirect, status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

@router.post("/auth/saml/complete", response_model=AuthOut)
async def saml_complete(body: SamlHandoffIn, request: Request, session: DbSession):
    return await saml.complete(session, body.state, body.browserToken, body.handoff, _ua(request))


@router.get("/auth/saml/metadata")
async def saml_metadata():
    from fastapi.responses import Response
    auth = saml.toolkit()
    return Response(auth.get_settings().get_sp_metadata(), media_type="application/samlmetadata+xml")

@router.get("/scim/v2/ServiceProviderConfig")
async def scim_configuration(request: Request, session: DbSession):
    await enterprise.authorize_scim(session, request.headers.get("Authorization"))
    return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True}, "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200}, "changePassword": {"supported": False},
        "sort": {"supported": False}, "etag": {"supported": False},
        "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token", "description": "Organisation-scoped provisioning token", "primary": True}]}


from zoikorum.domains.identity import privacy_access as privacy

class PrivacyReviewIn(BaseModel):
    note: str = Field(min_length=20, max_length=2000)

@router.get('/admin/privacy-requests')
async def privacy_queue(actor: CurrentActor, session: DbSession):
    return await privacy.queue(session, actor)

@router.post('/admin/privacy-requests/{request_id}/access')
async def privacy_access(request_id: uuid.UUID, body: PrivacyReviewIn, actor: CurrentActor, session: DbSession):
    return await privacy.fulfil_access(session, actor, request_id, body.note)

@router.get('/me/data-requests/{request_id}/reviewed-copy')
async def privacy_download(request_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    from fastapi.responses import JSONResponse
    return JSONResponse(await privacy.download(session, actor, request_id), headers={'Cache-Control': 'no-store',
        'Content-Disposition': 'attachment; filename="zoikorum-personal-data.json"'})
