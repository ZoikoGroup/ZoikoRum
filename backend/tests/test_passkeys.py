"""Real signed WebAuthn ceremonies, including replay, scope and counter checks."""
import base64
import hashlib
import json
import struct
import cbor2
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def registration(options, private, credential_id, origin='http://localhost:5173'):
    nums = private.public_key().public_numbers()
    cose = {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, 'big'), -3: nums.y.to_bytes(32, 'big')}
    client = json.dumps({'type': 'webauthn.create', 'challenge': options['challenge'], 'origin': origin}).encode()
    auth = hashlib.sha256(b'localhost').digest() + b'\x45' + struct.pack('>I', 0) + b'\x00' * 16 + struct.pack('>H', len(credential_id)) + credential_id + cbor2.dumps(cose)
    return {'id': b64(credential_id), 'rawId': b64(credential_id), 'type': 'public-key',
        'response': {'clientDataJSON': b64(client), 'attestationObject': b64(cbor2.dumps({'fmt': 'none', 'attStmt': {}, 'authData': auth}))}}


def assertion(options, private, credential_id, counter=1, origin='http://localhost:5173'):
    client = json.dumps({'type': 'webauthn.get', 'challenge': options['challenge'], 'origin': origin}).encode()
    auth = hashlib.sha256(b'localhost').digest() + b'\x05' + struct.pack('>I', counter)
    signature = private.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return {'id': b64(credential_id), 'rawId': b64(credential_id), 'type': 'public-key',
        'response': {'clientDataJSON': b64(client), 'authenticatorData': b64(auth), 'signature': b64(signature), 'userHandle': None}}


async def test_verified_passkeys_reject_replay_wrong_origin_and_revoke_immediately(client, make_user):
    user = await make_user('passkey-owner')
    other = await make_user('passkey-other')
    private = ec.generate_private_key(ec.SECP256R1())
    keyid = b'passkey-regression-credential'
    c = (await client.post('/v1/me/passkeys/options', headers=user.h)).json()
    body = {'challengeId': c['challengeId'], 'credential': registration(c['publicKey'], private, keyid), 'label': 'Laptop'}
    assert (await client.post('/v1/me/passkeys', headers=other.h, json=body)).status_code == 401
    enrolled = await client.post('/v1/me/passkeys', headers=user.h, json=body)
    assert enrolled.status_code == 201, enrolled.text
    assert (await client.post('/v1/me/passkeys', headers=user.h, json=body)).status_code == 401
    assert (await client.get('/v1/me/passkeys', headers=other.h)).json() == []
    c = (await client.post('/v1/auth/passkeys/options')).json()
    bad = {'challengeId': c['challengeId'], 'credential': assertion(c['publicKey'], private, keyid, origin='https://attacker.example')}
    assert (await client.post('/v1/auth/passkeys/verify', json=bad)).status_code == 401
    body = {'challengeId': c['challengeId'], 'credential': assertion(c['publicKey'], private, keyid)}
    authenticated = await client.post('/v1/auth/passkeys/verify', json=body)
    assert authenticated.status_code == 200, authenticated.text
    assert authenticated.json()['user']['id'] == str(user.id)
    assert (await client.post('/v1/auth/passkeys/verify', json=body)).status_code == 401
    h = {'Authorization': 'Bearer ' + authenticated.json()['tokens']['accessToken']}
    c = (await client.post('/v1/auth/passkeys/step-up/options', headers=other.h)).json()
    assert (await client.post('/v1/auth/passkeys/step-up', headers=other.h, json={'challengeId': c['challengeId'], 'credential': assertion(c['publicKey'], private, keyid, 2)})).status_code == 401
    key = (await client.get('/v1/me/passkeys', headers=h)).json()[0]
    assert (await client.delete('/v1/me/passkeys/' + key['id'], headers=other.h)).status_code in (401, 403, 404)
    assert (await client.delete('/v1/me/passkeys/' + key['id'], headers=h)).status_code == 204
    c = (await client.post('/v1/auth/passkeys/options')).json()
    assert (await client.post('/v1/auth/passkeys/verify', json={'challengeId': c['challengeId'], 'credential': assertion(c['publicKey'], private, keyid, 2)})).status_code == 401
