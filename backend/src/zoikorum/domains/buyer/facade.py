"""Buyer facade - CONTRACT. Signatures and DTOs are fixed; implement bodies.

Every buyer acts through an organization. An individual buyer gets an
INDIVIDUAL organization where they hold every org role.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.shared.money import Money


@dataclass(frozen=True)
class OrganizationSummary:
    id: uuid.UUID
    name: str
    org_type: str  # INDIVIDUAL | BUSINESS | ENTERPRISE
    country: str
    status: str  # ACTIVE | SUSPENDED
    business_context: str | None  # STARTUP|SME|MID_MARKET|ENTERPRISE|INDIVIDUAL


@dataclass(frozen=True)
class CostCenterSummary:
    id: uuid.UUID
    organization_id: uuid.UUID
    business_unit_id: uuid.UUID | None
    name: str
    quarterly_budget: Money | None


async def get_organization(session: AsyncSession, org_id: uuid.UUID) -> OrganizationSummary | None:
    raise NotImplementedError


async def get_member_roles(session: AsyncSession, org_id: uuid.UUID, identity_id: uuid.UUID) -> frozenset[str]:
    """Empty set when not a member."""
    raise NotImplementedError


async def get_member_spend_limit(session: AsyncSession, org_id: uuid.UUID, identity_id: uuid.UUID) -> Money | None:
    """Approval authority. None => no limit configured (unlimited for ORG_ADMIN, zero otherwise)."""
    raise NotImplementedError


async def list_member_identities(
    session: AsyncSession, org_id: uuid.UUID, roles: Iterable[str] | None = None
) -> list[uuid.UUID]:
    raise NotImplementedError


async def get_cost_center(session: AsyncSession, cost_center_id: uuid.UUID) -> CostCenterSummary | None:
    raise NotImplementedError
