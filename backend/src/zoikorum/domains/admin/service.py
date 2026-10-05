"""Admin / operations: platform overview for staff. Enforcement cases arrive with Trust & Safety tooling."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.verification import facade as verification_facade
from zoikorum.shared.auth import Actor, PlatformRole


async def overview(session: AsyncSession, actor: Actor) -> dict:
    """Read-only platform counts for any staff member (MFA enforced by require_platform_role)."""
    actor.require_platform_role(*PlatformRole.ALL)
    accounts = await identity_facade.count_accounts(session)
    profiles = await professional_facade.count_profiles(session)
    checks = await verification_facade.open_case_counts(session)
    return {
        "accounts": {"total": accounts["total"], "buyers": accounts.get("BUYER", 0),
                     "professionals": accounts.get("PROFESSIONAL", 0), "firmAdmins": accounts.get("FIRM_ADMIN", 0),
                     "enterprise": accounts.get("ENTERPRISE_ADMIN", 0) + accounts.get("ENTERPRISE_MEMBER", 0)},
        "professionalProfiles": profiles,
        "verification": checks,
    }
