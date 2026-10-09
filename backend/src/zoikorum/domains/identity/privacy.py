"""Identity's personal data (shared/privacy.py). Erasure anonymises the account itself and runs last."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity.models import ConsentRecord, DataRequest, Identity, IdentityLink, Session
from zoikorum.shared import clock, privacy
from zoikorum.shared.crypto import decrypt_field

DELETED_NAME = "Deleted user"


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    identity = await session.get(Identity, identity_id)
    if identity is None:
        return {}
    account = privacy.row(identity)
    account["phone"] = decrypt_field(identity.phone_enc) if identity.phone_enc else None
    account["twoStepVerification"] = identity.mfa_enabled_at is not None
    return {
        "account": account,
        "consents": await privacy.rows(session, ConsentRecord, ConsentRecord.identity_id == identity_id),
        "memberships": await privacy.rows(session, IdentityLink, IdentityLink.identity_id == identity_id),
        "signIns": await privacy.rows(session, Session, Session.identity_id == identity_id,
                                      exclude=("family_id",)),
        "privacyRequests": await privacy.rows(session, DataRequest, DataRequest.identity_id == identity_id,
                                              exclude=("export_key",)),
    }


async def erase(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    """The account can no longer sign in and no longer names the person. Consent records are kept (proof of terms)."""
    identity = await session.get(Identity, identity_id, with_for_update=True)
    if identity is None:
        return {}
    now = clock.now()
    identity.email = f"deleted-{identity.id}@deleted.invalid"
    identity.display_name = DELETED_NAME
    identity.password_hash = None
    identity.phone_enc = None
    identity.mfa_secret_enc = None
    identity.mfa_enabled_at = None
    identity.signup_organization_name = None
    identity.time_zone = None
    identity.status = "DELETED"
    revoked = (await session.execute(update(Session).where(Session.identity_id == identity_id, Session.revoked_at.is_(None))
                                     .values(revoked_at=now))).rowcount
    return {"anonymised": True, "sessionsEnded": revoked}


privacy.register("identity", export=export, erase=erase,
                 retained="Proof that you accepted the terms, kept with the anonymised account.")


async def is_deleted(session: AsyncSession, identity_id: uuid.UUID) -> bool:
    return await session.scalar(select(Identity.status).where(Identity.id == identity_id)) == "DELETED"
