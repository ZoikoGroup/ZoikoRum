"""Entra authorization-code/PKCE and authenticated SCIM; no email-based account linking."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode
import httpx
import jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from zoikorum.config import get_settings
from zoikorum.domains.identity import service, facade
from zoikorum.domains.identity.models import AuthChallenge, FederationAccount, Identity, Session
from zoikorum.domains.identity.schemas import AuthOut
from zoikorum.domains.buyer import facade as buyer
from zoikorum.shared import clock
from zoikorum.shared.auth import AuthStrength, Persona
from zoikorum.shared.errors import ServiceUnavailable, Unauthenticated, Conflict, Forbidden, NotFound
from zoikorum.shared.event_catalog import E

SCHEMA = 'urn:ietf:params:scim:schemas:core:2.0:User'

def configured(require_oidc=True):
    s = get_settings()
    try:
        tenant, org = uuid.UUID(s.entra_tenant_id or ''), uuid.UUID(s.enterprise_organization_id or '')
        client = uuid.UUID(s.entra_client_id or '') if require_oidc else s.entra_client_id or ''
    except ValueError as error:
        raise ServiceUnavailable('Enterprise sign-in is not configured', code='SSO_NOT_CONFIGURED') from error
    if require_oidc and not s.entra_client_secret:
        raise ServiceUnavailable('Enterprise sign-in is not configured', code='SSO_NOT_CONFIGURED')
    return s, str(tenant), str(client), org

async def organization(session, require_oidc=True):
    s, tenant, client, org_id = configured(require_oidc)
    org = await buyer.get_organization(session, org_id)
    if not org or org.org_type != 'ENTERPRISE' or org.status != 'ACTIVE':
        raise ServiceUnavailable('Enterprise organisation mapping is unavailable', code='SSO_NOT_CONFIGURED')
    return s, tenant, client, org

async def begin(session):
    s, tenant, client, org = await organization(session)
    nonce, verifier, browser_token = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    challenge = AuthChallenge(purpose='OIDC', expires_at=clock.now()+timedelta(minutes=5),
        challenge=json.dumps({'nonce': nonce, 'verifier': verifier, 'browserHash': hashlib.sha256(browser_token.encode()).hexdigest(),
                             'tenant': tenant, 'client': client, 'org': str(org.id)}).encode())
    session.add(challenge)
    await session.flush()
    params = {'client_id': client, 'response_type': 'code', 'scope': 'openid profile',
              'redirect_uri': s.frontend_url.rstrip('/') + '/sso/callback', 'response_mode': 'query',
              'state': str(challenge.id), 'nonce': nonce, 'code_challenge_method': 'S256',
              'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()}
    return {'authorizationUrl': f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?' + urlencode(params),
            'state': str(challenge.id), 'browserToken': browser_token}

async def complete(session, state, browser_token, code, user_agent):
    s, tenant, client, org = await organization(session)
    row = await session.scalar(select(AuthChallenge).where(AuthChallenge.id == state).with_for_update())
    if not row or row.purpose != 'OIDC' or row.used_at or row.expires_at <= clock.now():
        raise Unauthenticated('Enterprise sign-in expired or was already used')
    data = json.loads(row.challenge)
    if not hmac.compare_digest(data['browserHash'], hashlib.sha256(browser_token.encode()).hexdigest()):
        raise Unauthenticated('Enterprise sign-in does not belong to this browser')
    if (data['tenant'], data['client'], data['org']) != (tenant, client, str(org.id)):
        raise Unauthenticated('Enterprise configuration changed; restart sign-in')
    issuer = f'https://login.microsoftonline.com/{tenant}/v2.0'
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.post(f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token', data={
                'client_id': client, 'client_secret': s.entra_client_secret, 'grant_type': 'authorization_code',
                'code': code, 'code_verifier': data['verifier'], 'redirect_uri': s.frontend_url.rstrip('/')+'/sso/callback'})
            response.raise_for_status()
            token = response.json()['id_token']
            header = jwt.get_unverified_header(token)
            keys_response = await http.get(f'https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys')
            keys_response.raise_for_status()
            keys = keys_response.json()['keys']
        matching = [key for key in keys if key.get('kid') == header.get('kid') and key.get('kty') == 'RSA']
        if len(matching) != 1:
            raise ValueError('Unknown signing key')
        key = jwt.PyJWK.from_dict(matching[0], algorithm='RS256').key
        claims = jwt.decode(token, key, algorithms=['RS256'], audience=client, issuer=issuer,
            options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'nonce', 'tid', 'oid']})
        if claims['nonce'] != data['nonce'] or claims['tid'] != tenant:
            raise ValueError('Nonce or tenant mismatch')
        subject = str(uuid.UUID(claims['oid']))
    except (httpx.HTTPError, ValueError, KeyError, jwt.PyJWTError) as error:
        raise Unauthenticated('Enterprise sign-in could not be verified') from error
    account = await session.scalar(select(FederationAccount).where(FederationAccount.organization_id == org.id,
        FederationAccount.subject == subject).with_for_update())
    if not account or not account.active or not await facade.account_is_active(session, account.identity_id):
        raise Forbidden('Your enterprise account has not been provisioned or is inactive')
    roles = await buyer.get_member_roles(session, org.id, account.identity_id)
    if not roles:
        raise Forbidden('Enterprise membership is not active yet')
    row.used_at = clock.now()
    identity = await session.get(Identity, account.identity_id)
    pair = await service._start_session(session, identity, AuthStrength.OAUTH, user_agent)
    service._evt(session, E.AUTHENTICATION_SUCCEEDED, identity, provider='ENTRA', authStrength=AuthStrength.OAUTH)
    return AuthOut(tokens=pair, user=service.to_out(identity, await service._links(session, identity.id)))

async def authorize_scim(session, authorization):
    s, tenant, client, org = await organization(session, require_oidc=False)
    configured_token = s.scim_bearer_token or ''
    supplied = (authorization or '').removeprefix('Bearer ')
    if len(configured_token) < 32 or not authorization or not authorization.startswith('Bearer ') or not hmac.compare_digest(configured_token, supplied):
        raise Unauthenticated('Invalid provisioning credential')
    return org

class ScimUserIn(BaseModel):
    userName: EmailStr
    externalId: uuid.UUID
    displayName: str = Field(min_length=1, max_length=200)
    active: bool = True

async def scim_out(session, account):
    identity = await session.get(Identity, account.identity_id)
    return {'schemas': [SCHEMA], 'id': str(account.id), 'externalId': account.subject,
            'userName': identity.email, 'displayName': identity.display_name,
            'active': account.active, 'meta': {'resourceType': 'User'}}

async def provision(session, org, body):
    account = await session.scalar(select(FederationAccount).where(FederationAccount.organization_id == org.id,
        FederationAccount.subject == str(body.externalId)).with_for_update())
    if account:
        return await scim_out(session, account)
    email = str(body.userName).lower()
    if await session.scalar(select(Identity.id).where(Identity.email == email)):
        raise Conflict('This email belongs to an existing ZoikoID; verified account linking is required', code='ACCOUNT_LINK_REQUIRED')
    identity = Identity(email=email, display_name=body.displayName, country=org.country, status='ACTIVE' if body.active else 'SUSPENDED',
        enterprise_federated=True, personas=[Persona.ENTERPRISE_MEMBER], primary_persona=Persona.ENTERPRISE_MEMBER,
        platform_roles=[], email_confirmed_at=clock.now())
    session.add(identity)
    await session.flush()
    account = FederationAccount(identity_id=identity.id, organization_id=org.id, subject=str(body.externalId), active=body.active)
    session.add(account)
    await session.flush()
    service._evt(session, E.FEDERATION_PROVISIONED, identity, organizationId=org.id, active=body.active)
    return await scim_out(session, account)

async def get_scim_account(session, org, account_id):
    account = await session.scalar(select(FederationAccount).where(FederationAccount.id == account_id,
        FederationAccount.organization_id == org.id).with_for_update())
    if not account:
        raise NotFound('Provisioned account not found')
    return account

async def change_active(session, org, account_id, active, display_name=None):
    account = await get_scim_account(session, org, account_id)
    identity = await session.get(Identity, account.identity_id, with_for_update=True)
    account.active = active
    identity.status = 'ACTIVE' if active else 'SUSPENDED'
    if display_name:
        identity.display_name = display_name
    # Revocation commits with deprovisioning, before membership projections catch up.
    await session.execute(update(Session).where(Session.identity_id == identity.id, Session.revoked_at.is_(None)).values(revoked_at=clock.now()))
    service._evt(session, E.FEDERATION_PROVISIONED, identity, organizationId=org.id, active=active)
    return await scim_out(session, account)
