"""WebAuthn commands: server challenges, user verification and locked counters."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from webauthn import (generate_registration_options, generate_authentication_options,
                      verify_registration_response, verify_authentication_response, options_to_json)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, ResidentKeyRequirement,
                                     UserVerificationRequirement, PublicKeyCredentialDescriptor)

from zoikorum.config import get_settings
from zoikorum.domains.identity import service, facade
from zoikorum.domains.identity.models import AuthChallenge, Passkey, Identity
from zoikorum.domains.identity.schemas import AuthOut
from zoikorum.shared.event_catalog import E
from zoikorum.shared import clock
from zoikorum.shared.auth import AuthStrength
from zoikorum.shared.errors import Unauthenticated, NotFound, Forbidden, ServiceUnavailable


def configuration():
    s = get_settings()
    origin = urlparse(s.passkey_origin)
    if (origin.hostname != s.passkey_rp_id and not (origin.hostname or '').endswith('.' + s.passkey_rp_id)
            or origin.path not in ('', '/') or origin.query or origin.fragment
            or origin.username or (origin.scheme != 'https' and (origin.hostname != 'localhost' or s.env == 'production'))):
        raise ServiceUnavailable('Passkey origin and relying party are not configured correctly')
    return s


async def begin(session, *, actor=None, registration=False):
    s = configuration()
    if registration:
        if not actor:
            raise Unauthenticated()
        # Enrolling a new factor is sensitive; do not permit a stolen password-only
        # session to add a factor once an account already has one.
        identity = await session.get(Identity, actor.identity_id)
        existing = list((await session.scalars(select(Passkey).where(Passkey.identity_id == identity.id))).all())
        if identity.mfa_enabled_at or existing:
            actor.require_step_up()
        options = generate_registration_options(
            rp_id=s.passkey_rp_id, rp_name='Zoikorum', user_id=identity.id.bytes,
            user_name=identity.email, user_display_name=identity.display_name,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=k.credential_id) for k in existing])
    else:
        options = generate_authentication_options(rp_id=s.passkey_rp_id,
            user_verification=UserVerificationRequirement.REQUIRED)
    challenge = AuthChallenge(identity_id=actor.identity_id if actor else None,
        session_id=actor.session_id if actor else None,
        purpose='REGISTER' if registration else 'AUTHENTICATE', challenge=options.challenge,
        expires_at=clock.now() + timedelta(minutes=5))
    session.add(challenge)
    await session.flush()
    return {'challengeId': str(challenge.id), 'publicKey': json.loads(options_to_json(options))}


async def _challenge(session, challenge_id, purpose, actor):
    row = await session.scalar(select(AuthChallenge).where(AuthChallenge.id == challenge_id).with_for_update())
    if (not row or row.purpose != purpose or row.used_at or row.expires_at <= clock.now()
            or (row.identity_id and (not actor or row.identity_id != actor.identity_id or row.session_id != actor.session_id))):
        raise Unauthenticated('Passkey challenge expired or does not belong to this session')
    return row


async def register(session, actor, challenge_id, credential, label):
    s = configuration()
    row = await _challenge(session, challenge_id, 'REGISTER', actor)
    identity = await session.get(Identity, actor.identity_id)
    if identity.mfa_enabled_at or identity.passkey_enabled:
        actor.require_step_up()
    try:
        result = verify_registration_response(credential=credential, expected_challenge=row.challenge,
            expected_rp_id=s.passkey_rp_id, expected_origin=s.passkey_origin, require_user_verification=True)
    except Exception as error:
        raise Unauthenticated('Passkey registration could not be verified') from error
    if await session.scalar(select(Passkey.id).where(Passkey.credential_id == result.credential_id)):
        raise Forbidden('This passkey has already been registered')
    session.add(Passkey(identity_id=actor.identity_id, credential_id=result.credential_id,
        public_key=result.credential_public_key, sign_count=result.sign_count, label=label))
    identity = await session.get(Identity, actor.identity_id)
    identity.passkey_enabled = True
    service._evt(session, E.PASSKEY_REGISTERED, identity)
    row.used_at = clock.now()
    await session.flush()


async def authenticate(session, challenge_id, credential, user_agent, actor=None):
    s = configuration()
    row = await _challenge(session, challenge_id, 'AUTHENTICATE', actor)
    try:
        credential_id = base64url_to_bytes(credential['id'])
    except (ValueError, KeyError, TypeError) as error:
        raise Unauthenticated('Invalid passkey') from error
    key = await session.scalar(select(Passkey).where(Passkey.credential_id == credential_id).with_for_update())
    if not key or (actor and key.identity_id != actor.identity_id):
        raise Unauthenticated('Passkey does not belong to this account')
    if not await facade.account_is_active(session, key.identity_id):
        raise Forbidden('This account is restricted', code='ACCOUNT_NOT_ACTIVE')
    try:
        result = verify_authentication_response(credential=credential, expected_challenge=row.challenge,
            expected_rp_id=s.passkey_rp_id, expected_origin=s.passkey_origin,
            credential_public_key=key.public_key, credential_current_sign_count=key.sign_count,
            require_user_verification=True)
    except Exception as error:
        raise Unauthenticated('Passkey authentication could not be verified') from error
    key.sign_count = result.new_sign_count
    row.used_at = clock.now()
    identity = await session.get(Identity, key.identity_id)
    pair = await service._start_session(session, identity, AuthStrength.PASSKEY, user_agent)
    service._evt(session, E.STEP_UP_COMPLETED if actor else E.AUTHENTICATION_SUCCEEDED, identity, authStrength=AuthStrength.PASSKEY)
    user = service.to_out(identity, await service._links(session, identity.id))
    # A verified passkey session satisfies the required strong-authentication gate.
    user.mfaRequired = False
    return AuthOut(tokens=pair, user=user)


async def listing(session, actor):
    rows = (await session.scalars(select(Passkey).where(Passkey.identity_id == actor.identity_id))).all()
    return [{'id': str(k.id), 'label': k.label, 'createdAt': k.created_at} for k in rows]


async def remove(session, actor, key_id):
    actor.require_step_up()
    row = await session.scalar(select(Passkey).where(Passkey.id == key_id,
        Passkey.identity_id == actor.identity_id).with_for_update())
    if not row:
        raise NotFound('Passkey not found')
    await session.delete(row)
    await session.flush()
    identity = await session.get(Identity, actor.identity_id)
    identity.passkey_enabled = bool(await session.scalar(select(Passkey.id).where(Passkey.identity_id == actor.identity_id).limit(1)))
    service._evt(session, E.PASSKEY_REMOVED, identity, passkeyId=key_id)
