"""Advisory sign-in risk signals (Handbook: account takeover and bot detection, without an outside captcha).

Each new sign-in (not a refresh or step-up) is compared with the account's recent sign-ins:
* VELOCITY - more than ZK_SIGN_IN_VELOCITY_PER_HOUR sign-ins to the account in the last hour;
* MANY_ACCOUNTS_ONE_ADDRESS - one client address signing in to more than five accounts in an hour (credential stuffing);
* NEW_DEVICE - a browser/device not seen on the account before;
* NEW_COUNTRY - a country not seen on the account before;
* IMPOSSIBLE_TRAVEL - the distance from the previous sign-in's location could not be covered in the time between them
  at ZK_SIGN_IN_MAX_TRAVEL_KMH.

Location comes from the load balancer's headers (X-Client-Geo-Country, X-Client-Geo-Lat-Long; see the Terraform backend
service), at city level. The client address is stored only as a keyed hash. Signals are advisory: they never block a
sign-in. MEDIUM and HIGH are written to the audit trail; the person sees their own sign-ins with signals, and staff
see an account's.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.identity.models import SignInSignal
from zoikorum.shared import clock
from zoikorum.shared.events import record_audit

HISTORY = 50
SHARED_ADDRESS_ACCOUNTS = 5


@dataclass(frozen=True)
class ClientHints:
    ip: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None


_hints: ContextVar[ClientHints | None] = ContextVar("zk_sign_in_hints", default=None)


def _lat_long(value: str | None) -> tuple[float | None, float | None]:
    try:
        lat, lon = (float(x) for x in (value or "").split(",", 1))
    except ValueError:
        return None, None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0.0, 0.0) else (None, None)


async def bind_request(request: Request) -> None:
    """Router dependency: keeps the caller's address and location for the sign-in handled by this request."""
    country = (request.headers.get("X-Client-Geo-Country") or "").strip().upper()[:2] or None
    lat, lon = _lat_long(request.headers.get("X-Client-Geo-Lat-Long"))
    _hints.set(ClientHints(request.client.host if request.client else None, country if country and country.isalpha() else None, lat, lon))


def set_hints(hints: ClientHints | None) -> None:
    _hints.set(hints)


def _ip_hash(ip: str | None) -> str | None:
    if not ip:
        return None
    return hmac.new(get_settings().field_encryption_key.encode(), ip.encode(), hashlib.sha256).hexdigest()


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance (haversine)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def grade(signals: list[str]) -> str:
    if "IMPOSSIBLE_TRAVEL" in signals or {"VELOCITY", "NEW_DEVICE"} <= set(signals) or "MANY_ACCOUNTS_ONE_ADDRESS" in signals:
        return "HIGH"
    return "MEDIUM" if signals else "LOW"


async def assess(session: AsyncSession, identity_id: uuid.UUID, session_id: uuid.UUID | None, device: str) -> SignInSignal:
    s = get_settings()
    now = clock.now()
    hints = _hints.get() or ClientHints()
    ip_hash = _ip_hash(hints.ip)
    previous = (await session.scalars(select(SignInSignal).where(SignInSignal.identity_id == identity_id)
                                      .order_by(SignInSignal.created_at.desc()).limit(HISTORY))).all()
    signals: list[str] = []
    if sum(1 for p in previous if p.created_at > now - timedelta(hours=1)) >= s.sign_in_velocity_per_hour:
        signals.append("VELOCITY")
    if ip_hash:
        accounts = await session.scalar(select(func.count(func.distinct(SignInSignal.identity_id))).where(
            SignInSignal.ip_hash == ip_hash, SignInSignal.created_at > now - timedelta(hours=1),
            SignInSignal.identity_id != identity_id))
        if (accounts or 0) >= SHARED_ADDRESS_ACCOUNTS:
            signals.append("MANY_ACCOUNTS_ONE_ADDRESS")
    if previous and device not in {p.device for p in previous}:
        signals.append("NEW_DEVICE")
    if previous and hints.country and hints.country not in {p.country for p in previous if p.country}:
        if any(p.country for p in previous):
            signals.append("NEW_COUNTRY")
    last = next((p for p in previous if p.latitude is not None and p.longitude is not None), None)
    if last and hints.lat is not None and hints.lon is not None:
        km = distance_km((last.latitude, last.longitude), (hints.lat, hints.lon))
        hours = max((now - last.created_at).total_seconds() / 3600, 1 / 60)
        if km > 100 and km / hours > s.sign_in_max_travel_kmh:
            signals.append("IMPOSSIBLE_TRAVEL")
    row = SignInSignal(identity_id=identity_id, session_id=session_id, ip_hash=ip_hash, country=hints.country, latitude=hints.lat,
                       longitude=hints.lon, device=device[:100], signals=signals, risk=grade(signals))
    session.add(row)
    await session.flush()
    if row.risk != "LOW":
        record_audit(session, "identity.sign_in.risk_signal", object_type="Identity", object_id=identity_id,
                     details={"risk": row.risk, "signals": signals, "country": hints.country, "device": row.device})
    return row


def signal_out(r: SignInSignal) -> dict:
    return {"id": r.id, "at": r.created_at, "device": r.device, "country": r.country, "signals": list(r.signals), "risk": r.risk}


async def recent(session: AsyncSession, identity_id: uuid.UUID, limit: int = 20) -> list[dict]:
    rows = (await session.scalars(select(SignInSignal).where(SignInSignal.identity_id == identity_id)
                                  .order_by(SignInSignal.created_at.desc()).limit(limit))).all()
    return [signal_out(r) for r in rows]
