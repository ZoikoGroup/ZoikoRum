"""Pricing guidance (Request for proposal: budget estimates; Category pages: market rates).

Ranges come only from this platform: proposals buyers accepted, and the indicative rates published professionals set.
They are shown as the middle half of the range (25th to 75th percentile) and only from at least MIN_SAMPLE data points,
so no single professional's or buyer's price can be read from them. With too few points for the specialization the
whole category is used, and with too few there, nothing is shown.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.marketplace import facade as marketplace_facade

MIN_SAMPLE = 5


def _quartiles(values: list[int]) -> dict | None:
    if len(values) < MIN_SAMPLE:
        return None
    v = sorted(values)

    def q(p: float) -> int:
        i = (len(v) - 1) * p
        lo, hi = int(i), min(int(i) + 1, len(v) - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (i - lo))
    return {"low": q(0.25), "typical": q(0.5), "high": q(0.75), "sampleSize": len(v)}


async def estimate(session: AsyncSession, specialization: str, currency: str, engagement_type: str | None = None) -> dict:
    from zoikorum.domains.professional import facade as professional_facade
    from zoikorum.domains.proposal import facade as proposal_facade

    info = (await marketplace_facade.get_specializations(session, [specialization])).get(specialization)
    if info is None:
        return {"specialization": specialization, "currency": currency, "basis": None, "engagements": None, "rates": {}}
    scopes = [("specialization", info.name, [specialization])]
    siblings = await marketplace_facade.category_specializations(session, info.category_slug)
    if siblings:
        scopes.append(("category", info.category_slug.replace("-", " ").title(), siblings))
    for level, name, specs in scopes:
        engagements = _quartiles(await proposal_facade.accepted_values(session, specs, currency, engagement_type))
        rates = {unit: q for unit, values in (await professional_facade.published_rates(session, specs, currency)).items()
                 if (q := _quartiles(values))}
        if engagements or rates:
            return {"specialization": specialization, "currency": currency, "basis": {"level": level, "name": name},
                    "engagements": engagements, "rates": rates, "minimumSample": MIN_SAMPLE}
    return {"specialization": specialization, "currency": currency, "basis": None, "engagements": None, "rates": {}, "minimumSample": MIN_SAMPLE}
