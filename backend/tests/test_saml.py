"""SAML 2.0 single sign-on (identity/saml.py): metadata upload, SP-initiated sign-in through the assertion consumer
service, just-in-time provisioning like OpenID Connect, and every refusal path (signature, audience, request, replay,
time, wrapping, DOCTYPE)."""

from __future__ import annotations

import base64
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from lxml import etree

from samlhelp import SSO_URL, FakeIdp


async def _admin(client, make_user, drain):
    admin = await make_user("saml-admin", account_type="ENTERPRISE", organization="Saml Co")
    await drain()
    await admin.refresh()
    org = (await client.get("/v1/organizations/mine", headers=admin.h)).json()[0]
    await admin.step_up()
    return admin, org


async def _configure(client, admin, org, idp: FakeIdp, domain: str, **extra):
    r = await client.put(f"/v1/organizations/{org['id']}/sso", headers=admin.h,
                         json={"protocol": "SAML", "samlMetadataXml": idp.metadata(), "emailDomains": [domain], **extra})
    assert r.status_code == 200, r.text
    return r.json()


async def _start(client, email):
    r = await client.post("/v1/auth/sso/start", json={"email": email})
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["url"])
    q = parse_qs(url.query)
    request = zlib.decompress(base64.b64decode(q["SAMLRequest"][0]), -15)
    authn = etree.fromstring(request)
    return q["RelayState"][0], authn.get("ID"), authn


async def _post_acs(client, response: str, relay: str):
    return await client.post("/v1/auth/saml/acs", content=f"SAMLResponse={_q(response)}&RelayState={_q(relay)}",
                             headers={"Content-Type": "application/x-www-form-urlencoded"})


def _q(value: str) -> str:
    from urllib.parse import quote
    return quote(value, safe="")


def _redirect(r) -> dict:
    assert r.status_code == 303, r.text
    loc = urlparse(r.headers["location"])
    assert loc.path.endswith("/sso/callback")
    return {k: v[0] for k, v in parse_qs(loc.query).items()}


async def test_saml_sign_in_provisions_member_and_refuses_bad_responses(client, make_user, drain):
    from zoikorum.domains.identity import saml

    idp = FakeIdp()
    domain = f"saml-{uuid.uuid4().hex[:6]}.example.com"
    admin, org = await _admin(client, make_user, drain)
    cfg = await _configure(client, admin, org, idp, domain)
    assert cfg["protocol"] == "SAML" and cfg["samlIdpEntityId"] == idp.entity_id and cfg["samlCertificates"] == 1
    assert cfg["samlAcsUrl"].endswith("/v1/auth/saml/acs")
    meta = await client.get("/v1/auth/saml/metadata")
    assert meta.status_code == 200 and b"AssertionConsumerService" in meta.content

    email = f"sam@{domain}"
    relay, request_id, authn = await _start(client, email)
    assert authn.get("Destination") == SSO_URL and authn.get("AssertionConsumerServiceURL") == saml.acs_url()

    good = idp.response(request_id=request_id, acs=saml.acs_url(), audience=saml.sp_entity_id(), email=email, name="Sam Saml")
    params = _redirect(await _post_acs(client, good, relay))
    assert params["state"] == relay and params["code"]
    # Replaying the same response to the consumer service is refused (the request was used).
    assert _redirect(await _post_acs(client, good, relay))["error"] == "access_denied"
    # A wrong code cannot redeem it; the right one signs in once.
    assert (await client.post("/v1/auth/sso/callback", json={"code": "wrong", "state": relay})).json()["code"] == "SSO_STATE_INVALID"
    relay, request_id, _ = await _start(client, email)
    params = _redirect(await _post_acs(client, idp.response(request_id=request_id, acs=saml.acs_url(), audience=saml.sp_entity_id(),
                                                            email=email, name="Sam Saml"), relay))
    signed = await client.post("/v1/auth/sso/callback", json=params)
    assert signed.status_code == 200, signed.text
    assert signed.json()["user"]["email"] == email
    assert (await client.post("/v1/auth/sso/callback", json=params)).json()["code"] == "SSO_STATE_INVALID"  # one use
    await drain()
    members = (await client.get(f"/v1/organizations/{org['id']}/members", headers=admin.h)).json()
    assert any(m["email"] == email and "REQUESTER" in m["roles"] for m in members)

    # Second sign-in finds the same account by its SAML subject.
    relay, request_id, _ = await _start(client, email)
    params = _redirect(await _post_acs(client, idp.response(request_id=request_id, acs=saml.acs_url(), audience=saml.sp_entity_id(),
                                                            email=email, sign="response"), relay))
    again = await client.post("/v1/auth/sso/callback", json=params)
    assert again.json()["user"]["id"] == signed.json()["user"]["id"]

    async def refused(**kw):
        relay, request_id, _ = await _start(client, email)
        args = {"request_id": request_id, "acs": saml.acs_url(), "audience": saml.sp_entity_id(), "email": email} | kw
        if "request_id_override" in kw:
            args["request_id"] = kw.pop("request_id_override")
            args.pop("request_id_override")
        return _redirect(await _post_acs(client, idp.response(**args), relay))

    assert "error" in await refused(audience="https://someone-else.test")
    assert "error" in await refused(sign="none")
    assert "error" in await refused(issuer="https://evil.test")
    assert "error" in await refused(acs="https://evil.test/acs")
    assert "error" in await refused(now=datetime.now(timezone.utc) - timedelta(hours=1))
    assert "error" in await refused(key=FakeIdp().key_pem)  # signed by another key
    assert "error" in await refused(request_id_override="_not-this-request")


async def test_saml_refuses_tampered_and_wrapped_responses():
    from zoikorum.domains.identity import saml
    from zoikorum.shared.errors import Unauthenticated, ValidationFailed

    idp = FakeIdp()
    md = saml.parse_metadata(idp.metadata())
    now = datetime.now(timezone.utc)
    good = idp.response(request_id="_r1", acs=saml.acs_url(), audience=saml.sp_entity_id(), email="ann@acme.test")
    check = dict(certificates=md["certificates"], idp_entity_id=md["entityId"], request_id="_r1", now=now)
    assert saml.verify_response(good, **check)["email"] == "ann@acme.test"

    # Tampering with the signed email breaks the signature.
    tampered = base64.b64encode(base64.b64decode(good).replace(b"ann@acme.test", b"eve@acme.test")).decode()
    with pytest.raises(Unauthenticated):
        saml.verify_response(tampered, **check)
    # Signature wrapping: a second, unsigned assertion next to the signed one.
    doc = etree.fromstring(base64.b64decode(good))
    extra = etree.fromstring(base64.b64decode(idp.response(request_id="_r1", acs=saml.acs_url(), audience=saml.sp_entity_id(),
                                                           email="eve@acme.test", sign="none")))
    doc.append(extra.find("{urn:oasis:names:tc:SAML:2.0:assertion}Assertion"))
    with pytest.raises(Unauthenticated):
        saml.verify_response(base64.b64encode(etree.tostring(doc)).decode(), **check)
    # A DOCTYPE (entity expansion) is never parsed.
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"/>'
    with pytest.raises(Unauthenticated):
        saml.verify_response(base64.b64encode(bomb).decode(), **check)
    with pytest.raises(ValidationFailed):
        saml.parse_metadata(bomb.decode())
    # An expired but pinned certificate still verifies (identity providers keep signing with them).
    old = FakeIdp(expired_cert=True)
    r = old.response(request_id="_r1", acs=saml.acs_url(), audience=saml.sp_entity_id(), email="ann@acme.test")
    assert saml.verify_response(r, **{**check, "certificates": saml.parse_metadata(old.metadata())["certificates"]})


async def test_saml_set_up_needs_metadata_and_keeps_it_on_update(client, make_user, drain):
    idp = FakeIdp()
    domain = f"saml-{uuid.uuid4().hex[:6]}.example.com"
    admin, org = await _admin(client, make_user, drain)
    r = await client.put(f"/v1/organizations/{org['id']}/sso", headers=admin.h, json={"protocol": "SAML", "emailDomains": [domain]})
    assert r.json()["code"] == "SAML_METADATA_REQUIRED"
    await _configure(client, admin, org, idp, domain)
    kept = await client.put(f"/v1/organizations/{org['id']}/sso", headers=admin.h,
                            json={"protocol": "SAML", "emailDomains": [domain], "enforce": True})
    assert kept.status_code == 200 and kept.json()["samlIdpEntityId"] == idp.entity_id and kept.json()["enforce"] is True
    typed = await client.put(f"/v1/organizations/{org['id']}/sso", headers=admin.h, json={
        "protocol": "SAML", "emailDomains": [domain], "samlEntityId": "https://other.test", "samlSsoUrl": "https://other.test/sso",
        "samlCertificate": idp.cert_pem})
    assert typed.json()["samlIdpEntityId"] == "https://other.test"
