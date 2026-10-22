"""Administration / Trust & Safety facade - CONTRACT. Implement bodies."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def active_restrictions(session: AsyncSession, subject_type: str, subject_id: uuid.UUID) -> tuple[str, ...]:
    """Active enforcement actions for a subject (IDENTITY|PROFESSIONAL|ORGANIZATION),
    e.g. ("VISIBILITY_REDUCTION",). Empty tuple when clean."""
    from sqlalchemy import select, or_
    from zoikorum.domains.admin.models import EnforcementCase
    from zoikorum.shared import clock
    rows = (await session.scalars(select(EnforcementCase.action).where(
        EnforcementCase.subject_type == subject_type, EnforcementCase.subject_id == subject_id,
        EnforcementCase.status == "ACTIVE", or_(EnforcementCase.expires_at.is_(None), EnforcementCase.expires_at > clock.now())))).all()
    return tuple(sorted(set(rows)))


# ---- Operational switches (admin/switches.py) ------------------------------------------------------------------------

async def is_paused(session: AsyncSession, key: str) -> bool:
    """True while staff have paused this kind of action: SIGN_UPS, NEW_REQUESTS, PROPOSAL_SUBMISSION, FUNDING, RELEASES,
    PAYOUTS, AI_ASSIST. Deferred work (releases, payouts) checks this and retries later."""
    from zoikorum.domains.admin import switches
    return await switches.is_paused(session, key)


async def require_on(session: AsyncSession, key: str) -> None:
    """Refuses with 503 FEATURE_PAUSED while the switch is paused."""
    from zoikorum.domains.admin import switches
    await switches.require_on(session, key)


async def flag_enabled(session: AsyncSession, key: str, identity_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None) -> bool:
    """Whether a feature flag (admin/flags.py) is on for this organisation or person."""
    from zoikorum.domains.admin import flags
    return await flags.enabled(session, key, identity_id, org_id)



# ---- Maker-checker approvals (admin/approvals.py) ---------------------------------------------------------------------

from zoikorum.domains.admin.schemas import ApprovalRequestOut  # noqa: E402,F401  (response model of 202 answers)


async def request_approval(session: AsyncSession, actor, kind: str, payload: dict, justification: str) -> dict:
    """Records a privileged staff action for a second person to approve (status REQUESTED; nothing changes yet) and
    returns the request (ApprovalRequestOut). Raises when the requester lacks the authority or the action could never
    be carried out. Kinds: GRANT_PLATFORM_ROLE, REVOKE_PLATFORM_ROLE, SWITCH_CHANGE, FINANCIAL_EXCEPTION_RESOLVE,
    DEAD_LETTER_REPLAY_FINANCIAL, AUDIT_EXPORT."""
    from zoikorum.domains.admin import approvals
    return await approvals.request(session, actor, kind, payload, justification)
