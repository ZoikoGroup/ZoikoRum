"""SAML 2.0 single sign-on for organisations (service-provider initiated), alongside OpenID Connect (identity/sso.py).

* Set-up: an Organisation Admin uploads the identity provider's metadata (entity id, single sign-on address, signing
  certificates). Zoikorum's own service-provider metadata is at ``GET /v1/auth/saml/metadata``.
* Sign-in: ``POST /v1/auth/sso/start`` with a work email returns the identity provider's address with an AuthnRequest
  (HTTP-Redirect binding). The identity provider posts the signed Response to the assertion consumer service
  ``POST /v1/auth/saml/acs`` (HTTP-POST binding). After every check passes the browser is sent to the web app's
  ``/sso/callback`` with a one-time code, and the web app finishes exactly as for OpenID Connect (same just-in-time
  provisioning and account-safety rules, identity/sso.py ``_org_identity``).
* Checks: the XML signature (Response or Assertion, RSA/ECDSA with SHA-256 or stronger, via signxml) against the
  uploaded certificates, using only the signed element (signature-wrapping attacks); exactly one assertion; issuer;
  audience; recipient and destination; InResponseTo matches the request this server issued (one use); time conditions
  with two minutes of clock skew. Documents with a DOCTYPE, encrypted assertions and unsigned responses are refused.
"""

from __future__ import annotations

import base64
import logging
import zlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from xml.sax.saxutils import escape, quoteattr

from cryptography import x509

from zoikorum.config import get_settings
from zoikorum.shared.errors import Unauthenticated, ValidationFailed

log = logging.getLogger("zoikorum.identity.saml")
SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML = "urn:oasis:names:tc:SAML:2.0:assertion"
MD = "urn:oasis:names:tc:SAML:2.0:metadata"
DS = "http://www.w3.org/2000/09/xmldsig#"
REDIRECT = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
SKEW = timedelta(minutes=2)
MAX_RESPONSE_BYTES = 256 * 1024

EMAIL_ATTRIBUTES = ("email", "mail", "emailaddress", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                    "urn:oid:0.9.2342.19200300.100.1.3", "user.email")
NAME_ATTRIBUTES = ("displayname", "name", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
                   "http://schemas.microsoft.com/identity/claims/displayname", "urn:oid:2.16.840.1.113730.3.1.241", "cn")


def _base() -> str:
    s = get_settings()
    return (s.public_api_url or s.frontend_url).rstrip("/")


def sp_entity_id() -> str:
    return _base() + "/v1/auth/saml/metadata"


def acs_url() -> str:
    return _base() + "/v1/auth/saml/acs"


def sp_metadata() -> str:
    """This service provider's metadata, for the organisation to load into its identity provider."""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<md:EntityDescriptor xmlns:md="{MD}" entityID={quoteattr(sp_entity_id())}>'
            f'<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" '
            f'protocolSupportEnumeration="{SAMLP}">'
            '<md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>'
            f'<md:AssertionConsumerService Binding="{POST}" Location={quoteattr(acs_url())} index="0" isDefault="true"/>'
            '</md:SPSSODescriptor></md:EntityDescriptor>')


# ---- Parsing (no DTDs, no entities, no network) ------------------------------------------------------------------------

def _parser():
    from lxml import etree

    return etree.XMLParser(resolve_entities=False, no_network=True, dtd_validation=False, load_dtd=False, huge_tree=False,
                           remove_comments=True, remove_pis=True)


def _parse(data: bytes):
    from lxml import etree

    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValidationFailed("XML documents with a DOCTYPE are not accepted", code="SAML_INVALID_XML")
    try:
        return etree.fromstring(data, parser=_parser())
    except etree.XMLSyntaxError as exc:
        raise ValidationFailed("The SAML document is not valid XML", code="SAML_INVALID_XML") from exc


def _pem(b64: str) -> str:
    body = "".join(b64.split())
    pem = "-----BEGIN CERTIFICATE-----\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) + "\n-----END CERTIFICATE-----\n"
    try:
        x509.load_pem_x509_certificate(pem.encode())
    except ValueError as exc:
        raise ValidationFailed("A signing certificate in the metadata could not be read", code="SAML_BAD_CERTIFICATE") from exc
    return pem


def normalise_certificate(text: str) -> str:
    """A PEM certificate as pasted, or the bare base64 body from metadata."""
    body = text.replace("-----BEGIN CERTIFICATE-----", "").replace("-----END CERTIFICATE-----", "")
    return _pem(body)


def parse_metadata(xml: str) -> dict:
    """{entityId, ssoUrl, certificates} of the identity provider in uploaded SAML metadata."""
    root = _parse(xml.encode() if isinstance(xml, str) else xml)
    descriptors = [root] if root.tag == f"{{{MD}}}EntityDescriptor" else root.findall(f".//{{{MD}}}EntityDescriptor")
    for entity in descriptors:
        idp = entity.find(f"{{{MD}}}IDPSSODescriptor")
        if idp is None:
            continue
        sso = next((e.get("Location") for e in idp.findall(f"{{{MD}}}SingleSignOnService") if e.get("Binding") == REDIRECT), None)
        if not sso or not sso.startswith("https://"):
            raise ValidationFailed("The identity provider has no https single sign-on address for the HTTP-Redirect binding",
                                   code="SAML_NO_REDIRECT_BINDING")
        certs = []
        for kd in idp.findall(f"{{{MD}}}KeyDescriptor"):
            if kd.get("use") not in (None, "signing"):
                continue
            for c in kd.findall(f".//{{{DS}}}X509Certificate"):
                pem = _pem(c.text or "")
                if pem not in certs:
                    certs.append(pem)
        if not certs:
            raise ValidationFailed("The metadata has no signing certificate", code="SAML_BAD_CERTIFICATE")
        entity_id = entity.get("entityID") or ""
        if not entity_id:
            raise ValidationFailed("The metadata has no entityID", code="SAML_INVALID_XML")
        return {"entityId": entity_id, "ssoUrl": sso, "certificates": certs}
    raise ValidationFailed("The metadata does not describe an identity provider", code="SAML_INVALID_XML")


# ---- AuthnRequest (HTTP-Redirect) -----------------------------------------------------------------------------------------

def _instant(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def authn_request_url(sso_url: str, request_id: str, relay_state: str, now: datetime, email: str | None = None) -> str:
    xml = (f'<samlp:AuthnRequest xmlns:samlp="{SAMLP}" xmlns:saml="{SAML}" ID={quoteattr(request_id)} Version="2.0" '
           f'IssueInstant="{_instant(now)}" Destination={quoteattr(sso_url)} AssertionConsumerServiceURL={quoteattr(acs_url())} '
           f'ProtocolBinding="{POST}"><saml:Issuer>{escape(sp_entity_id())}</saml:Issuer>'
           + (f'<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{escape(email)}'
              '</saml:NameID></saml:Subject>' if email else "")
           + '<samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" AllowCreate="true"/>'
           '</samlp:AuthnRequest>')
    deflater = zlib.compressobj(9, zlib.DEFLATED, -15)
    encoded = base64.b64encode(deflater.compress(xml.encode()) + deflater.flush()).decode()
    return sso_url + ("&" if "?" in sso_url else "?") + urlencode({"SAMLRequest": encoded, "RelayState": relay_state})


# ---- Response validation ------------------------------------------------------------------------------------------------------

def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unauthenticated("The sign-in could not be verified", code="SAML_INVALID") from exc
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _fail(reason: str):
    # One public message for every failure: a probing party learns nothing about which check failed (logged here).
    log.info("saml response refused", extra={"fields": {"reason": reason}})
    return Unauthenticated("The sign-in could not be verified", code="SAML_INVALID")


def _verify_signature(root, certificates: list[str]):
    from signxml import SignatureConfiguration, SignatureMethod, XMLVerifier

    strong = frozenset({SignatureMethod.RSA_SHA256, SignatureMethod.RSA_SHA384, SignatureMethod.RSA_SHA512,
                        SignatureMethod.ECDSA_SHA256, SignatureMethod.ECDSA_SHA384, SignatureMethod.ECDSA_SHA512})
    last = None
    for pem in certificates:
        # The certificate is pinned (uploaded by the Organisation Admin from the provider's metadata), so its own dates
        # are not a trust signal: identity providers commonly keep signing with a self-signed certificate past its end
        # date. Verify inside its validity window; replacing the metadata is how trust is withdrawn.
        cert = x509.load_pem_x509_certificate(pem.encode())
        when = min(max(datetime.now(timezone.utc), cert.not_valid_before_utc + timedelta(seconds=1)),
                   cert.not_valid_after_utc - timedelta(seconds=1))
        config = SignatureConfiguration(signature_methods=strong, expect_references=1, verification_time=when)
        try:
            return XMLVerifier().verify(root, x509_cert=pem, id_attribute="ID", parser=_parser(), expect_config=config).signed_xml
        except Exception as exc:  # noqa: BLE001 - try the next certificate (identity providers rotate them)
            last = exc
    raise _fail("signature") from last


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def verify_response(saml_response: str, *, certificates: list[str], idp_entity_id: str, request_id: str, now: datetime) -> dict:
    """The identity in a posted SAMLResponse, after every check: {subject, email, name, issuer}."""
    if len(saml_response) > MAX_RESPONSE_BYTES * 4 // 3 + 4:
        raise _fail("too large")
    try:
        data = base64.b64decode(saml_response, validate=False)
    except ValueError as exc:
        raise _fail("encoding") from exc
    try:
        root = _parse(data)
    except ValidationFailed as exc:
        raise _fail("xml") from exc
    if root.tag != f"{{{SAMLP}}}Response":
        raise _fail("not a Response")
    status = root.find(f"{{{SAMLP}}}Status/{{{SAMLP}}}StatusCode")
    if status is None or status.get("Value") != SUCCESS:
        raise Unauthenticated("The identity provider did not sign you in", code="SAML_NOT_SUCCESSFUL")
    if root.find(f".//{{{SAML}}}EncryptedAssertion") is not None:
        raise _fail("encrypted assertions are not supported; turn assertion encryption off for Zoikorum")
    if len(root.findall(f".//{{{SAML}}}Assertion")) != 1:
        raise _fail("exactly one assertion expected")
    if root.get("Destination") not in (None, acs_url()):
        raise _fail("destination")
    if root.get("InResponseTo") not in (None, request_id):
        raise _fail("in response to")

    signed = _verify_signature(root, certificates)
    if signed.tag == f"{{{SAMLP}}}Response":
        found = signed.findall(f"{{{SAML}}}Assertion")
        if len(found) != 1:
            raise _fail("exactly one assertion expected")
        assertion = found[0]
        response_issuer = signed.find(f"{{{SAML}}}Issuer")
        if response_issuer is not None and _text(response_issuer) != idp_entity_id:
            raise _fail("response issuer")
    elif signed.tag == f"{{{SAML}}}Assertion":
        assertion = signed
    else:
        raise _fail("signed element")

    if _text(assertion.find(f"{{{SAML}}}Issuer")) != idp_entity_id:
        raise _fail("issuer")
    conditions = assertion.find(f"{{{SAML}}}Conditions")
    if conditions is None:
        raise _fail("conditions")
    not_before, not_after = _time(conditions.get("NotBefore")), _time(conditions.get("NotOnOrAfter"))
    if (not_before and now + SKEW < not_before) or (not_after and now - SKEW >= not_after):
        raise _fail("time conditions")
    audiences = [_text(a) for a in conditions.findall(f"{{{SAML}}}AudienceRestriction/{{{SAML}}}Audience")]
    if sp_entity_id() not in audiences:
        raise _fail("audience")

    subject = assertion.find(f"{{{SAML}}}Subject")
    name_id = _text(subject.find(f"{{{SAML}}}NameID")) if subject is not None else ""
    if not name_id:
        raise _fail("subject")
    confirmed = False
    for sc in subject.findall(f"{{{SAML}}}SubjectConfirmation"):
        data_el = sc.find(f"{{{SAML}}}SubjectConfirmationData")
        if sc.get("Method") != BEARER or data_el is None:
            continue
        until = _time(data_el.get("NotOnOrAfter"))
        if data_el.get("Recipient") == acs_url() and data_el.get("InResponseTo") == request_id and until and now - SKEW < until:
            confirmed = True
    if not confirmed:
        raise _fail("subject confirmation")

    attributes: dict[str, str] = {}
    for attr in assertion.findall(f"{{{SAML}}}AttributeStatement/{{{SAML}}}Attribute"):
        values = [_text(v) for v in attr.findall(f"{{{SAML}}}AttributeValue")]
        if values and values[0]:
            for key in (attr.get("Name"), attr.get("FriendlyName")):
                if key:
                    attributes.setdefault(key.lower(), values[0])
    email = next((attributes[k] for k in EMAIL_ATTRIBUTES if k in attributes), name_id if "@" in name_id else "")
    name = next((attributes[k] for k in NAME_ATTRIBUTES if k in attributes), "")
    if not name and ("givenname" in attributes or "surname" in attributes):
        name = f"{attributes.get('givenname', '')} {attributes.get('surname', '')}".strip()
    return {"subject": name_id, "email": email.strip().lower(), "name": name or email.split("@")[0], "issuer": idp_entity_id}
