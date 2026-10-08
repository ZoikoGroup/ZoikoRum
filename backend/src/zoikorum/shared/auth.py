"""Token verification and authorization helpers (RBAC + ABAC, Architecture 11.3).

Tokens are minted by the identity domain; every other domain only *verifies*
them here. RBAC gives coarse platform roles; ABAC checks are explicit calls
such as ``actor.require_org(org_id)`` inside services, next to the data they
protect. Never rely on the frontend hiding a button.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request

from zoikorum.config import get_settings
from zoikorum.shared import clock, context
from zoikorum.shared.errors import Forbidden, StepUpRequired, Unauthenticated


class PlatformRole:
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    TS_ANALYST = "TS_ANALYST"  # Trust & Safety analyst - first-line assessment
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"  # credential & regulatory validation
    RISK_LEAD = "RISK_LEAD"
    LEGAL = "LEGAL"
    MEDIATOR = "MEDIATOR"
    FINANCIAL_OPS = "FINANCIAL_OPS"
    EXECUTIVE = "EXECUTIVE"
    AI_SAFETY_REVIEWER = "AI_SAFETY_REVIEWER"

    ALL = frozenset(
        {
            PLATFORM_ADMIN, TS_ANALYST, COMPLIANCE_OFFICER, RISK_LEAD, LEGAL,
            MEDIATOR, FINANCIAL_OPS, EXECUTIVE, AI_SAFETY_REVIEWER,
        }
    )


class Persona:
    """Account roles a ZoikoID holds on the marketplace (chosen at signup, more can be added).

    One identity may hold several, e.g. a buyer who also offers services as a professional.
    """

    BUYER = "BUYER"
    PROFESSIONAL = "PROFESSIONAL"
    FIRM_ADMIN = "FIRM_ADMIN"
    ENTERPRISE_ADMIN = "ENTERPRISE_ADMIN"
    ENTERPRISE_MEMBER = "ENTERPRISE_MEMBER"  # invited enterprise team member (Requester, Approver ...)

    ALL = frozenset({BUYER, PROFESSIONAL, FIRM_ADMIN, ENTERPRISE_ADMIN, ENTERPRISE_MEMBER})
    # Chosen by the user themselves; the others are derived from organization/firm membership.
    SELF_SERVICE = frozenset({BUYER, PROFESSIONAL})
    # Signup "account type" -> persona granted.
    FROM_ACCOUNT_TYPE = {"BUYER": BUYER, "PROFESSIONAL": PROFESSIONAL, "FIRM": FIRM_ADMIN, "ENTERPRISE": ENTERPRISE_ADMIN}


class OrgRole:
    """Buyer-organization roles (Enterprise Policy doc s.11)."""

    ORG_ADMIN = "ORG_ADMIN"
    REQUESTER = "REQUESTER"
    APPROVER = "APPROVER"
    BUDGET_OWNER = "BUDGET_OWNER"
    LEGAL_REVIEWER = "LEGAL_REVIEWER"
    EXCEPTION_AUTHORITY = "EXCEPTION_AUTHORITY"

    ALL = frozenset({ORG_ADMIN, REQUESTER, APPROVER, BUDGET_OWNER, LEGAL_REVIEWER, EXCEPTION_AUTHORITY})


class FirmRole:
    """Roles inside a firm (Firm domain)."""

    FIRM_ADMIN = "FIRM_ADMIN"
    FIRM_MEMBER = "FIRM_MEMBER"
    AUTHORIZED_REPRESENTATIVE = "AUTHORIZED_REPRESENTATIVE"  # legally acts for the firm; verified later

    ALL = frozenset({FIRM_ADMIN, FIRM_MEMBER, AUTHORIZED_REPRESENTATIVE})


class AuthStrength:
    PASSWORD = "PASSWORD"
    OAUTH = "OAUTH"
    MFA = "MFA"
    PASSKEY = "PASSKEY"

    ELEVATED = frozenset({MFA, PASSKEY})


@dataclass(frozen=True)
class Actor:
    identity_id: uuid.UUID
    session_id: uuid.UUID | None
    email: str | None
    platform_roles: frozenset[str] = frozenset()
    personas: frozenset[str] = frozenset()
    # Buyer side: organization memberships {org_id: {roles}}
    org_roles: dict[str, frozenset[str]] = field(default_factory=dict)
    professional_id: uuid.UUID | None = None
    firm_roles: dict[str, frozenset[str]] = field(default_factory=dict)
    auth_strength: str = AuthStrength.PASSWORD
    auth_time: datetime | None = None

    # ---- RBAC ---------------------------------------------------------------
    def has_platform_role(self, *roles: str) -> bool:
        return bool(self.platform_roles.intersection(roles))

    def require_platform_role(self, *roles: str) -> None:
        if not self.has_platform_role(*roles):
            raise Forbidden(f"Requires one of platform roles: {', '.join(roles)}")
        # Staff accounts must always work from an MFA-backed session.
        if self.auth_strength not in AuthStrength.ELEVATED:
            raise StepUpRequired("Staff access requires multi-factor authentication")

    @property
    def is_operator(self) -> bool:
        return bool(self.platform_roles)

    def has_persona(self, *personas: str) -> bool:
        return bool(self.personas.intersection(personas))

    def require_persona(self, *personas: str) -> None:
        if not self.has_persona(*personas):
            names = " or ".join(p.replace("_", " ").title() for p in personas)
            raise Forbidden(f"This action is available to {names} accounts", code="ROLE_REQUIRED")

    # ---- ABAC: buyer organizations -----------------------------------------
    @property
    def org_ids(self) -> list[uuid.UUID]:
        return [uuid.UUID(o) for o in self.org_roles]

    def in_org(self, org_id: Any) -> bool:
        return str(org_id) in self.org_roles

    def has_org_role(self, org_id: Any, *roles: str) -> bool:
        return bool(self.org_roles.get(str(org_id), frozenset()).intersection(roles))

    def require_org(self, org_id: Any, *roles: str) -> None:
        if not self.in_org(org_id):
            raise Forbidden("You are not a member of this organization")
        if roles and not self.has_org_role(org_id, *roles):
            raise Forbidden(f"Requires organization role: {', '.join(roles)}")

    # ---- ABAC: professional side -------------------------------------------
    def is_professional(self, professional_id: Any) -> bool:
        return self.professional_id is not None and str(self.professional_id) == str(professional_id)

    def require_professional(self, professional_id: Any) -> None:
        if not self.is_professional(professional_id):
            raise Forbidden("This action belongs to a different professional")

    def has_firm_role(self, firm_id: Any, *roles: str) -> bool:
        return bool(self.firm_roles.get(str(firm_id), frozenset()).intersection(roles))

    # ---- Step-up (Architecture 11.4) ---------------------------------------
    def require_step_up(self, max_age_seconds: int | None = None) -> None:
        max_age = max_age_seconds or get_settings().step_up_max_age_seconds
        if self.auth_strength not in AuthStrength.ELEVATED or self.auth_time is None:
            raise StepUpRequired("Confirm with MFA or a passkey to continue")
        if (clock.now() - self.auth_time).total_seconds() > max_age:
            raise StepUpRequired("Your elevated session expired; confirm with MFA again")


def decode_access_token(token: str) -> Actor:
    s = get_settings()
    try:
        claims = jwt.decode(
            token,
            s.jwt_secret,
            algorithms=["HS256"],
            issuer=s.jwt_issuer,
            options={"require": ["exp", "sub", "iat"]},
            leeway=5,
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthenticated("Access token expired") from exc
    except jwt.PyJWTError as exc:
        raise Unauthenticated("Invalid access token") from exc
    if claims.get("typ") != "access":
        raise Unauthenticated("Not an access token")
    return Actor(
        identity_id=uuid.UUID(claims["sub"]),
        session_id=uuid.UUID(claims["sid"]) if claims.get("sid") else None,
        email=claims.get("email"),
        platform_roles=frozenset(claims.get("roles", [])),
        personas=frozenset(claims.get("personas", [])),
        org_roles={k: frozenset(v) for k, v in claims.get("orgs", {}).items()},
        professional_id=uuid.UUID(claims["pro"]) if claims.get("pro") else None,
        firm_roles={k: frozenset(v) for k, v in claims.get("firms", {}).items()},
        auth_strength=claims.get("amr", AuthStrength.PASSWORD),
        auth_time=datetime.fromtimestamp(claims["auth_time"], tz=timezone.utc) if claims.get("auth_time") else None,
    )


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def _current_actor(request: Request) -> Actor:
    token = _bearer(request)
    if not token:
        raise Unauthenticated()
    actor = decode_access_token(token)
    validator = getattr(request.app.state, "actor_validator", None)
    if validator:
        actor = await validator(actor, request.url.path, request.method)
    context.bind_actor(str(actor.identity_id), "operator" if actor.is_operator else "user", None, actor.auth_strength)
    request.state.actor = actor
    return actor


async def _optional_actor(request: Request) -> Actor | None:
    token = _bearer(request)
    if not token:
        return None
    return await _current_actor(request)


CurrentActor = Annotated[Actor, Depends(_current_actor)]


def require_roles(*roles: str):
    """Route guard: caller must hold at least one of the given personas or platform roles.

        @router.post("/v1/offerings", dependencies=[Depends(require_roles(Persona.PROFESSIONAL))])
    """
    personas = [r for r in roles if r in Persona.ALL]
    staff = [r for r in roles if r in PlatformRole.ALL]

    async def guard(actor: CurrentActor) -> Actor:
        if personas and actor.has_persona(*personas):
            return actor
        if staff and actor.has_platform_role(*staff):
            actor.require_platform_role(*staff)  # also enforces MFA for staff
            return actor
        names = " or ".join(r.replace("_", " ").title() for r in roles)
        raise Forbidden(f"This area is available to {names} accounts", code="ROLE_REQUIRED")

    return guard
OptionalActor = Annotated[Actor | None, Depends(_optional_actor)]


def system_actor() -> Actor:
    """Actor used by event consumers / timers when a domain API needs one."""
    return Actor(identity_id=uuid.UUID(int=0), session_id=None, email=None, auth_strength=AuthStrength.PASSKEY)
