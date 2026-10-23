"""Identity's evidence for the retention job (shared/retention.py): personal-data export files ("data_export").

An export is stored when a person asks for their data and can be downloaded for ZK_DATA_EXPORT_DAYS; after the
retention period set for "data_export" in ZK_RETENTION_RULES the file itself is removed and the request keeps a note.
The jurisdiction is the account's country. Exports are never under legal hold.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity.models import DataRequest, Identity
from zoikorum.shared import clock
from zoikorum.shared.retention import RetainedFile, register_source

EVIDENCE_TYPE = "data_export"


async def _exports_older_than(session: AsyncSession, before: datetime, limit: int) -> list[RetainedFile]:
    rows = (await session.execute(
        select(DataRequest, Identity.country).join(Identity, Identity.id == DataRequest.identity_id)
        .where(DataRequest.request_type == "ACCESS", DataRequest.export_key.is_not(None), DataRequest.completed_at <= before)
        .order_by(DataRequest.completed_at).limit(limit))).all()
    return [RetainedFile(EVIDENCE_TYPE, r.export_key, None, country, r.completed_at, False, f"DataRequest:{r.id}") for r, country in rows]


async def _forget(session: AsyncSession, f: RetainedFile) -> None:
    import uuid

    r = await session.get(DataRequest, uuid.UUID(f.ref.split(":", 1)[1]), with_for_update=True)
    if r is not None:
        r.export_key = None
        r.detail = {**(r.detail or {}), "exportPurgedAt": clock.now().isoformat()}


register_source(EVIDENCE_TYPE, _exports_older_than, _forget)
