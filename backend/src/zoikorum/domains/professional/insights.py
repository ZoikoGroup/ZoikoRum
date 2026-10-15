"""Own performance insights (Professional Dashboard): how buyers experience working with you, from platform records only.

Only the professional sees these. Each rate comes with the counts behind it and a plain hint, and a rate is left empty
until there are enough records for it to mean something.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.professional.service import _mine
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor

MIN_SAMPLE = 3  # below this a percentage says more about chance than about the work


def _rate(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole >= MIN_SAMPLE else None


async def mine(session: AsyncSession, actor: Actor) -> dict:
    from zoikorum.domains.contract import facade as contract_facade
    from zoikorum.domains.dispute import facade as dispute_facade
    from zoikorum.domains.proposal import facade as proposal_facade
    from zoikorum.domains.review import facade as review_facade

    pro = await _mine(session, actor)
    response = await proposal_facade.response_stats(session, pro.id)
    wins = await proposal_facade.win_stats(session, pro.id)
    recent = await proposal_facade.win_stats(session, pro.id, since=clock.now() - timedelta(days=90))
    delivery = await contract_facade.delivery_stats(session, pro.id)
    first_pass = await contract_facade.first_pass_stats(session, pro.id)
    disputes = await dispute_facade.opened_against(session, pro.id)
    outcomes = await dispute_facade.outcome_stats(session, pro.id)
    ratings = await review_facade.rating_stats(session, pro.id)
    from zoikorum.domains.analytics import facade as analytics_facade
    views = await analytics_facade.profile_views(session, pro.id, clock.now() - timedelta(days=30))

    metrics = [
        {"key": "responseRate", "label": "Requests answered", "value": _rate(response["responded"], response["requests"]),
         "basis": f"{response['responded']} of {response['requests']} requests",
         "hint": "Answer every request, even with a decline: buyers see your response time on your profile."},
        {"key": "acceptanceRate", "label": "Proposals accepted", "value": _rate(wins["accepted"], wins["submitted"]),
         "basis": f"{wins['accepted']} of {wins['submitted']} proposals ({recent['accepted']} of {recent['submitted']} in the last 90 days)",
         "hint": "Proposals that restate the objective and price each deliverable are accepted more often."},
        {"key": "onTimeRate", "label": "Milestones delivered on time", "value": _rate(delivery["onTime"], delivery["milestonesWithDueDate"]),
         "basis": f"{delivery['onTime']} of {delivery['milestonesWithDueDate']} milestones with a due date",
         "hint": "If a date will slip, agree a change order before it does: late delivery counts against your trust signals."},
        {"key": "firstPassRate", "label": "Accepted without revisions", "value": _rate(first_pass["firstPass"], first_pass["accepted"]),
         "basis": f"{first_pass['firstPass']} of {first_pass['accepted']} accepted milestones",
         "hint": "Confirm acceptance criteria at kick-off to avoid revision rounds."},
        {"key": "disputeRate", "label": "Engagements with a dispute", "value": _rate(disputes, delivery["engagements"]),
         "basis": f"{disputes} of {delivery['engagements']} engagements"
                  + (f"; {outcomes['adverseOutcomes']} decided against you" if outcomes["adverseOutcomes"] else ""),
         "hint": "Lower is better. Raise problems early in the engagement conversation, where they are on record.", "lowerIsBetter": True},
    ]
    return {"professionalId": pro.id, "generatedAt": clock.now(), "minimumSample": MIN_SAMPLE, "metrics": metrics,
            "medianResponseHours": response["medianHours"], "completedEngagements": delivery["completed"],
            "averageRating": ratings["averageRating"], "reviewCount": ratings["reviewCount"], "profileViews30d": views}
