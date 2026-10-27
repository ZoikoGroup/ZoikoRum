"""Token signing (shared/signing_keys.py): HS256 by default, RS256 with key rotation and a JWKS, the HS256 transition
window, and KMS-backed signing."""

from __future__ import annotations

import base64
import json

import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from zoikorum.shared import signing_keys


def _pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


@pytest.fixture
def settings(monkeypatch):
    from zoikorum.config import get_settings

    s = get_settings()
    for name, value in {"jwt_signing": "hs256", "jwt_private_keys": {}, "jwt_public_keys": {}, "jwt_active_kid": None,
                        "jwt_kms_key_name": None, "jwt_accept_hs256": True}.items():
        monkeypatch.setattr(s, name, value)
    signing_keys._rings.clear()
    yield s
    signing_keys._rings.clear()


CLAIMS = {"iss": "zoikorum", "sub": "00000000-0000-0000-0000-000000000001", "typ": "access", "iat": 1, "exp": 4_000_000_000}


@pytest.mark.unit
def test_hs256_default_publishes_no_keys(settings):
    token = signing_keys.sign(CLAIMS)
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    assert signing_keys.decode(token, issuer="zoikorum")["sub"] == CLAIMS["sub"]
    assert signing_keys.jwks() == {"keys": []}


@pytest.mark.unit
def test_rs256_rotation_jwks_and_transition_window(settings, monkeypatch):
    hs_token = signing_keys.sign(CLAIMS)
    _, old_pem = _pem()
    monkeypatch.setattr(settings, "jwt_signing", "rs256")
    monkeypatch.setattr(settings, "jwt_private_keys", {"k1": old_pem})
    monkeypatch.setattr(settings, "jwt_active_kid", "k1")
    old_token = signing_keys.sign(CLAIMS)
    assert jwt.get_unverified_header(old_token) == {"alg": "RS256", "kid": "k1", "typ": "JWT"}
    assert [k["kid"] for k in signing_keys.jwks()["keys"]] == ["k1"]
    assert "d" not in signing_keys.jwks()["keys"][0]  # never the private part
    assert signing_keys.decode(hs_token, issuer="zoikorum")  # transition: old HS256 tokens still accepted

    # Rotate: k2 signs, k1 is retired to the public list and still verifies tokens it signed.
    new_key, new_pem = _pem()
    old_public = serialization.load_pem_private_key(old_pem.encode(), None).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setattr(settings, "jwt_private_keys", {"k2": new_pem})
    monkeypatch.setattr(settings, "jwt_public_keys", {"k1": old_public})
    monkeypatch.setattr(settings, "jwt_active_kid", "k2")
    new_token = signing_keys.sign(CLAIMS)
    assert jwt.get_unverified_header(new_token)["kid"] == "k2"
    assert signing_keys.decode(old_token, issuer="zoikorum") and signing_keys.decode(new_token, issuer="zoikorum")
    assert sorted(k["kid"] for k in signing_keys.jwks()["keys"]) == ["k1", "k2"]
    # Third parties can verify with the JWKS alone.
    jwk = next(k for k in signing_keys.jwks()["keys"] if k["kid"] == "k2")
    assert jwt.decode(new_token, jwt.PyJWK(jwk).key, algorithms=["RS256"], issuer="zoikorum")["sub"] == CLAIMS["sub"]

    # End of the transition: HS256 refused; an unknown kid or a forged algorithm is refused too.
    monkeypatch.setattr(settings, "jwt_accept_hs256", False)
    with pytest.raises(jwt.InvalidTokenError):
        signing_keys.decode(hs_token, issuer="zoikorum")
    other, _ = _pem()
    with pytest.raises(jwt.InvalidTokenError):
        signing_keys.decode(jwt.encode(CLAIMS, other, algorithm="RS256", headers={"kid": "k9"}), issuer="zoikorum")
    with pytest.raises(jwt.InvalidTokenError):
        signing_keys.decode(jwt.encode(CLAIMS, None, algorithm="none"), issuer="zoikorum")


@pytest.mark.unit
def test_kms_signing(settings, monkeypatch):
    key, _ = _pem()
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    calls = []

    class FakeKms:
        def get_public_key(self, request):
            return type("R", (), {"pem": pem})()

        def asymmetric_sign(self, request):
            calls.append(request["name"])
            sig = key.sign(request["digest"]["sha256"], padding.PKCS1v15(), _Prehashed())
            return type("R", (), {"signature": sig})()

    from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

    def _Prehashed():
        return Prehashed(hashes.SHA256())

    monkeypatch.setattr(signing_keys, "_kms_client", lambda: FakeKms())
    signing_keys._kms_public_key.cache_clear()
    name = "projects/p/locations/l/keyRings/r/cryptoKeys/jwt/cryptoKeyVersions/1"
    monkeypatch.setattr(settings, "jwt_signing", "rs256")
    monkeypatch.setattr(settings, "jwt_kms_key_name", name)
    token = signing_keys.sign(CLAIMS)
    assert calls == [name] and jwt.get_unverified_header(token)["kid"].startswith("kms-")
    assert signing_keys.decode(token, issuer="zoikorum")["sub"] == CLAIMS["sub"]
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert payload == CLAIMS


async def test_access_tokens_follow_the_signing_mode(client, make_user, settings, monkeypatch):
    _, pem = _pem()
    monkeypatch.setattr(settings, "jwt_signing", "rs256")
    monkeypatch.setattr(settings, "jwt_private_keys", {"main": pem})
    monkeypatch.setattr(settings, "jwt_active_kid", "main")
    user = await make_user("rs-user")
    assert jwt.get_unverified_header(user.access)["kid"] == "main"
    assert (await client.get("/v1/me", headers=user.h)).status_code == 200
    keys = (await client.get("/.well-known/jwks.json")).json()["keys"]
    assert [k["kid"] for k in keys] == ["main"]


@pytest.mark.unit
def test_rs256_outside_development_needs_a_key():
    from prodsettings import PRODUCTION
    from pydantic import ValidationError

    from zoikorum.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **PRODUCTION, jwt_signing="rs256")
    assert Settings(_env_file=None, **PRODUCTION, jwt_signing="rs256", jwt_kms_key_name="projects/p/x").jwt_signing == "rs256"
