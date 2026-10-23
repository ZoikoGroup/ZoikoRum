"""A stand-in SAML identity provider for tests: a real RSA key and self-signed certificate, signed responses (signxml)."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML = "urn:oasis:names:tc:SAML:2.0:assertion"
IDP = "https://idp.saml.test/metadata"
SSO_URL = "https://idp.saml.test/sso"


class FakeIdp:
    def __init__(self, entity_id: str = IDP, *, expired_cert: bool = False):
        self.entity_id = entity_id
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.saml.test")])
        now = datetime.now(timezone.utc)
        start, end = (now - timedelta(days=800), now - timedelta(days=400)) if expired_cert else (now - timedelta(days=1), now + timedelta(days=365))
        self.cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(self.key.public_key())
                     .serial_number(x509.random_serial_number()).not_valid_before(start).not_valid_after(end)
                     .sign(self.key, hashes.SHA256()))
        self.cert_pem = self.cert.public_bytes(serialization.Encoding.PEM).decode()
        self.key_pem = self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()).decode()

    def cert_b64(self) -> str:
        return base64.b64encode(self.cert.public_bytes(serialization.Encoding.DER)).decode()

    def metadata(self) -> str:
        return (f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" xmlns:ds="http://www.w3.org/2000/09/xmldsig#" '
                f'entityID="{self.entity_id}"><md:IDPSSODescriptor protocolSupportEnumeration="{SAMLP}">'
                f'<md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data><ds:X509Certificate>{self.cert_b64()}'
                '</ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor>'
                f'<md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="{SSO_URL}"/>'
                '</md:IDPSSODescriptor></md:EntityDescriptor>')

    def response(self, *, request_id: str, acs: str, audience: str, email: str, name: str = "Sam Saml", subject: str | None = None,
                 now: datetime | None = None, sign: str = "assertion", issuer: str | None = None, valid_minutes: int = 5,
                 key=None) -> str:
        """A base64 SAMLResponse. sign: "assertion", "response" or "none"."""
        from signxml import XMLSigner
        from signxml.algorithms import CanonicalizationMethod

        now = now or datetime.now(timezone.utc)
        fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        aid, rid = "_a" + uuid.uuid4().hex, "_r" + uuid.uuid4().hex
        issuer = issuer or self.entity_id
        assertion = (
            f'<saml:Assertion xmlns:saml="{SAML}" ID="{aid}" Version="2.0" IssueInstant="{fmt(now)}">'
            f'<saml:Issuer>{issuer}</saml:Issuer>' + ('<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="placeholder"/>'
                                                     if sign == "assertion" else "") +
            f'<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{subject or email}</saml:NameID>'
            f'<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"><saml:SubjectConfirmationData '
            f'InResponseTo="{request_id}" NotOnOrAfter="{fmt(now + timedelta(minutes=valid_minutes))}" Recipient="{acs}"/>'
            '</saml:SubjectConfirmation></saml:Subject>'
            f'<saml:Conditions NotBefore="{fmt(now - timedelta(minutes=1))}" NotOnOrAfter="{fmt(now + timedelta(minutes=valid_minutes))}">'
            f'<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction></saml:Conditions>'
            f'<saml:AuthnStatement AuthnInstant="{fmt(now)}"><saml:AuthnContext><saml:AuthnContextClassRef>'
            'urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml:AuthnContextClassRef></saml:AuthnContext>'
            '</saml:AuthnStatement><saml:AttributeStatement>'
            f'<saml:Attribute Name="email"><saml:AttributeValue>{email}</saml:AttributeValue></saml:Attribute>'
            f'<saml:Attribute Name="displayName"><saml:AttributeValue>{name}</saml:AttributeValue></saml:Attribute>'
            '</saml:AttributeStatement></saml:Assertion>')
        signer = XMLSigner(c14n_algorithm=CanonicalizationMethod.EXCLUSIVE_XML_CANONICALIZATION_1_0)
        key_pem = key or self.key_pem
        if sign == "assertion":
            signed = signer.sign(etree.fromstring(assertion), key=key_pem, cert=self.cert_pem, reference_uri=aid, id_attribute="ID")
            assertion = etree.tostring(signed).decode()
        response = (f'<samlp:Response xmlns:samlp="{SAMLP}" xmlns:saml="{SAML}" ID="{rid}" Version="2.0" IssueInstant="{fmt(now)}" '
                    f'Destination="{acs}" InResponseTo="{request_id}"><saml:Issuer>{issuer}</saml:Issuer>'
                    + ('<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="placeholder"/>' if sign == "response" else "")
                    + f'<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>{assertion}'
                    '</samlp:Response>')
        if sign == "response":
            signed = signer.sign(etree.fromstring(response), key=key_pem, cert=self.cert_pem, reference_uri=rid, id_attribute="ID")
            response = etree.tostring(signed).decode()
        return base64.b64encode(response.encode()).decode()
