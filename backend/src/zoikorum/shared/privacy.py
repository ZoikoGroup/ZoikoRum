"""Privacy requests (GDPR / CCPA access and erasure) across domains, without crossing domain boundaries.

Each domain that holds personal data registers, in its ``privacy.py`` (imported by its ``handlers``):

    export(session, identity_id)   -> dict          everything it holds about the person (never secrets)
    erase(session, identity_id)    -> dict          removes or anonymises what may be removed; returns a summary
    blockers(session, identity_id) -> list[str]     plain-language reasons the account cannot be deleted yet
    retained: str                                    what it must keep by law, shown to the person

The identity domain owns the requests and runs these (``identity/privacy_requests.py``). Records kept by law
(contracts, payments, invoices, disputes, verification evidence, audit) stay; they then refer to an anonymised
account ("Deleted user").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Awaitable, Callable

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

Exporter = Callable[[AsyncSession, uuid.UUID], Awaitable[dict]]
Eraser = Callable[[AsyncSession, uuid.UUID], Awaitable[dict]]
Blockers = Callable[[AsyncSession, uuid.UUID], Awaitable[list[str]]]

# Columns never exported, whatever table they are in.
SECRET_COLUMNS = frozenset({"password_hash", "mfa_secret_enc", "refresh_token_hash", "phone_enc", "secret_enc",
                            "signing_secret_enc", "token_hash", "storage_key", "photo_key"})


@dataclass(frozen=True)
class PersonalData:
    domain: str
    export: Exporter
    erase: Eraser | None = None
    blockers: Blockers | None = None
    retained: str | None = None


_REGISTRY: dict[str, PersonalData] = {}


def register(domain: str, *, export: Exporter, erase: Eraser | None = None, blockers: Blockers | None = None,
             retained: str | None = None) -> None:
    _REGISTRY[domain] = PersonalData(domain, export, erase, blockers, retained)


def registered() -> list[PersonalData]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def _value(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (uuid.UUID, Decimal)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _value(x) for k, x in v.items()}
    return v


def row(obj: Any, exclude: tuple[str, ...] = ()) -> dict:
    """One ORM row as plain JSON values, without secret or excluded columns."""
    return {c.key: _value(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs
            if c.key not in SECRET_COLUMNS and c.key not in exclude}


async def rows(session: AsyncSession, model: Any, *where: Any, exclude: tuple[str, ...] = ()) -> list[dict]:
    found = (await session.scalars(select(model).where(*where).order_by(model.created_at))).all()
    return [row(o, exclude) for o in found]


async def export_all(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    return {p.domain: await p.export(session, identity_id) for p in registered()}


async def erasure_blockers(session: AsyncSession, identity_id: uuid.UUID) -> list[str]:
    reasons: list[str] = []
    for p in registered():
        if p.blockers:
            reasons += await p.blockers(session, identity_id)
    return reasons


async def erase_all(session: AsyncSession, identity_id: uuid.UUID, *, last: str) -> dict:
    """Every domain's erasure; ``last`` (identity) runs at the end so the others can still read the account."""
    summary = {}
    for p in sorted(registered(), key=lambda p: p.domain == last):
        if p.erase:
            summary[p.domain] = await p.erase(session, identity_id)
    return summary


def retention_notes() -> dict[str, str]:
    return {p.domain: p.retained for p in registered() if p.retained}


async def allow_name_erasure(session: AsyncSession) -> None:
    """For this transaction only, let append-only tables replace a copied name with ERASED_NAME (shared/ddl.py)."""
    from sqlalchemy import text

    await session.execute(text("SELECT set_config('zoikorum.privacy_erasure', 'on', true)"))
