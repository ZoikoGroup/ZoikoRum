"""Passkeys (WebAuthn, identity/passkeys.py), driven by a software authenticator that signs exactly like a phone or
laptop would: a P-256 key pair, real authenticator data, real signatures."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from zoikorum.shared.auth import AuthStrength, decode_access_token

ORIGIN, RP_ID = "http://localhost:5173", "localhost"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SoftAuthenticator:
    """One passkey on one device."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.count = 0
        self.user_handle = b""

    def _client_data(self, kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()

    def create(self, options: dict, origin: str = ORIGIN) -> dict:
        numbers = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})
        auth_data = (hashlib.sha256(options["rp"]["id"].encode()).digest() + bytes([0x01 | 0x04 | 0x40])
                     + struct.pack(">I", self.count) + bytes(16) + struct.pack(">H", len(self.credential_id))
                     + self.credential_id + cose)
        self.user_handle = unb64(options["user"]["id"])
        return {"id": b64(self.credential_id), "rawId": b64(self.credential_id), "type": "public-key",
                "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(self._client_data("webauthn.create", options["challenge"], origin)),
                             "attestationObject": b64(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})),
                             "transports": ["internal"]}}

    def get(self, options: dict, origin: str = ORIGIN) -> dict:
        self.count += 1
        auth_data = hashlib.sha256(options["rpId"].encode()).digest() + bytes([0x01 | 0x04]) + struct.pack(">I", self.count)
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.credential_id), "rawId": b64(self.credential_id), "type": "public-key",
                "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(client_data), "authenticatorData": b64(auth_data),
                             "signature": b64(signature), "userHandle": b64(self.user_handle)}}


async def add_passkey(client, user, device: SoftAuthenticator, name="Work laptop"):
    options = (await client.post("/v1/me/passkeys/options", headers=user.h, json={"password": user.password})).json()
    assert options["rp"]["id"] == RP_ID and options["authenticatorSelection"]["userVerification"] == "required"
    r = await client.post("/v1/me/passkeys", headers=user.h, json={"name": name, "credential": device.create(options)})
    assert r.status_code == 201, r.text
    return r.json()


async def sign_in(client, device: SoftAuthenticator, portal="customer", origin=ORIGIN):
    options = (await client.post("/v1/auth/passkey/options")).json()
    return await client.post("/v1/auth/passkey", json={"credential": device.get(options, origin), "portal": portal})


async def test_a_passkey_is_added_with_the_password_and_signs_in_as_two_step(client, make_user):
    user = await make_user("pia")
    wrong = await client.post("/v1/me/passkeys/options", headers=user.h, json={"password": "not my password"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "PASSWORD_INCORRECT"
    device = SoftAuthenticator()
    added = await add_passkey(client, user, device)
    assert [p["name"] for p in (await client.get("/v1/me/passkeys", headers=user.h)).json()] == ["Work laptop"]
    assert added["lastUsedAt"] is None

    r = await sign_in(client, device)
    assert r.status_code == 200, r.text
    actor = decode_access_token(r.json()["tokens"]["accessToken"])
    assert actor.identity_id == user.id and actor.auth_strength == AuthStrength.PASSKEY  # counts as two-step
    assert (await client.get("/v1/me/passkeys", headers=user.h)).json()[0]["lastUsedAt"] is not None


async def test_signed_answers_work_once_and_only_from_this_site(client, make_user):
    user = await make_user("ola")
    device = SoftAuthenticator()
    await add_passkey(client, user, device)
    options = (await client.post("/v1/auth/passkey/options")).json()
    answer = device.get(options)
    assert (await client.post("/v1/auth/passkey", json={"credential": answer})).status_code == 200
    replay = await client.post("/v1/auth/passkey", json={"credential": answer})
    assert replay.status_code == 401 and replay.json()["code"] == "PASSKEY_CHALLENGE_INVALID"

    phished = await sign_in(client, device, origin="https://zoikorum-login.example")  # a look-alike site
    assert phished.status_code == 401 and phished.json()["code"] == "PASSKEY_INVALID"
    unknown = await sign_in(client, SoftAuthenticator())
    assert unknown.status_code == 401 and unknown.json()["code"] == "PASSKEY_UNKNOWN"


async def test_passkey_sign_in_keeps_staff_and_customers_on_their_own_page(client, make_user):
    customer, staff = await make_user("cat"), await make_user("sam", platform_roles=("COMPLIANCE_OFFICER",))
    customer_key, staff_key = SoftAuthenticator(), SoftAuthenticator()
    await add_passkey(client, customer, customer_key)
    await add_passkey(client, staff, staff_key)
    assert (await sign_in(client, customer_key, portal="staff")).json()["code"] == "NOT_STAFF_ACCOUNT"
    assert (await sign_in(client, staff_key, portal="customer")).json()["code"] == "USE_STAFF_SIGN_IN"
    assert (await sign_in(client, staff_key, portal="staff")).status_code == 200


async def test_a_passkey_confirms_sensitive_actions_and_can_be_removed(client, make_user):
    user = await make_user("raj")
    device = SoftAuthenticator()
    added = await add_passkey(client, user, device)
    options = (await client.post("/v1/auth/step-up/passkey/options", headers=user.h)).json()
    assert [c["id"] for c in options["allowCredentials"]] == [b64(device.credential_id)]  # only your own passkeys
    r = await client.post("/v1/auth/step-up/passkey", headers=user.h, json={"credential": device.get(options)})
    assert r.status_code == 200, r.text
    assert decode_access_token(r.json()["accessToken"]).auth_strength == AuthStrength.PASSKEY

    other = await make_user("eve")
    assert (await client.delete(f"/v1/me/passkeys/{added['id']}", headers=other.h)).status_code == 404
    assert (await client.delete(f"/v1/me/passkeys/{added['id']}", headers=user.h)).status_code == 204
    assert (await sign_in(client, device)).json()["code"] == "PASSKEY_UNKNOWN"
    assert (await client.post("/v1/auth/step-up/passkey/options", headers=user.h)).json()["code"] == "NO_PASSKEY"
