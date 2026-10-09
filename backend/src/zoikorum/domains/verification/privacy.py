"""Verification checks about the person (shared/privacy.py). Kept for the verification retention period."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.verification.models import EvidenceItem, VerificationCase
from zoikorum.shared import privacy


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    ids = (await session.scalars(select(VerificationCase.id).where(VerificationCase.owner_identity_id == identity_id))).all()
    return {"checks": await privacy.rows(session, VerificationCase, VerificationCase.owner_identity_id == identity_id),
            # Documents are listed by name and fingerprint; the files themselves are sent on request by support.
            "documents": await privacy.rows(session, EvidenceItem, EvidenceItem.case_id.in_(ids))}


privacy.register("verification", export=export,
                 retained="Identity and credential checks with their documents, for the period the law requires "
                          "(anti-money-laundering and licensing records).")
