"""Provisioning and signed OIDC enforce browser, tenant, subject and live revocation."""
import json
import time
import uuid
from urllib.parse import parse_qs, urlparse
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from test_organizations import enterprise_admin
from zoikorum.config import get_settings
from zoikorum.domains.identity import enterprise

async def test_entra_scim_oidc_and_immediate_deprovisioning(client, make_user, drain, monkeypatch):
    admin, org = await enterprise_admin(make_user, drain, client)
    s = get_settings()
    tenant, application, subject = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    for name, value in {'entra_tenant_id': tenant, 'entra_client_id': application, 'entra_client_secret': 'configured-test-secret',
                        'enterprise_organization_id': org['id'], 'scim_bearer_token': 'provisioning-secret-' * 3}.items():
        monkeypatch.setattr(s, name, value)
    scim_h = {'Authorization': 'Bearer ' + s.scim_bearer_token}
    payload = {'userName': 'provisioned@example.com', 'displayName': 'Provisioned User', 'externalId': subject, 'active': True}
    assert (await client.post('/v1/scim/v2/Users', json=payload)).status_code == 401
    duplicate_email = dict(payload, userName=admin.email)
    response = await client.post('/v1/scim/v2/Users', headers=scim_h, json=duplicate_email)
    assert response.status_code == 409 and response.json()['code'] == 'ACCOUNT_LINK_REQUIRED'
    created = await client.post('/v1/scim/v2/Users', headers=scim_h, json=payload)
    assert created.status_code == 201, created.text
    account = created.json()
    repeated = await client.post('/v1/scim/v2/Users', headers=scim_h, json=payload)
    assert repeated.json()['id'] == account['id']
    await drain()
    started = await client.post('/v1/auth/enterprise/start')
    assert started.status_code == 200, started.text
    flow = started.json()
    query = parse_qs(urlparse(flow['authorizationUrl']).query)
    assert query['code_challenge_method'] == ['S256']
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk['kid'] = 'enterprise-regression'
    claims = {'iss': f'https://login.microsoftonline.com/{tenant}/v2.0', 'aud': application,
        'sub': 'pairwise-subject', 'oid': subject, 'tid': tenant, 'nonce': query['nonce'][0],
        'iat': int(time.time()), 'exp': int(time.time())+120}
    signed = jwt.encode(claims, key, algorithm='RS256', headers={'kid': jwk['kid']})
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={'id_token': signed} if request.method == 'POST' else {'keys': [jwk]})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(enterprise.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(transport), **kwargs))
    body = {'state': flow['state'], 'browserToken': 'x' * 40, 'code': 'provider-code'}
    assert (await client.post('/v1/auth/enterprise/complete', json=body)).status_code == 401
    assert calls == []
    body['browserToken'] = flow['browserToken']
    completed = await client.post('/v1/auth/enterprise/complete', json=body)
    assert completed.status_code == 200, completed.text
    assert completed.json()['user']['email'] == payload['userName']
    h = {'Authorization': 'Bearer ' + completed.json()['tokens']['accessToken']}
    mine = (await client.get('/v1/organizations/mine', headers=h)).json()
    assert mine[0]['id'] == org['id'] and mine[0]['myRoles'] == ['REQUESTER']
    assert (await client.post('/v1/auth/enterprise/complete', json=body)).status_code == 401
    deactivated = await client.patch('/v1/scim/v2/Users/' + account['id'], headers=scim_h,
        json={'Operations': [{'op': 'Replace', 'path': 'active', 'value': False}]})
    assert deactivated.status_code == 200 and deactivated.json()['active'] is False
    # No drain: existing access and refresh credentials stop working immediately.
    assert (await client.get('/v1/organizations/mine', headers=h)).status_code in (401, 403)
    assert (await client.post('/v1/auth/refresh', json={'refreshToken': completed.json()['tokens']['refreshToken']})).status_code in (401, 403)
    await drain()
    result = await client.get('/v1/scim/v2/Users', headers=scim_h, params={'filter': 'userName eq "provisioned@example.com"'})
    assert result.status_code == 200 and result.json()['totalResults'] == 1
