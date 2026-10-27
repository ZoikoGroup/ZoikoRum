"""Sign-in token signing keys (Architecture 11.3): HS256 with the shared secret, or RS256 with key rotation.

* ``ZK_JWT_SIGNING=hs256`` (default): tokens are signed with ``ZK_JWT_SECRET`` as before.
* ``ZK_JWT_SIGNING=rs256``: new tokens are signed with an RSA key and carry its ``kid``. The key is either a Cloud KMS
  asymmetric signing key version (``ZK_JWT_KMS_KEY_NAME``: the private key never leaves KMS) or one of
  ``ZK_JWT_PRIVATE_KEYS`` chosen by ``ZK_JWT_ACTIVE_KID``. Every public key (active, other private keys, retired
  ``ZK_JWT_PUBLIC_KEYS``, the KMS key) is published as a JWKS at ``/.well-known/jwks.json`` and accepted on verification.
* Transition window: with ``ZK_JWT_ACCEPT_HS256`` (default true) tokens signed with the shared secret are still accepted,
  so switching to rs256 signs nobody out. Turn it off once the longest-lived HS256 token has expired.

Verification never trusts the token's own ``alg`` beyond these two families, and an RS256 token must name a known kid.
Nothing here logs or returns private key material.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from zoikorum.config import get_settings

log = logging.getLogger("zoikorum.signing_keys")


@dataclass(frozen=True)
class _Ring:
    mode: str
    active_kid: str | None
    private: object | None  # RSAPrivateKey (local keys) or None (KMS / hs256)
    public: dict  # kid -> RSAPublicKey
    kms_key: str | None


def _kid_for(public_key) -> str:
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.urlsafe_b64encode(hashlib.sha256(der).digest()[:12]).decode().rstrip("=")


def _load_private(pem: str):
    return serialization.load_pem_private_key(pem.replace("\\n", "\n").encode(), password=None)


def _load_public(pem: str):
    text = pem.replace("\\n", "\n")
    if "PRIVATE KEY" in text:
        return _load_private(text).public_key()
    return serialization.load_pem_public_key(text.encode())


_ephemeral_lock = threading.Lock()
_ephemeral: dict[str, object] = {}


def _development_key():
    """rs256 in development/tests without configured keys: one temporary key per process (never on servers)."""
    with _ephemeral_lock:
        if "key" not in _ephemeral:
            _ephemeral["key"] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            log.warning("rs256 signing without configured keys: using a temporary key for this process")
        return _ephemeral["key"]


def _kms_client():  # replaced in tests
    from google.cloud import kms

    return kms.KeyManagementServiceClient()


@lru_cache(maxsize=4)
def _kms_public_key(name: str):
    pem = _kms_client().get_public_key(request={"name": name}).pem
    return serialization.load_pem_public_key(pem.encode())


def _kms_kid(name: str) -> str:
    return "kms-" + hashlib.sha256(name.encode()).hexdigest()[:16]


_rings: dict[str, _Ring] = {}


def ring() -> _Ring:
    """The key ring for the current settings (parsed once per distinct configuration)."""
    s = get_settings()
    marker = json.dumps([s.jwt_signing, s.jwt_active_kid, s.jwt_kms_key_name, sorted((s.jwt_private_keys or {}).items()),
                         sorted((s.jwt_public_keys or {}).items())])
    cache_key = hashlib.sha256(marker.encode()).hexdigest()
    if cache_key not in _rings:
        _rings.clear()
        _rings[cache_key] = _build(s)
    return _rings[cache_key]


def _build(s) -> _Ring:
    public: dict = {}
    for kid, pem in (s.jwt_public_keys or {}).items():
        public[kid] = _load_public(pem)
    private = None
    for kid, pem in (s.jwt_private_keys or {}).items():
        key = _load_private(pem)
        public[kid] = key.public_key()
        if kid == s.jwt_active_kid:
            private = key
    active = s.jwt_active_kid
    kms_key = s.jwt_kms_key_name or None
    if kms_key:
        active = _kms_kid(kms_key)
        try:
            public[active] = _kms_public_key(kms_key)
        except Exception:  # noqa: BLE001 - KMS unreachable: verification of other keys still works
            log.warning("the KMS signing key's public half could not be read")
    elif s.jwt_signing == "rs256" and private is None:
        private = _development_key()
        active = _kid_for(private.public_key())
        public[active] = private.public_key()
    return _Ring(s.jwt_signing, active, private, public, kms_key)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _kms_sign(name: str, claims: dict, kid: str) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(claims, separators=(',', ':'), default=str).encode())}"
    digest = hashlib.sha256(signing_input.encode()).digest()
    signature = _kms_client().asymmetric_sign(request={"name": name, "digest": {"sha256": digest}}).signature
    return f"{signing_input}.{_b64(signature)}"


def sign(claims: dict) -> str:
    """A signed JWT for ``claims`` with the configured algorithm and active key."""
    s = get_settings()
    r = ring()
    if r.mode != "rs256":
        return jwt.encode(claims, s.jwt_secret, algorithm="HS256")
    if r.kms_key:
        return _kms_sign(r.kms_key, claims, r.active_kid)
    return jwt.encode(claims, r.private, algorithm="RS256", headers={"kid": r.active_kid})


def verification_key(token: str) -> tuple[object, list[str]]:
    """(key, allowed algorithms) for ``token``, from its header. Raises jwt.InvalidTokenError for an unknown kid or an
    algorithm this installation does not accept."""
    s = get_settings()
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    if alg == "HS256":
        if s.jwt_signing == "hs256" or s.jwt_accept_hs256:
            return s.jwt_secret, ["HS256"]
        raise jwt.InvalidTokenError("HS256 tokens are no longer accepted")
    if alg == "RS256":
        key = ring().public.get(header.get("kid"))
        if key is None:
            raise jwt.InvalidTokenError("unknown signing key")
        return key, ["RS256"]
    raise jwt.InvalidTokenError("unsupported algorithm")


def decode(token: str, **kwargs) -> dict:
    """jwt.decode with the key and algorithm chosen by ``verification_key``."""
    key, algorithms = verification_key(token)
    return jwt.decode(token, key, algorithms=algorithms, **kwargs)


def jwks() -> dict:
    """The public keys tokens may be signed with (RFC 7517). Empty in hs256 mode: a shared secret is never published."""
    r = ring()
    if r.mode != "rs256" and not get_settings().jwt_public_keys and not get_settings().jwt_private_keys:
        return {"keys": []}
    keys = []
    for kid, key in sorted(r.public.items()):
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key))
        keys.append({**jwk, "kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": keys}


def new_key_pem() -> tuple[str, str]:
    """(kid, PEM private key) for ZK_JWT_PRIVATE_KEYS (cli new-jwt-key)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return _kid_for(key.public_key()), pem
