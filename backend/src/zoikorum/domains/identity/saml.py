"""Strict signed SAML with request correlation and browser-bound one-use handoff."""
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlparse, urlencode
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from sqlalchemy import select
from zoikorum.config import get_settings
from zoikorum.domains.identity import enterprise, service, facade
from zoikorum.domains.identity.models import AuthChallenge, FederationAccount, Identity
from zoikorum.domains.identity.schemas import AuthOut
from zoikorum.domains.buyer import facade as buyer
from zoikorum.shared import clock
from zoikorum.shared.auth import AuthStrength
from zoikorum.shared.errors import ServiceUnavailable, Unauthenticated, Forbidden
from zoikorum.shared.event_catalog import E

OBJECT_ID = 'http://schemas.microsoft.com/identity/claims/objectidentifier'

def toolkit(post_data=None):
    s = get_settings()
    try:
        tenant = str(uuid.UUID(s.entra_tenant_id or ''))
    except ValueError as error:
        raise ServiceUnavailable('SAML tenant is not configured', code='SSO_NOT_CONFIGURED') from error
    if not all((s.saml_sp_entity_id, s.saml_idp_sso_url, s.saml_idp_certificate, s.saml_sp_certificate, s.saml_sp_private_key)):
        raise ServiceUnavailable('SAML signing certificates and endpoints are not configured', code='SSO_NOT_CONFIGURED')
    api, idp = urlparse(s.public_api_url), urlparse(s.saml_idp_sso_url)
    if (idp.scheme != 'https' or idp.hostname != 'login.microsoftonline.com' or idp.username
            or (api.scheme != 'https' and s.env == 'production') or not api.hostname or api.username or api.query or api.fragment):
        raise ServiceUnavailable('SAML endpoints are not configured correctly', code='SSO_NOT_CONFIGURED')
    settings = {'strict': True, 'debug': False,
        'sp': {'entityId': s.saml_sp_entity_id, 'assertionConsumerService': {'url': s.public_api_url.rstrip('/') + '/v1/auth/saml/acs',
              'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST'},
              'x509cert': s.saml_sp_certificate, 'privateKey': s.saml_sp_private_key},
        'idp': {'entityId': f'https://sts.windows.net/{tenant}/', 'singleSignOnService': {'url': s.saml_idp_sso_url,
               'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect'}, 'x509cert': s.saml_idp_certificate},
        'security': {'authnRequestsSigned': True, 'wantMessagesSigned': True, 'wantAssertionsSigned': True,
                     'rejectUnsolicitedResponsesWithInResponseTo': True, 'wantAttributeStatement': True,
                     'signatureAlgorithm': 'http://www.w3.org/2001/04/xmldsig-more#rsa-sha256',
                     'digestAlgorithm': 'http://www.w3.org/2001/04/xmlenc#sha256'}}
    request = {'https': 'on' if api.scheme == 'https' else 'off', 'http_host': api.netloc,
               'server_port': str(api.port or (443 if api.scheme == 'https' else 80)),
               'script_name': api.path.rstrip('/') + '/v1/auth/saml/acs', 'get_data': {}, 'post_data': post_data or {}}
    return OneLogin_Saml2_Auth(request, old_settings=settings)

async def begin(session):
    s, tenant, client, org = await enterprise.organization(session, require_oidc=False)
    auth = toolkit()
    browser_token = secrets.token_urlsafe(32)
    row = AuthChallenge(purpose='SAML', expires_at=clock.now()+timedelta(minutes=5), challenge=b'')
    session.add(row)
    await session.flush()
    url = auth.login(return_to=str(row.id), force_authn=True)
    row.challenge = json.dumps({'requestId': auth.get_last_request_id(), 'browserHash': hashlib.sha256(browser_token.encode()).hexdigest(),
        'organizationId': str(org.id), 'tenant': tenant}).encode()
    return {'authorizationUrl': url, 'state': str(row.id), 'browserToken': browser_token}

async def receive(session, response, state):
    s, tenant, client, org = await enterprise.organization(session, require_oidc=False)
    row = await session.scalar(select(AuthChallenge).where(AuthChallenge.id == state).with_for_update())
    if not row or row.purpose != 'SAML' or row.used_at or row.expires_at <= clock.now():
        raise Unauthenticated('SAML request expired or was already used')
    data = json.loads(row.challenge)
    if data['tenant'] != tenant or data['organizationId'] != str(org.id):
        raise Unauthenticated('Enterprise mapping changed')
    try:
        auth = toolkit({'SAMLResponse': response, 'RelayState': str(state)})
        auth.process_response(request_id=data['requestId'])
        if auth.get_errors() or not auth.is_authenticated():
            raise ValueError('Invalid SAML response')
        object_ids = auth.get_attributes().get(OBJECT_ID, [])
        if len(object_ids) != 1:
            raise ValueError('Missing subject binding')
        subject = str(uuid.UUID(object_ids[0]))
    except ServiceUnavailable:
        raise
    except Exception as error:
        raise Unauthenticated('SAML signature, audience or request could not be verified') from error
    account = await session.scalar(select(FederationAccount).where(FederationAccount.organization_id == org.id,
        FederationAccount.subject == subject).with_for_update())
    if not account or not account.active or not await facade.account_is_active(session, account.identity_id):
        raise Forbidden('Your enterprise account is not active')
    handoff = secrets.token_urlsafe(32)
    row.purpose = 'SAML_HANDOFF'
    row.expires_at = clock.now()+timedelta(minutes=1)
    row.challenge = json.dumps({**data, 'identityId': str(account.identity_id),
        'handoffHash': hashlib.sha256(handoff.encode()).hexdigest()}).encode()
    return s.frontend_url.rstrip('/') + '/sso/saml-callback?' + urlencode({'state': str(row.id), 'handoff': handoff})

async def complete(session, state, browser_token, handoff, user_agent):
    s, tenant, client, org = await enterprise.organization(session, require_oidc=False)
    row = await session.scalar(select(AuthChallenge).where(AuthChallenge.id == state).with_for_update())
    if not row or row.purpose != 'SAML_HANDOFF' or row.used_at or row.expires_at <= clock.now():
        raise Unauthenticated('SAML handoff expired or was already used')
    data = json.loads(row.challenge)
    if (data['tenant'] != tenant or data['organizationId'] != str(org.id)
            or not hmac.compare_digest(data['browserHash'], hashlib.sha256(browser_token.encode()).hexdigest())
            or not hmac.compare_digest(data['handoffHash'], hashlib.sha256(handoff.encode()).hexdigest())):
        raise Unauthenticated('SAML handoff does not belong to this browser')
    identity_id = uuid.UUID(data['identityId'])
    if not await facade.account_is_active(session, identity_id) or not await buyer.get_member_roles(session, org.id, identity_id):
        raise Forbidden('Enterprise account or membership is not active')
    row.used_at = clock.now()
    identity = await session.get(Identity, identity_id)
    pair = await service._start_session(session, identity, AuthStrength.OAUTH, user_agent)
    service._evt(session, E.AUTHENTICATION_SUCCEEDED, identity, provider='SAML', authStrength=AuthStrength.OAUTH)
    return AuthOut(tokens=pair, user=service.to_out(identity, await service._links(session, identity.id)))
