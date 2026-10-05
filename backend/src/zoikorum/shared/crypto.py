"""Hashing + field-level encryption helpers.

* ``sha256_hex`` / ``canonical_json`` - evidence hashes and audit hash chain.
* ``encrypt_field`` / ``decrypt_field`` - AES-256-GCM for sensitive attributes
  (MFA secrets, document numbers). In production the data key comes from KMS
  (envelope encryption); locally it is derived from ZK_FIELD_ENCRYPTION_KEY.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zoikorum.config import get_settings


def canonical_json(data: Any) -> bytes:
    """Deterministic JSON (sorted keys, no whitespace) for hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False).encode()


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def hmac_sha256_hex(secret: str, data: bytes) -> str:
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _key() -> bytes:
    s = get_settings()
    material = getattr(s, "field_encryption_key", None) or s.jwt_secret
    return hashlib.sha256(("zk-field-key:" + material).encode()).digest()


def encrypt_field(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), b"zoikorum-field-v1")
    return "v1:" + base64.b64encode(nonce + ct).decode()


def decrypt_field(token: str) -> str:
    if not token.startswith("v1:"):
        raise ValueError("Unknown field encryption version")
    raw = base64.b64decode(token[3:])
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], b"zoikorum-field-v1").decode()
