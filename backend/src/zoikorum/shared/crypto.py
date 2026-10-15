"""Hashing + field-level encryption helpers.

* ``sha256_hex`` / ``canonical_json`` - evidence hashes and audit hash chain.
* ``encrypt_field`` / ``decrypt_field`` - AES-256-GCM for sensitive attributes (authenticator secrets, phone numbers,
  webhook secrets).

Keys (envelope encryption, Handbook: KMS-managed keys with rotation):

* Production: data keys are random 256-bit keys stored only **wrapped** by a Cloud KMS key (ZK_FIELD_KMS_KEY_NAME,
  ZK_FIELD_DATA_KEYS). The server asks KMS to unwrap a key the first time it needs it and keeps it in memory. A copy
  of the database and the settings is useless without access to the KMS key.
* Local development and tests: one key derived from ZK_FIELD_ENCRYPTION_KEY (key id ``local``).

Values look like ``v2:<key id>:<base64 nonce+ciphertext>``; the key id is bound into the ciphertext. Rotation: add a new
key id, make it ZK_FIELD_ACTIVE_KEY, then run ``python -m zoikorum.cli rotate-field-keys`` to re-encrypt stored values;
old ids stay listed until nothing uses them. ``v1:`` values (earlier versions) still decrypt with the local key.
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

LOCAL = "local"
_unwrapped: dict[tuple[str, str], bytes] = {}  # (kms key name, key id) -> data key


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


def _aad(key_id: str) -> bytes:
    return b"zoikorum-field-dek:" + key_id.encode()


def kms_unwrap(kms_key_name: str, wrapped: bytes, key_id: str) -> bytes:
    """Cloud KMS decrypt of a wrapped data key (google-cloud-kms; the server's service account needs
    roles/cloudkms.cryptoKeyDecrypter on that key only)."""
    from google.cloud import kms

    response = kms.KeyManagementServiceClient().decrypt(
        request={"name": kms_key_name, "ciphertext": wrapped, "additional_authenticated_data": _aad(key_id)})
    return response.plaintext


def kms_wrap(kms_key_name: str, data_key: bytes, key_id: str) -> bytes:
    from google.cloud import kms

    response = kms.KeyManagementServiceClient().encrypt(
        request={"name": kms_key_name, "plaintext": data_key, "additional_authenticated_data": _aad(key_id)})
    return response.ciphertext


def _local_key() -> bytes:
    return hashlib.sha256(("zk-field-key:" + get_settings().field_encryption_key).encode()).digest()


def _data_key(key_id: str) -> bytes:
    if key_id == LOCAL:
        return _local_key()
    s = get_settings()
    wrapped = s.field_data_keys.get(key_id)
    if not wrapped or not s.field_kms_key_name:
        raise ValueError(f"Field encryption key {key_id!r} is not configured (ZK_FIELD_DATA_KEYS, ZK_FIELD_KMS_KEY_NAME)")
    cache_key = (s.field_kms_key_name, key_id)
    if cache_key not in _unwrapped:
        key = kms_unwrap(s.field_kms_key_name, base64.b64decode(wrapped), key_id)
        if len(key) != 32:
            raise ValueError(f"Field encryption key {key_id!r} is not a 256-bit key")
        _unwrapped[cache_key] = key
    return _unwrapped[cache_key]


def active_key_id() -> str:
    s = get_settings()
    return s.field_active_key if s.field_active_key and s.field_kms_key_name else LOCAL


def key_id_of(token: str) -> str:
    return token.split(":", 2)[1] if token.startswith("v2:") else LOCAL


def encrypt_field(plaintext: str) -> str:
    key_id = active_key_id()
    nonce = os.urandom(12)
    ct = AESGCM(_data_key(key_id)).encrypt(nonce, plaintext.encode(), b"zoikorum-field-v2:" + key_id.encode())
    return f"v2:{key_id}:" + base64.b64encode(nonce + ct).decode()


def decrypt_field(token: str) -> str:
    if token.startswith("v1:"):  # earlier versions: the local key, no key id
        raw = base64.b64decode(token[3:])
        return AESGCM(_local_key()).decrypt(raw[:12], raw[12:], b"zoikorum-field-v1").decode()
    if not token.startswith("v2:"):
        raise ValueError("Unknown field encryption version")
    _, key_id, body = token.split(":", 2)
    raw = base64.b64decode(body)
    return AESGCM(_data_key(key_id)).decrypt(raw[:12], raw[12:], b"zoikorum-field-v2:" + key_id.encode()).decode()


def new_wrapped_key(key_id: str) -> str:
    """A fresh random data key, wrapped by the configured KMS key. Returns only the wrapped form (safe to store)."""
    s = get_settings()
    if not s.field_kms_key_name:
        raise ValueError("Set ZK_FIELD_KMS_KEY_NAME first")
    return base64.b64encode(kms_wrap(s.field_kms_key_name, os.urandom(32), key_id)).decode()


# Every stored encrypted column, for re-encryption after a key rotation: (schema.table, column).
ENCRYPTED_COLUMNS = (
    ("identity.identities", "mfa_secret_enc"),
    ("identity.identities", "phone_enc"),
    ("notification.webhook_endpoints", "secret_encrypted"),
)
