"""Operational switches (Engineering Handbook 23.3 "feature flags, kill switches").

Staff pause one kind of action at once, without a release, for example while a payment partner has an incident or a
fraud wave is under way. Every change needs step-up, a reason, and is audited.

* Refused while paused (503 FEATURE_PAUSED): sign-up, new proposal requests, proposal submission, escrow funding.
* Deferred while paused, never lost: escrow releases and payouts wait and are retried every 10 minutes, so they go out
  on their own once the switch is back on.
* AI assistance: every built-in AI feature uses its non-AI rules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.admin.models import FeatureSwitch
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import Forbidden, NotFound, ServiceUnavailable
from zoikorum.shared.events import record_audit


@dataclass(frozen=True)
class Switch:
    label: str
    effect: str
    money: bool  # Financial Operations may change it too


SWITCHES: dict[str, Switch] = {
    "SIGN_UPS": Switch("New accounts", "Sign-up is refused. Existing accounts sign in and work as normal.", False),
    "NEW_REQUESTS": Switch("New proposal requests", "Buyers cannot send new requests. Open requests carry on.", False),
    "PROPOSAL_SUBMISSION": Switch("Proposal submission", "Professionals can save drafts but not submit them.", False),
    "FUNDING": Switch("Escrow funding", "Buyers cannot fund milestones, so nothing new is charged.", True),
    "RELEASES": Switch("Escrow releases", "Accepted work stays held in escrow; each release is retried every 10 minutes "
                       "and goes out on its own once switched back on.", True),
    "PAYOUTS": Switch("Payouts to professionals", "Released money waits as a queued payout and is sent within 10 "
                      "minutes of switching back on.", True),
    "AI_ASSIST": Switch("AI assistance", "Every built-in AI feature uses its non-AI rules instead.", False),
}


async def is_paused(session: AsyncSession, key: str) -> bool:
    return bool(await session.scalar(select(FeatureSwitch.paused).where(FeatureSwitch.key == key)))


async def require_on(session: AsyncSession, key: str) -> None:
    if await is_paused(session, key):
        raise ServiceUnavailable(f"{SWITCHES[key].label} is paused for maintenance. Please try again later.",
                                 code="FEATURE_PAUSED", extra={"switch": key})


def _out(key: str, row: FeatureSwitch | None) -> dict:
    s = SWITCHES[key]
    return {"key": key, "label": s.label, "effect": s.effect, "money": s.money, "paused": bool(row and row.paused),
            "reason": row.reason if row else None, "changedBy": row.changed_by if row else None,
            "changedAt": row.updated_at if row else None}


async def list_switches(session: AsyncSession) -> list[dict]:
    rows = {r.key: r for r in (await session.scalars(select(FeatureSwitch))).all()}
    return [_out(k, rows.get(k)) for k in SWITCHES]


async def set_switch(session: AsyncSession, actor: Actor, key: str, paused: bool, reason: str) -> dict:
    from zoikorum.domains.admin.service import staff

    s = SWITCHES.get(key)
    if s is None:
        raise NotFound("Unknown switch")
    roles = (PlatformRole.PLATFORM_ADMIN, PlatformRole.FINANCIAL_OPS) if s.money else (PlatformRole.PLATFORM_ADMIN,)
    try:
        await staff(session, actor, *roles)
    except Forbidden as exc:
        raise Forbidden("Only a Platform Admin" + (" or Financial Operations" if s.money else "") + " can change this switch") from exc
    actor.require_step_up()
    row = await session.scalar(select(FeatureSwitch).where(FeatureSwitch.key == key).with_for_update())
    if row is None:
        row = FeatureSwitch(id=uuid.uuid4(), key=key, paused=False)
        session.add(row)
    changed = row.paused != paused
    row.paused, row.reason, row.changed_by = paused, reason.strip(), actor.identity_id
    await session.flush()
    if changed:
        record_audit(session, "admin.switch." + ("paused" if paused else "resumed"), object_type="FeatureSwitch",
                     object_id=row.id, details={"switch": key, "reason": row.reason})
    return _out(key, row)


async def gauges(session: AsyncSession) -> list[tuple[str, str, float]]:
    """Metrics: 1 for each paused switch, so an alert can fire if one is left off by mistake."""
    rows = {r.key: r.paused for r in (await session.scalars(select(FeatureSwitch))).all()}
    return [(f"zk_switch_paused_{k.lower()}", f"1 while {s.label.lower()} is paused", 1.0 if rows.get(k) else 0.0)
            for k, s in SWITCHES.items()]
