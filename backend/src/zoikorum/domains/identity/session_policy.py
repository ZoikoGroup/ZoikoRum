"""Enterprise session policy: an organisation's rules for its members' sessions (Enterprise Policy s.11).

An Organisation Admin sets, per organisation:
* ``maxSessionSeconds``: a session ends this long after sign-in, however often it is refreshed;
* ``idleTimeoutSeconds``: a session ends when it has not been refreshed for this long;
* ``requireMfa``: password sessions must be two-step (authenticator or passkey); single sign-on sessions count as the
  identity provider's responsibility;
* ``allowedIdps``: the sign-in methods members may use (PASSWORD, PASSKEY, OIDC, SAML, GOOGLE, MICROSOFT); empty: any.

The rules are inherited by every member's session and checked when it refreshes (and the sign-in method when a new
session starts). Someone in several organisations gets the strictest combination. Staff sessions (admin audience) are
governed by the platform's own rules, not by a customer organisation's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity.models import IdentityLink, OrgSessionPolicy, Session
from zoikorum.shared.auth import Actor, AuthStrength, OrgRole
from zoikorum.shared.errors import Forbidden
from zoikorum.shared.events import record_audit

IDPS = ("PASSWORD", "PASSKEY", "OIDC", "SAML", "GOOGLE", "MICROSOFT")
SSO_IDPS = frozenset({"OIDC", "SAML"})


@dataclass(frozen=True)
class Effective:
    max_session_seconds: int | None = None
    idle_timeout_seconds: int | None = None
    require_mfa: bool = False
    allowed_idps: frozenset[str] | None = None  # None: any


def policy_out(org_id: uuid.UUID, p: OrgSessionPolicy | None) -> dict:
    return {"organizationId": org_id, "maxSessionSeconds": p.max_session_seconds if p else None,
            "idleTimeoutSeconds": p.idle_timeout_seconds if p else None, "requireMfa": bool(p and p.require_mfa),
            "allowedIdps": sorted(p.allowed_idps) if p else [], "updatedAt": p.updated_at if p else None}


async def _require_org_admin(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> None:
    from zoikorum.domains.buyer import facade as buyer

    if OrgRole.ORG_ADMIN not in await buyer.get_member_roles(session, org_id, actor.identity_id):
        raise Forbidden("Session rules are managed by an Organisation Admin", code="ROLE_REQUIRED")


async def get_policy(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> dict:
    await _require_org_admin(session, actor, org_id)
    return policy_out(org_id, await session.scalar(select(OrgSessionPolicy).where(OrgSessionPolicy.organization_id == org_id)))


async def set_policy(session: AsyncSession, actor: Actor, org_id: uuid.UUID, body) -> dict:
    await _require_org_admin(session, actor, org_id)
    actor.require_step_up()
    p = await session.scalar(select(OrgSessionPolicy).where(OrgSessionPolicy.organization_id == org_id).with_for_update())
    if p is None:
        p = OrgSessionPolicy(organization_id=org_id, updated_by=actor.identity_id)
        session.add(p)
    p.max_session_seconds, p.idle_timeout_seconds = body.maxSessionSeconds, body.idleTimeoutSeconds
    p.require_mfa, p.allowed_idps, p.updated_by = body.requireMfa, sorted(set(body.allowedIdps)), actor.identity_id
    await session.flush()
    record_audit(session, "identity.session_policy.updated", object_type="OrgSessionPolicy", object_id=p.id, tenant_id=org_id,
                 details={"maxSessionSeconds": p.max_session_seconds, "idleTimeoutSeconds": p.idle_timeout_seconds,
                          "requireMfa": p.require_mfa, "allowedIdps": p.allowed_idps})
    return policy_out(org_id, p)


async def effective_for(session: AsyncSession, identity_id: uuid.UUID) -> Effective:
    """The strictest combination of the policies of every organisation the person belongs to."""
    org_ids = (await session.scalars(select(IdentityLink.target_id).where(IdentityLink.identity_id == identity_id,
                                                                          IdentityLink.link_type == "ORG_MEMBER"))).all()
    if not org_ids:
        return Effective()
    rows = (await session.scalars(select(OrgSessionPolicy).where(OrgSessionPolicy.organization_id.in_(org_ids)))).all()
    if not rows:
        return Effective()

    def smallest(values):
        values = [v for v in values if v]
        return min(values) if values else None

    allowed = None
    for r in rows:
        if r.allowed_idps:
            allowed = set(r.allowed_idps) if allowed is None else allowed & set(r.allowed_idps)
    return Effective(smallest(r.max_session_seconds for r in rows), smallest(r.idle_timeout_seconds for r in rows),
                     any(r.require_mfa for r in rows), frozenset(allowed) if allowed is not None else None)


def _mfa_ok(strength: str, idp: str | None) -> bool:
    return strength in AuthStrength.ELEVATED or (idp or "") in SSO_IDPS


async def check_new_sign_in(session: AsyncSession, identity_id: uuid.UUID, idp: str, audience: str) -> None:
    """A new session by a sign-in method an organisation of the person does not allow is refused."""
    if audience == "ADMIN":
        return
    eff = await effective_for(session, identity_id)
    if eff.allowed_idps is not None and idp not in eff.allowed_idps:
        raise Forbidden("Your organisation does not allow this way of signing in. Use: "
                        + ", ".join(sorted(eff.allowed_idps)).replace("OIDC", "SSO").replace("SAML", "SSO"),
                        code="SIGN_IN_METHOD_NOT_ALLOWED")


async def violation(session: AsyncSession, sess: Session, now: datetime) -> tuple[str, str] | None:
    """(code, message) when the session being refreshed breaks one of the person's organisations' rules, else None."""
    if sess.audience == "ADMIN":
        return None
    eff = await effective_for(session, sess.identity_id)
    if eff == Effective():
        return None
    if eff.idle_timeout_seconds and (now - sess.created_at).total_seconds() > eff.idle_timeout_seconds:
        return "SESSION_IDLE_TIMEOUT", "You were signed out after a period of inactivity, as your organisation requires."
    if eff.max_session_seconds:
        started = await session.scalar(select(func.min(Session.created_at)).where(Session.family_id == sess.family_id))
        if started and (now - started).total_seconds() > eff.max_session_seconds:
            return "SESSION_MAX_AGE", "Your organisation asks you to sign in again after this long."
    if eff.allowed_idps is not None and (sess.idp or "PASSWORD") not in eff.allowed_idps:
        return "SIGN_IN_METHOD_NOT_ALLOWED", "Your organisation no longer allows this way of signing in; sign in again."
    if eff.require_mfa and not _mfa_ok(sess.auth_strength, sess.idp):
        return "MFA_REQUIRED_BY_ORGANISATION", "Your organisation requires two-step sign-in; sign in again with your code."
    return None
