"""Field encryption with KMS-wrapped data keys: values carry their key id, old values keep decrypting, a rotation
re-encrypts stored values onto the new key. A stand-in replaces Cloud KMS (it wraps with its own secret key)."""

from __future__ import annotations

import base64
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text

from zoikorum.config import get_settings
from zoikorum.shared import crypto

KMS_KEY = "projects/p/locations/l/keyRings/r/cryptoKeys/fields"


@pytest.fixture
def fake_kms(monkeypatch):
    master, calls = AESGCM.generate_key(256), {"unwrap": 0}

    def wrap(name, data_key, key_id):
        assert name == KMS_KEY
        nonce = os.urandom(12)
        return nonce + AESGCM(master).encrypt(nonce, data_key, crypto._aad(key_id))

    def unwrap(name, wrapped, key_id):
        calls["unwrap"] += 1
        return AESGCM(master).decrypt(wrapped[:12], wrapped[12:], crypto._aad(key_id))

    monkeypatch.setattr(crypto, "kms_wrap", wrap)
    monkeypatch.setattr(crypto, "kms_unwrap", unwrap)
    monkeypatch.setattr(crypto, "_unwrapped", {})
    s = get_settings()
    monkeypatch.setattr(s, "field_kms_key_name", KMS_KEY)
    monkeypatch.setattr(s, "field_data_keys", {})
    monkeypatch.setattr(s, "field_active_key", None)
    return calls


@pytest.mark.unit
def test_values_carry_their_key_and_old_formats_still_decrypt(fake_kms, monkeypatch):
    s = get_settings()
    local = crypto.encrypt_field("JBSWY3DPEHPK3PXP")
    assert local.startswith("v2:local:") and crypto.decrypt_field(local) == "JBSWY3DPEHPK3PXP"

    legacy_nonce = os.urandom(12)  # a value written by the earlier format
    legacy = "v1:" + base64.b64encode(legacy_nonce + AESGCM(crypto._local_key()).encrypt(
        legacy_nonce, b"+44 20 7946 0000", b"zoikorum-field-v1")).decode()
    assert crypto.decrypt_field(legacy) == "+44 20 7946 0000"

    s.field_data_keys = {"2026-10": crypto.new_wrapped_key("2026-10")}
    s.field_active_key = "2026-10"
    wrapped = crypto.encrypt_field("webhook-secret")
    assert wrapped.startswith("v2:2026-10:") and "webhook-secret" not in wrapped
    assert crypto.decrypt_field(wrapped) == "webhook-secret" and crypto.decrypt_field(local) == "JBSWY3DPEHPK3PXP"
    crypto.decrypt_field(crypto.encrypt_field("again"))
    assert fake_kms["unwrap"] == 1  # unwrapped once, then kept in memory

    tampered = wrapped.replace("v2:2026-10:", "v2:local:")  # the key id is bound into the ciphertext
    with pytest.raises(Exception):
        crypto.decrypt_field(tampered)
    s.field_data_keys = {}
    crypto._unwrapped.clear()
    with pytest.raises(ValueError, match="not configured"):
        crypto.decrypt_field(wrapped)


async def test_rotation_re_encrypts_stored_secrets_and_sign_in_still_works(client, make_user, fake_kms, sf):
    from zoikorum.cli import _rotate_field_keys

    u = await make_user("rosa")
    await u.enable_mfa()
    async with sf() as s:
        before = await s.scalar(text("SELECT mfa_secret_enc FROM identity.identities WHERE id = :i"), {"i": u.id})
    assert before.startswith("v2:local:")

    settings = get_settings()
    settings.field_data_keys = {"2026-10": crypto.new_wrapped_key("2026-10")}
    settings.field_active_key = "2026-10"
    await _rotate_field_keys()
    async with sf() as s:
        after = await s.scalar(text("SELECT mfa_secret_enc FROM identity.identities WHERE id = :i"), {"i": u.id})
    assert after.startswith("v2:2026-10:") and crypto.decrypt_field(after) == crypto.decrypt_field(before)
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": u.password, "totpCode": u.totp()})
    assert r.status_code == 200, r.text
