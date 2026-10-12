"""Signed SAML success, unsigned assertion refusal and browser-bound handoff."""
import base64
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from lxml import etree
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from sqlalchemy import select
from test_organizations import enterprise_admin
from zoikorum.config import get_settings
from zoikorum.domains.identity.models import AuthChallenge
from zoikorum.domains.identity.saml import OBJECT_ID
import json

async def test_saml_requires_signed_assertion_and_browser_bound_single_use_handoff(client, make_user, drain, sf, monkeypatch):
    admin, org = await enterprise_admin(make_user, drain, client)
    tenant, subject = str(uuid.uuid4()), str(uuid.uuid4())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'SAML test')])
    now = datetime.now(timezone.utc)
    cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).sign(key, hashes.SHA256())
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    certificate = cert.public_bytes(serialization.Encoding.PEM).decode()
    s = get_settings()
    for setting, value in {'entra_tenant_id': tenant, 'enterprise_organization_id': org['id'],
        'scim_bearer_token': 'saml-provisioning-secret-'*3, 'saml_sp_entity_id': 'https://zoikorum.example/saml',
        'saml_idp_sso_url': f'https://login.microsoftonline.com/{tenant}/saml2', 'saml_idp_certificate': certificate,
        'saml_sp_certificate': certificate, 'saml_sp_private_key': private, 'public_api_url': 'http://localhost:8000'}.items():
        monkeypatch.setattr(s, setting, value)
    response = await client.post('/v1/scim/v2/Users', headers={'Authorization': 'Bearer '+s.scim_bearer_token},
        json={'userName': 'saml-user@example.com', 'externalId': subject, 'displayName': 'SAML User'})
    assert response.status_code == 201, response.text
    await drain()
    response = await client.post('/v1/auth/saml/start')
    assert response.status_code == 200, response.text
    flow = response.json()
    async with sf() as session:
        row = await session.get(AuthChallenge, uuid.UUID(flow['state']))
        request_id = json.loads(row.challenge)['requestId']
    def date(t):
        return t.strftime('%Y-%m-%dT%H:%M:%SZ')
    destination = s.public_api_url+'/v1/auth/saml/acs'
    issuer = f'https://sts.windows.net/{tenant}/'
    xml = f'''<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_response" Version="2.0" IssueInstant="{date(now)}" Destination="{destination}" InResponseTo="{request_id}">
<saml:Issuer>{issuer}</saml:Issuer><samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
<saml:Assertion ID="_assertion" Version="2.0" IssueInstant="{date(now)}"><saml:Issuer>{issuer}</saml:Issuer>
<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent">{subject}</saml:NameID><saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"><saml:SubjectConfirmationData InResponseTo="{request_id}" NotOnOrAfter="{date(now+timedelta(minutes=3))}" Recipient="{destination}"/></saml:SubjectConfirmation></saml:Subject>
<saml:Conditions NotBefore="{date(now-timedelta(minutes=1))}" NotOnOrAfter="{date(now+timedelta(minutes=3))}"><saml:AudienceRestriction><saml:Audience>{s.saml_sp_entity_id}</saml:Audience></saml:AudienceRestriction></saml:Conditions>
<saml:AuthnStatement AuthnInstant="{date(now)}" SessionIndex="_session"><saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>
<saml:AttributeStatement><saml:Attribute Name="{OBJECT_ID}"><saml:AttributeValue>{subject}</saml:AttributeValue></saml:Attribute></saml:AttributeStatement></saml:Assertion></samlp:Response>'''
    def encoded(xml):
        return base64.b64encode(xml if isinstance(xml, bytes) else xml.encode()).decode()
    bad = await client.post('/v1/auth/saml/acs', data={'SAMLResponse': encoded(xml), 'RelayState': flow['state']})
    assert bad.status_code == 401, bad.text
    root = etree.fromstring(xml.encode())
    assertion = root.find('{urn:oasis:names:tc:SAML:2.0:assertion}Assertion')
    signed_assertion = OneLogin_Saml2_Utils.add_sign(etree.tostring(assertion), private, certificate,
        sign_algorithm='http://www.w3.org/2001/04/xmldsig-more#rsa-sha256', digest_algorithm='http://www.w3.org/2001/04/xmlenc#sha256')
    root.replace(assertion, etree.fromstring(signed_assertion))
    signed = OneLogin_Saml2_Utils.add_sign(etree.tostring(root), private, certificate,
        sign_algorithm='http://www.w3.org/2001/04/xmldsig-more#rsa-sha256', digest_algorithm='http://www.w3.org/2001/04/xmlenc#sha256')
    accepted = await client.post('/v1/auth/saml/acs', data={'SAMLResponse': encoded(signed), 'RelayState': flow['state']}, follow_redirects=False)
    assert accepted.status_code == 303, accepted.text
    handoff = parse_qs(urlparse(accepted.headers['location']).query)['handoff'][0]
    body = {'state': flow['state'], 'handoff': handoff, 'browserToken': 'incorrect-browser-token-'*2}
    assert (await client.post('/v1/auth/saml/complete', json=body)).status_code == 401
    body['browserToken'] = flow['browserToken']
    completed = await client.post('/v1/auth/saml/complete', json=body)
    assert completed.status_code == 200, completed.text
    assert completed.json()['user']['email'] == 'saml-user@example.com'
    assert (await client.post('/v1/auth/saml/complete', json=body)).status_code == 401
