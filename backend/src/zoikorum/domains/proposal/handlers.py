from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.proposal import service
from zoikorum.shared.relay import on_timer
from zoikorum.shared.events import subscribe, record_audit
from zoikorum.shared.event_catalog import E
from zoikorum.shared.errors import DomainError
import uuid


@subscribe(E.APPROVAL_GRANTED, consumer="proposal.policy_continuation")
@subscribe(E.EXCEPTION_GRANTED, consumer="proposal.policy_continuation")
async def continue_authorized(session, event):
    p = event.payload
    if p.get("subjectType") != "Proposal" or p.get("action") not in ("PROPOSAL_ACCEPT", "PROPOSAL_SUBMIT"):
        return
    actor = await service.policy_facade.continuation_actor(session, p)
    if not actor:
        return
    command = service.accept_proposal if p["action"] == "PROPOSAL_ACCEPT" else service.submit_proposal
    try:
        async with session.begin_nested():
            await command(session, actor, uuid.UUID(str(p["subjectId"])))
    except DomainError as exc:
        record_audit(session, "proposal.policy.continuation_skipped", object_type="Proposal", object_id=p["subjectId"],
                     details={"reason": exc.code})


@on_timer(service.TIMER_EXPIRY)
async def on_expiry(session: AsyncSession, key: str, payload: dict) -> None:
    """A sent proposal past its validity date expires and can no longer be accepted."""
    await service.expire(session, payload)
