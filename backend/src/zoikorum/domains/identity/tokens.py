"""Access/refresh token minting. Only the identity domain mints tokens; the algorithm and key come from
shared/signing_keys.py (HS256 shared secret, or RS256 with rotation and a published JWKS)."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta

import jwt

from zoikorum.config import get_settings
from zoikorum.domains.identity.models import Identity, IdentityLink
from zoikorum.shared import clock, signing_keys
from zoikorum.shared.crypto import sha256_hex


def mint_access_token(
    identity: Identity,
    links: list[IdentityLink],
    *,
    session_id: uuid.UUID,
    auth_strength: str,
    auth_time: datetime,
    audience: str = "APP",
) -> tuple[str, int]:
    s = get_settings()
    now = clock.now()
    orgs: dict[str, list[str]] = {}
    firms: dict[str, list[str]] = {}
    pro: str | None = None
    for link in links:
        if link.link_type == "ORG_MEMBER":
            orgs[str(link.target_id)] = sorted(link.roles)
        elif link.link_type == "FIRM_MEMBER":
            firms[str(link.target_id)] = sorted(link.roles)
        elif link.link_type == "PROFESSIONAL":
            pro = str(link.target_id)
    claims = {
        "iss": s.jwt_issuer,
        "sub": str(identity.id),
        "typ": "access",
        "sid": str(session_id),
        "email": identity.email,
        # Staff roles travel only in tokens from the staff sign-in (admin audience); customer sessions never carry them.
        "roles": identity.live_platform_roles(now) if audience == "ADMIN" else [],
        "adm": audience == "ADMIN",
        "personas": sorted(identity.personas or []),
        "orgs": orgs,
        "firms": firms,
        "pro": pro,
        "amr": auth_strength,
        "auth_time": int(auth_time.timestamp()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=s.access_token_ttl_seconds)).timestamp()),
    }
    return signing_keys.sign(claims), s.access_token_ttl_seconds


def new_refresh_token() -> tuple[str, str]:
    """Returns (opaque token for the client, sha256 hash to store)."""
    token = secrets.token_urlsafe(48)
    return token, sha256_hex(token)


def mint_purpose_token(identity_id: uuid.UUID, purpose: str, ttl_seconds: int, extra: dict | None = None) -> str:
    s = get_settings()
    now = clock.now()
    return signing_keys.sign(
        {
            **(extra or {}),
            "iss": s.jwt_issuer,
            "sub": str(identity_id),
            "typ": purpose,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        },
    )


def read_purpose_claims(token: str, purpose: str) -> dict:
    s = get_settings()
    # Expiry is checked against the domain clock (tests travel in time); "issued at" too, for the same reason.
    claims = signing_keys.decode(token, issuer=s.jwt_issuer, options={"verify_exp": False, "verify_iat": False})
    if claims.get("typ") != purpose:
        raise jwt.InvalidTokenError("wrong token purpose")
    now = clock.now().timestamp()
    if claims.get("exp", 0) < now:
        raise jwt.ExpiredSignatureError("token expired")
    if claims.get("iat", 0) > now + 60:  # issued in the future (beyond a minute of clock skew)
        raise jwt.ImmatureSignatureError("token not yet valid")
    return claims


def read_purpose_token(token: str, purpose: str) -> uuid.UUID:
    return uuid.UUID(read_purpose_claims(token, purpose)["sub"])
