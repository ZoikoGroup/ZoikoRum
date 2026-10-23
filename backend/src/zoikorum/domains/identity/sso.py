"""Single sign-on (Enterprise: SAML/OIDC, SCIM, Google and Microsoft sign-in). OpenID Connect, which Okta, Microsoft
Entra ID and Google Workspace all speak, and SAML 2.0 (identity/saml.py) for identity providers that only speak SAML.

* Organisation SSO: an Organisation Admin registers their identity provider (issuer, client id and secret) and the email
  domains it vouches for. People with those addresses sign in through it; with ``enforce`` the password is refused.
* Account safety: SSO signs in a person who is already a member of that organisation, or creates a new account (just in
  time) when no account has that address. It never takes over an existing account outside the organisation, so
  claiming a domain one does not own cannot capture anyone else's account.
* Google and Microsoft sign-in for individuals (ZK_GOOGLE_CLIENT_ID / ZK_MICROSOFT_CLIENT_ID). Google confirms email
  ownership, so it signs in the account with that address; Microsoft does not, so it signs in only an account it was
  linked to before, or creates a new one.
* The authorization code flow uses PKCE and a one-time state kept on the server. The ID token's signature, issuer,
  audience, expiry and nonce are checked. SSO is not a second factor: signing and payouts still ask for two-step.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import uuid
from datetime import timedelta
from urllib.parse import urlencode

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings, web_url
from zoikorum.domains.identity.models import ExternalLogin, Identity, SsoConnection, SsoLogin
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, AuthStrength, OrgRole, Persona
from zoikorum.shared.crypto import decrypt_field, encrypt_field
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, Unauthenticated, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit

STATE_TTL = timedelta(minutes=10)
SOCIAL = {"google": "https://accounts.google.com", "microsoft": "https://login.microsoftonline.com/common/v2.0"}


# ---- HTTP to the identity provider (replaced in tests) -----------------------------------------------------------------

async def _get_json(url: str) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


async def _post_form(url: str, data: dict) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, data=data, headers={"Accept": "application/json"})
        if r.status_code >= 400:
            raise Unauthenticated("The identity provider refused the sign-in", code="SSO_TOKEN_EXCHANGE_FAILED")
        return r.json()


_discovery: dict[str, tuple[float, dict]] = {}


async def discover(issuer: str) -> dict:
    hit = _discovery.get(issuer)
    if hit and time.monotonic() - hit[0] < 3600:
        return hit[1]
    doc = await _get_json(issuer.rstrip("/") + "/.well-known/openid-configuration")
    _discovery[issuer] = (time.monotonic(), doc)
    return doc


async def _verify_id_token(token: str, doc: dict, client_id: str, nonce: str, issuer_ok) -> dict:
    keys = (await _get_json(doc["jwks_uri"])).get("keys", [])
    kid = jwt.get_unverified_header(token).get("kid")
    key = next((k for k in keys if k.get("kid") == kid), keys[0] if len(keys) == 1 else None)
    if key is None:
        raise Unauthenticated("The identity provider's signing key was not found", code="SSO_INVALID_TOKEN")
    try:
        claims = jwt.decode(token, jwt.PyJWK(key).key, algorithms=["RS256", "ES256"], audience=client_id,
                            options={"require": ["exp", "iat", "sub", "iss"]}, leeway=30)
    except jwt.PyJWTError as exc:
        raise Unauthenticated("The sign-in could not be verified", code="SSO_INVALID_TOKEN") from exc
    if not issuer_ok(claims["iss"], claims) or claims.get("nonce") != nonce:
        raise Unauthenticated("The sign-in could not be verified", code="SSO_INVALID_TOKEN")
    return claims


# ---- Organisation connections (Organisation Admin) ----------------------------------------------------------------------

def _domains(values: list[str]) -> list[str]:
    out = sorted({d.strip().lower().lstrip("@") for d in values if d.strip()})
    if not out or any("." not in d or " " in d for d in out):
        raise ValidationFailed("List the email domains your identity provider signs people in for, e.g. example.com", code="DOMAINS_REQUIRED")
    return out


def connection_out(c: SsoConnection | None) -> dict:
    from zoikorum.domains.identity import saml

    sp = {"samlSpEntityId": saml.sp_entity_id(), "samlAcsUrl": saml.acs_url(), "samlSpMetadataUrl": saml.sp_entity_id()}
    if c is None:
        return {"configured": False, **sp}
    return {"configured": True, "protocol": c.protocol, "issuer": c.issuer, "clientId": c.client_id, "emailDomains": c.email_domains,
            "enforce": c.enforce, "justInTime": c.jit, "defaultRoles": c.default_roles, "enabled": c.enabled,
            "scimEnabled": c.scim_token_hash is not None, "redirectUri": web_url() + "/sso/callback", "scimBaseUrl": "/scim/v2",
            "samlIdpEntityId": c.saml_idp_entity_id, "samlSsoUrl": c.saml_sso_url, "samlCertificates": len(c.saml_certificates or []),
            "groupRoleMap": c.group_role_map or {}, "updatedAt": c.updated_at, **sp}


async def _require_org_admin(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> None:
    from zoikorum.domains.buyer import facade as buyer
    if OrgRole.ORG_ADMIN not in await buyer.get_member_roles(session, org_id, actor.identity_id):
        raise Forbidden("Single sign-on is managed by an Organisation Admin", code="ROLE_REQUIRED")


async def get_connection(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> dict:
    await _require_org_admin(session, actor, org_id)
    return connection_out(await session.scalar(select(SsoConnection).where(SsoConnection.organization_id == org_id)))


async def set_connection(session: AsyncSession, actor: Actor, org_id: uuid.UUID, body) -> dict:
    await _require_org_admin(session, actor, org_id)
    actor.require_step_up()
    domains = _domains(body.emailDomains)
    taken = (await session.scalars(select(SsoConnection).where(SsoConnection.organization_id != org_id,
                                                               SsoConnection.email_domains.overlap(domains)))).all()
    if taken:
        raise Conflict("Another organisation already uses one of these domains for single sign-on", code="DOMAIN_IN_USE")
    protocol = getattr(body, "protocol", None) or "OIDC"
    c = await session.scalar(select(SsoConnection).where(SsoConnection.organization_id == org_id).with_for_update())
    if protocol == "SAML":
        idp = _saml_settings(body, c)
        issuer = idp["entityId"]
        if c is None:
            c = SsoConnection(organization_id=org_id, created_by=actor.identity_id, client_secret_enc=encrypt_field(""))
            session.add(c)
        c.issuer, c.client_id = "", ""
        c.saml_idp_entity_id, c.saml_sso_url, c.saml_certificates = idp["entityId"], idp["ssoUrl"], idp["certificates"]
    else:
        if not body.issuer or not body.clientId:
            raise ValidationFailed("Enter the issuer address and client id from your identity provider", code="ISSUER_REQUIRED")
        issuer = body.issuer.rstrip("/")
        try:
            doc = await discover(issuer)
        except Exception as exc:
            raise ValidationFailed("The issuer's OpenID configuration could not be read; check the issuer address", code="ISSUER_UNREACHABLE") from exc
        if doc.get("issuer", "").rstrip("/") != issuer:
            raise ValidationFailed("The issuer address does not match the provider's own configuration", code="ISSUER_MISMATCH")
        if c is None:
            if not body.clientSecret:
                raise ValidationFailed("Enter the client secret from your identity provider", code="SECRET_REQUIRED")
            c = SsoConnection(organization_id=org_id, created_by=actor.identity_id, client_secret_enc=encrypt_field(body.clientSecret))
            session.add(c)
        elif body.clientSecret:
            c.client_secret_enc = encrypt_field(body.clientSecret)
        c.issuer, c.client_id = issuer, body.clientId.strip()
    c.protocol, c.email_domains, c.enforce, c.jit = protocol, domains, body.enforce, body.justInTime
    c.default_roles, c.enabled = list(body.defaultRoles) or [OrgRole.REQUESTER], body.enabled
    if getattr(body, "groupRoleMap", None) is not None:
        c.group_role_map = {k.strip(): v for k, v in body.groupRoleMap.items() if k.strip()}
    await session.flush()
    record_audit(session, "identity.sso.configured", object_type="SsoConnection", object_id=c.id, tenant_id=org_id,
                 details={"protocol": protocol, "issuer": issuer, "domains": domains, "enforce": c.enforce, "jit": c.jit})
    return connection_out(c)


def _saml_settings(body, c: SsoConnection | None) -> dict:
    """The identity provider's entity id, sign-on address and certificates: from uploaded metadata, from the fields typed
    in, or (on an update that sends neither) the ones already stored."""
    from zoikorum.domains.identity import saml

    if getattr(body, "samlMetadataXml", None):
        return saml.parse_metadata(body.samlMetadataXml)
    if getattr(body, "samlEntityId", None) and getattr(body, "samlSsoUrl", None) and getattr(body, "samlCertificate", None):
        if not body.samlSsoUrl.startswith("https://"):
            raise ValidationFailed("The single sign-on address must start with https://", code="SAML_NO_REDIRECT_BINDING")
        return {"entityId": body.samlEntityId.strip(), "ssoUrl": body.samlSsoUrl.strip(),
                "certificates": [saml.normalise_certificate(body.samlCertificate)]}
    if c is not None and c.protocol == "SAML" and c.saml_idp_entity_id:
        return {"entityId": c.saml_idp_entity_id, "ssoUrl": c.saml_sso_url, "certificates": list(c.saml_certificates)}
    raise ValidationFailed("Upload your identity provider's SAML metadata (or its entity id, sign-on address and certificate)",
                           code="SAML_METADATA_REQUIRED")


async def rotate_scim_token(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> dict:
    await _require_org_admin(session, actor, org_id)
    actor.require_step_up()
    c = await session.scalar(select(SsoConnection).where(SsoConnection.organization_id == org_id).with_for_update())
    if c is None:
        raise Conflict("Set up single sign-on first", code="SSO_NOT_CONFIGURED")
    token = "zkscim_" + secrets.token_urlsafe(32)
    c.scim_token_hash = hashlib.sha256(token.encode()).hexdigest()
    record_audit(session, "identity.scim.token_rotated", object_type="SsoConnection", object_id=c.id, tenant_id=org_id)
    await session.flush()
    return {"token": token, "note": "Copy this token into your identity provider now: it is not shown again."}


async def sso_required(session: AsyncSession, identity: Identity) -> bool:
    """An organisation that enforces SSO refuses its members' passwords (staff accounts are never affected)."""
    if identity.platform_roles:
        return False
    from zoikorum.domains.buyer import facade as buyer
    domain = identity.email.rsplit("@", 1)[-1].lower()
    for c in (await session.scalars(select(SsoConnection).where(SsoConnection.enabled.is_(True), SsoConnection.enforce.is_(True),
                                                                SsoConnection.email_domains.contains([domain])))).all():
        if await buyer.get_member_roles(session, c.organization_id, identity.id):
            return True
    return False


# ---- Sign-in flow ------------------------------------------------------------------------------------------------------------

def providers() -> dict:
    s = get_settings()
    return {"google": bool(s.google_client_id), "microsoft": bool(s.microsoft_client_id)}


def _social_client(provider: str) -> tuple[str, str]:
    s = get_settings()
    cid, secret = (s.google_client_id, s.google_client_secret) if provider == "google" else (s.microsoft_client_id, s.microsoft_client_secret)
    if not cid or not secret:
        raise NotFound(f"{provider.title()} sign-in is not available", code="PROVIDER_NOT_CONFIGURED")
    return cid, secret


async def start(session: AsyncSession, *, email: str | None = None, provider: str | None = None, link_actor: Actor | None = None) -> dict:
    """The address to send the browser to. State, nonce and PKCE verifier stay on the server for STATE_TTL."""
    connection = None
    if provider:
        if provider not in SOCIAL:
            raise NotFound("Unknown provider")
        issuer, (client_id, _) = SOCIAL[provider], _social_client(provider)
    else:
        domain = (email or "").rsplit("@", 1)[-1].lower()
        connection = await session.scalar(select(SsoConnection).where(SsoConnection.enabled.is_(True),
                                                                      SsoConnection.email_domains.contains([domain])))
        if connection is None:
            raise NotFound("Single sign-on is not set up for this email address", code="SSO_NOT_CONFIGURED")
        if connection.protocol == "SAML":
            return await _saml_start(session, connection, email)
        issuer, client_id = connection.issuer, connection.client_id
    doc = await discover(issuer)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    row = SsoLogin(connection_id=connection.id if connection else None, provider=provider or "org", nonce=secrets.token_urlsafe(24),
                   code_verifier=verifier, link_identity_id=link_actor.identity_id if link_actor else None,
                   expires_at=clock.now() + STATE_TTL)
    session.add(row)
    await session.flush()
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": web_url() + "/sso/callback", "scope": "openid email profile",
              "state": str(row.id), "nonce": row.nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    if email:
        params["login_hint"] = email
    return {"url": doc["authorization_endpoint"] + "?" + urlencode(params)}


async def callback(session: AsyncSession, code: str, state: str, user_agent: str | None):
    from zoikorum.domains.identity import service

    try:
        row = await session.get(SsoLogin, uuid.UUID(state), with_for_update=True)
    except ValueError:
        row = None
    if row is None or row.used_at or row.expires_at < clock.now():
        raise Unauthenticated("This sign-in link has expired; start again", code="SSO_STATE_INVALID")
    row.used_at = clock.now()
    connection = await session.get(SsoConnection, row.connection_id) if row.connection_id else None
    if row.provider == "saml":
        return await _saml_finish(session, row, connection, code, user_agent)
    if row.provider == "org":
        if connection is None or not connection.enabled:
            raise Unauthenticated("Single sign-on is no longer set up for this organisation", code="SSO_NOT_CONFIGURED")
        issuer, client_id, secret = connection.issuer, connection.client_id, decrypt_field(connection.client_secret_enc)
        issuer_ok = lambda iss, claims: iss.rstrip("/") == issuer  # noqa: E731
    else:
        issuer = SOCIAL[row.provider]
        client_id, secret = _social_client(row.provider)
        issuer_ok = (lambda iss, claims: iss == "https://accounts.google.com" or iss == "accounts.google.com") if row.provider == "google" \
            else (lambda iss, claims: iss == f"https://login.microsoftonline.com/{claims.get('tid')}/v2.0")
    doc = await discover(issuer)
    tokens = await _post_form(doc["token_endpoint"], {"grant_type": "authorization_code", "code": code, "client_id": client_id,
                                                       "client_secret": secret, "redirect_uri": web_url() + "/sso/callback",
                                                       "code_verifier": row.code_verifier})
    if "id_token" not in tokens:
        raise Unauthenticated("The identity provider did not return an identity", code="SSO_INVALID_TOKEN")
    claims = await _verify_id_token(tokens["id_token"], doc, client_id, row.nonce, issuer_ok)
    email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    name = claims.get("name") or email.split("@")[0]
    subject = f"{claims['iss']}|{claims['sub']}"

    if row.link_identity_id:  # connecting Google or Microsoft to a signed-in account
        await _link(session, row.link_identity_id, row.provider, subject)
        identity = await session.get(Identity, row.link_identity_id)
    elif row.provider == "org":
        identity = await _org_identity(session, connection, email, name, subject)
    else:
        identity = await _social_identity(session, row.provider, email, name, subject, bool(claims.get("email_verified")))
    if identity.status != "ACTIVE":
        raise Forbidden("This account is not active", code="ACCOUNT_NOT_ACTIVE")
    idp = {"org": "OIDC", "google": "GOOGLE", "microsoft": "MICROSOFT"}.get(row.provider, "OIDC")
    pair = await service._start_session(session, identity, AuthStrength.PASSWORD, user_agent, idp=idp)
    record_audit(session, "identity.sso.signed_in", object_type="Identity", object_id=identity.id,
                 details={"provider": row.provider, "issuer": claims["iss"]})
    from zoikorum.domains.identity.schemas import AuthOut
    return AuthOut(tokens=pair, user=service.to_out(identity, await service._links(session, identity.id)))


async def _link(session: AsyncSession, identity_id: uuid.UUID, provider: str, subject: str) -> None:
    existing = await session.scalar(select(ExternalLogin).where(ExternalLogin.subject == subject))
    if existing and existing.identity_id != identity_id:
        raise Conflict("That account is already connected to another Zoikorum account", code="ALREADY_LINKED")
    if not existing:
        session.add(ExternalLogin(identity_id=identity_id, provider=provider, subject=subject))
        await session.flush()


async def _new_identity(session: AsyncSession, email: str, name: str, persona: str) -> Identity:
    from zoikorum.domains.identity import service

    identity = Identity(email=email, password_hash=None, display_name=name[:200], country="US", platform_roles=[], personas=[persona],
                        primary_persona=persona, email_confirmed_at=clock.now())
    session.add(identity)
    await session.flush()
    service._evt(session, E.IDENTITY_CREATED, identity, email=email, country=identity.country, accountType=persona,
                 personas=identity.personas, organizationName=None, viaSso=True)
    return identity


async def _org_identity(session: AsyncSession, c: SsoConnection, email: str, name: str, subject: str) -> Identity:
    from zoikorum.domains.buyer import facade as buyer

    if not email or email.rsplit("@", 1)[-1] not in c.email_domains:
        raise Forbidden("Your identity provider signed you in with an address this organisation does not use", code="SSO_DOMAIN_MISMATCH")
    linked = await session.scalar(select(ExternalLogin).where(ExternalLogin.subject == subject))
    identity = await session.get(Identity, linked.identity_id) if linked else await session.scalar(select(Identity).where(Identity.email == email))
    if identity is None:
        if not c.jit:
            raise Forbidden("Your organisation has not given you access yet; ask an Organisation Admin", code="SSO_NOT_PROVISIONED")
        identity = await _new_identity(session, email, name, Persona.ENTERPRISE_MEMBER)
        await buyer.ensure_member(session, c.organization_id, identity.id, email, identity.display_name, c.default_roles)
    elif not await buyer.get_member_roles(session, c.organization_id, identity.id):
        raise Conflict("An account with this email exists outside your organisation. Sign in with its password, then accept your "
                       "organisation's invitation.", code="SSO_ACCOUNT_EXISTS")
    await _link(session, identity.id, "org", subject)
    return identity


async def _social_identity(session: AsyncSession, provider: str, email: str, name: str, subject: str, verified: bool) -> Identity:
    linked = await session.scalar(select(ExternalLogin).where(ExternalLogin.subject == subject))
    if linked:
        return await session.get(Identity, linked.identity_id)
    if not email:
        raise Unauthenticated("The provider did not share an email address", code="SSO_NO_EMAIL")
    existing = await session.scalar(select(Identity).where(Identity.email == email))
    if existing:
        if provider == "google" and verified and existing.email_confirmed_at:
            await _link(session, existing.id, provider, subject)
            return existing
        raise Conflict("An account with this email already exists. Sign in with its password, then connect "
                       f"{provider.title()} under Security.", code="SSO_ACCOUNT_EXISTS")
    identity = await _new_identity(session, email, name, Persona.BUYER)
    await _link(session, identity.id, provider, subject)
    return identity


# ---- SAML 2.0 (identity/saml.py) ---------------------------------------------------------------------------------------------

async def _saml_start(session: AsyncSession, c: SsoConnection, email: str | None) -> dict:
    from zoikorum.domains.identity import saml

    request_id = "_" + secrets.token_hex(20)  # an XML ID must not start with a digit
    row = SsoLogin(connection_id=c.id, provider="saml", nonce=request_id, code_verifier=secrets.token_urlsafe(48),
                   expires_at=clock.now() + STATE_TTL)
    session.add(row)
    await session.flush()
    return {"url": saml.authn_request_url(c.saml_sso_url, request_id, str(row.id), clock.now(), email)}


def _callback_error(message: str) -> str:
    return web_url() + "/sso/callback?" + urlencode({"error": "access_denied", "error_description": message})


async def saml_acs(session: AsyncSession, saml_response: str | None, relay_state: str | None) -> str:
    """The identity provider's post. Verifies the response and returns where to send the browser: the web app's callback
    with a one-time code (or an error description). Nothing is signed in until the web app redeems the code."""
    from zoikorum.domains.identity import saml

    try:
        row = await session.get(SsoLogin, uuid.UUID(relay_state or ""), with_for_update=True)
    except ValueError:
        row = None
    if row is None or row.provider != "saml" or row.used_at or row.assertion is not None or row.expires_at < clock.now():
        return _callback_error("This sign-in link has expired; start again.")
    c = await session.get(SsoConnection, row.connection_id) if row.connection_id else None
    if c is None or not c.enabled or c.protocol != "SAML":
        return _callback_error("Single sign-on is no longer set up for this organisation.")
    try:
        claims = saml.verify_response(saml_response or "", certificates=list(c.saml_certificates or []),
                                      idp_entity_id=c.saml_idp_entity_id or "", request_id=row.nonce, now=clock.now())
    except (Unauthenticated, ValidationFailed) as exc:
        row.used_at = clock.now()  # a refused response burns the request: start again
        record_audit(session, "identity.sso.saml_refused", object_type="SsoConnection", object_id=c.id, tenant_id=c.organization_id,
                     details={"code": exc.code})
        return _callback_error(exc.detail)
    handoff = secrets.token_urlsafe(32)
    row.assertion, row.code_verifier = claims, hashlib.sha256(handoff.encode()).hexdigest()
    await session.flush()
    return web_url() + "/sso/callback?" + urlencode({"code": handoff, "state": str(row.id)})


async def _saml_finish(session: AsyncSession, row: SsoLogin, c: SsoConnection | None, code: str, user_agent: str | None):
    import hmac

    from zoikorum.domains.identity import service
    from zoikorum.domains.identity.schemas import AuthOut

    if row.assertion is None or not hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(), row.code_verifier):
        raise Unauthenticated("This sign-in link has expired; start again", code="SSO_STATE_INVALID")
    if c is None or not c.enabled or c.protocol != "SAML":
        raise Unauthenticated("Single sign-on is no longer set up for this organisation", code="SSO_NOT_CONFIGURED")
    a = row.assertion
    identity = await _org_identity(session, c, a["email"], a["name"], f"saml:{a['issuer']}|{a['subject']}")
    if identity.status != "ACTIVE":
        raise Forbidden("This account is not active", code="ACCOUNT_NOT_ACTIVE")
    pair = await service._start_session(session, identity, AuthStrength.PASSWORD, user_agent, idp="SAML")
    record_audit(session, "identity.sso.signed_in", object_type="Identity", object_id=identity.id,
                 details={"provider": "saml", "issuer": a["issuer"]})
    return AuthOut(tokens=pair, user=service.to_out(identity, await service._links(session, identity.id)))
