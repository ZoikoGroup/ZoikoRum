"""Contract facade - CONTRACT. Signatures and DTOs are fixed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.contract.models import Contract, Milestone


@dataclass(frozen=True)
class MilestoneSummary:
    id: uuid.UUID
    contract_id: uuid.UUID
    sequence: int
    title: str
    amount_minor: int
    currency: str
    status: str  # PENDING_FUNDING|IN_PROGRESS|SUBMITTED|REVISION_REQUESTED|ACCEPTANCE_PENDING_APPROVAL|ACCEPTED|DISPUTED|CANCELLED
    due_date: date | None
    accepted_at: datetime | None
    accepted_release_minor: int | None = None


@dataclass(frozen=True)
class ContractSummary:
    id: uuid.UUID
    proposal_id: uuid.UUID
    request_id: uuid.UUID
    organization_id: uuid.UUID
    buyer_identity_id: uuid.UUID
    professional_id: uuid.UUID
    status: str  # GENERATED|PENDING_SIGNATURE|ACTIVE|COMPLETED|TERMINATED|DISPUTED
    currency: str
    total_minor: int
    terms_hash: str
    contract_version: int
    policy_version_id: uuid.UUID | None
    milestones: tuple[MilestoneSummary, ...]
    reference: str = ""  # human reference, e.g. ZK-ENG-1A2B3C4D
    buyer_legal_entity: dict | None = None  # snapshot at acceptance: legalName, registrationNumber, country, ...


def _milestone(m: Milestone) -> MilestoneSummary:
    return MilestoneSummary(m.id, m.contract_id, m.sequence, m.title, m.amount_minor, m.currency, m.status, m.due_date, m.accepted_at, m.accepted_release_minor)


async def _summary(session: AsyncSession, c: Contract | None) -> ContractSummary | None:
    if c is None:
        return None
    ms = (await session.scalars(select(Milestone).where(Milestone.contract_id == c.id).order_by(Milestone.sequence))).all()
    return ContractSummary(c.id, c.proposal_id, c.request_id, c.organization_id, c.buyer_identity_id, c.professional_id, c.status,
                           c.currency, c.total_minor, c.terms_hash, c.contract_version, c.policy_version_id, tuple(_milestone(m) for m in ms),
                           c.reference, (c.parties or {}).get("buyer", {}).get("legalEntity"))


async def get_contract(session: AsyncSession, contract_id: uuid.UUID) -> ContractSummary | None:
    return await _summary(session, await session.get(Contract, contract_id))


async def get_contract_by_request(session: AsyncSession, request_id: uuid.UUID) -> ContractSummary | None:
    return await _summary(session, await session.scalar(select(Contract).where(Contract.request_id == request_id)))


async def get_contract_by_proposal(session: AsyncSession, proposal_id: uuid.UUID) -> ContractSummary | None:
    return await _summary(session, await session.scalar(select(Contract).where(Contract.proposal_id == proposal_id)))


async def get_milestone(session: AsyncSession, milestone_id: uuid.UUID) -> MilestoneSummary | None:
    m = await session.get(Milestone, milestone_id)
    return _milestone(m) if m else None


async def milestone_acceptor(session: AsyncSession, milestone_id: uuid.UUID) -> uuid.UUID | None:
    milestone = await session.get(Milestone, milestone_id)
    return milestone.accepted_by if milestone else None


async def policy_controls(session: AsyncSession, contract_id: uuid.UUID) -> dict:
    contract = await session.get(Contract, contract_id)
    return dict(contract.terms.get("policySettings", {})) if contract else {}


async def assistance_terms(session: AsyncSession, contract_id: uuid.UUID) -> dict | None:
    c = await session.get(Contract, contract_id)
    return {"reference": c.reference, "terms": c.terms, "documentHash": c.terms_hash, "version": c.contract_version} if c else None


async def active_contract_ids(session: AsyncSession, professional_id: uuid.UUID) -> list[uuid.UUID]:
    return list((await session.scalars(select(Contract.id).where(Contract.professional_id == professional_id,
        Contract.status.in_(("ACTIVE", "DISPUTED"))))).all())


async def delivery_stats(session: AsyncSession, professional_id: uuid.UUID) -> dict[str, int]:
    """Platform history for a professional's public profile: completed engagements and on-time milestone delivery."""
    from sqlalchemy import func

    from zoikorum.shared import clock
    from zoikorum.config import get_settings
    completed_dates = (await session.scalars(select(Contract.completed_at).where(
        Contract.professional_id == professional_id, Contract.status == "COMPLETED"))).all()
    completed = len(completed_dates)
    weighted_completed = sum(0.5 ** (max(0, (clock.now() - d).total_seconds()) / 86400 / get_settings().trust_completion_half_life_days) for d in completed_dates if d)
    engagements = await session.scalar(select(func.count()).select_from(Contract).where(Contract.professional_id == professional_id, Contract.activated_at.is_not(None))) or 0
    rows = (await session.execute(select(Milestone.submitted_at, Milestone.due_date).join(Contract, Contract.id == Milestone.contract_id).where(
        Contract.professional_id == professional_id, Milestone.status == "ACCEPTED", Milestone.due_date.is_not(None)))).all()
    on_time = sum(1 for submitted, due in rows if submitted is not None and submitted.date() <= due)
    return {"completed": completed, "weightedCompleted": weighted_completed, "engagements": engagements, "milestonesWithDueDate": len(rows), "onTime": on_time}


async def contract_counts(session: AsyncSession, professional_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Per professional: contracts awaiting signature, active (incl. disputed) and completed."""
    from sqlalchemy import func

    if not professional_ids:
        return {}
    groups = {"GENERATED": "awaitingSignature", "PENDING_SIGNATURE": "awaitingSignature", "ACTIVE": "active",
              "DISPUTED": "active", "COMPLETED": "completed"}
    out: dict[uuid.UUID, dict[str, int]] = {}
    for pid, status, n in (await session.execute(select(Contract.professional_id, Contract.status, func.count())
                                                 .where(Contract.professional_id.in_(professional_ids))
                                                 .group_by(Contract.professional_id, Contract.status))).all():
        if status in groups:
            counts = out.setdefault(pid, {"awaitingSignature": 0, "active": 0, "completed": 0})
            counts[groups[status]] += n
    return out


async def engagements_by_organization(session: AsyncSession, professional_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """Per buyer organisation: engagements with this professional, how many completed, last activity (saved buyers)."""
    from sqlalchemy import func

    rows = (await session.execute(select(
        Contract.organization_id, func.count(), func.count().filter(Contract.status == "COMPLETED"), func.max(Contract.updated_at))
        .where(Contract.professional_id == professional_id).group_by(Contract.organization_id))).all()
    return {org: {"engagements": n, "completed": done, "lastEngagementAt": last} for org, n, done, last in rows}


async def disputed_between(session: AsyncSession, professional_id: uuid.UUID, organization_ids: list[uuid.UUID]) -> bool:
    """Is any engagement between this professional and one of these organisations in a dispute right now?"""
    if not organization_ids:
        return False
    return bool(await session.scalar(select(Contract.id).where(
        Contract.professional_id == professional_id, Contract.organization_id.in_(organization_ids),
        Contract.status == "DISPUTED").limit(1)))


async def retainer_paused(session: AsyncSession, contract_id: uuid.UUID) -> bool:
    c = await session.get(Contract, contract_id)
    return bool(c and c.paused_at)


async def first_pass_stats(session: AsyncSession, professional_id: uuid.UUID) -> dict[str, int]:
    """Accepted milestones and how many were accepted without a revision request (own performance insights)."""
    from sqlalchemy import func

    total, first = (await session.execute(select(func.count(), func.count().filter(Milestone.revision_count == 0))
        .select_from(Milestone).join(Contract, Contract.id == Milestone.contract_id)
        .where(Contract.professional_id == professional_id, Milestone.status == "ACCEPTED"))).one()
    return {"accepted": total or 0, "firstPass": first or 0}


async def activity_kpis(session: AsyncSession, since, until) -> dict:
    """Engagements started and completed in the period, buyers and professionals active, engagements running now."""
    from sqlalchemy import distinct, func

    started = (await session.execute(select(func.count(), func.count(distinct(Contract.organization_id)),
                                            func.count(distinct(Contract.professional_id))).where(
        Contract.activated_at >= since, Contract.activated_at < until))).one()
    completed = await session.scalar(select(func.count()).select_from(Contract).where(
        Contract.completed_at >= since, Contract.completed_at < until)) or 0
    running = await session.scalar(select(func.count()).select_from(Contract).where(Contract.status.in_(("ACTIVE", "DISPUTED")))) or 0
    return {"engagementsStarted": started[0], "activeBuyerOrganisations": started[1], "activeProfessionals": started[2],
            "engagementsCompleted": completed, "runningNow": running}


async def is_retainer(session: AsyncSession, contract_id: uuid.UUID) -> bool:
    c = await session.get(Contract, contract_id)
    return bool(c) and "RETAINER" in (c.engagement_type, c.pricing_model)


async def upcoming_dates(session: AsyncSession, org_ids: list[uuid.UUID], professional_id: uuid.UUID | None, days: int = 180) -> list[dict]:
    """Dated milestones still open and contracts waiting for signature, for a person's calendar feed."""
    from datetime import timedelta

    from sqlalchemy import or_

    from zoikorum.shared import clock

    who = []
    if org_ids:
        who.append(Contract.organization_id.in_(org_ids))
    if professional_id:
        who.append(Contract.professional_id == professional_id)
    if not who:
        return []
    today = clock.now().date()
    out = []
    rows = (await session.execute(select(Milestone, Contract).join(Contract, Contract.id == Milestone.contract_id).where(
        or_(*who), Contract.status.in_(("ACTIVE", "PENDING_SIGNATURE", "DISPUTED")), Milestone.due_date.is_not(None),
        Milestone.due_date >= today - timedelta(days=30), Milestone.due_date <= today + timedelta(days=days),
        Milestone.status.not_in(("ACCEPTED", "CANCELLED"))))).all()
    for m, c in rows:
        side = "professional" if professional_id and c.professional_id == professional_id else "buyer"
        path = f"/app/professional/engagements/{c.id}" if side == "professional" else f"/app/engagements/{c.id}"
        out.append({"uid": f"milestone-{m.id}", "date": m.due_date, "title": f"Due: M{m.sequence} {m.title} ({c.reference})",
                    "detail": f"Milestone due on engagement {c.reference}.", "path": path})
    for c in (await session.scalars(select(Contract).where(or_(*who), Contract.status == "PENDING_SIGNATURE"))).all():
        side = "professional" if professional_id and c.professional_id == professional_id else "buyer"
        path = f"/app/professional/engagements/{c.id}" if side == "professional" else f"/app/engagements/{c.id}"
        out.append({"uid": f"sign-{c.id}-{c.contract_version}", "date": c.signature_deadline.date(), "title": f"Sign by: {c.reference}",
                    "detail": "The contract must be signed by both parties by this date.", "path": path})
    return sorted(out, key=lambda x: x["date"])


# ---- Staff admin console ------------------------------------------------------------------------------------------

async def counts_by_party(session: AsyncSession, organization_ids: list[uuid.UUID],
                          firm_ids: list[uuid.UUID]) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    """Contracts (any status) per buyer organisation, and per firm the professional practised under."""
    from sqlalchemy import func

    by_org = dict((await session.execute(select(Contract.organization_id, func.count()).where(
        Contract.organization_id.in_(organization_ids)).group_by(Contract.organization_id))).all()) if organization_ids else {}
    by_firm = dict((await session.execute(select(Contract.firm_id, func.count()).where(
        Contract.firm_id.in_(firm_ids)).group_by(Contract.firm_id))).all()) if firm_ids else {}
    return by_org, by_firm


async def engagement_counts(session: AsyncSession, professional_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Per professional: engagements running now (active or disputed) and every engagement that ever started."""
    from sqlalchemy import func

    if not professional_ids:
        return {}
    rows = (await session.execute(select(
        Contract.professional_id, func.count().filter(Contract.status.in_(("ACTIVE", "DISPUTED"))),
        func.count().filter(Contract.activated_at.is_not(None)))
        .where(Contract.professional_id.in_(professional_ids)).group_by(Contract.professional_id))).all()
    return {pid: {"active": active, "lifetime": lifetime} for pid, active, lifetime in rows}


async def titles(session: AsyncSession, contract_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not contract_ids:
        return {}
    return dict((await session.execute(select(Contract.id, Contract.title).where(Contract.id.in_(contract_ids)))).all())


# ---- Staff console search (admin/search.py) --------------------------------------------------------------------------

async def staff_search_contracts(session: AsyncSession, term: str, exact_id: uuid.UUID | None, limit: int) -> list[dict]:
    """Contracts whose title or reference contains ``term`` (or whose id is ``exact_id``), newest first:
    [{"id", "title", "reference", "status"}]."""
    from sqlalchemy import func, or_

    like = "%" + term.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    match = [func.lower(Contract.title).like(like, escape="\\"), func.lower(Contract.reference).like(like, escape="\\")]
    if exact_id:
        match.append(Contract.id == exact_id)
    rows = (await session.scalars(select(Contract).where(or_(*match)).order_by(Contract.created_at.desc(), Contract.id).limit(limit))).all()
    return [{"id": c.id, "title": c.title, "reference": c.reference, "status": c.status} for c in rows]


async def acceptance_kpis(session: AsyncSession, since, until) -> dict:
    """Milestones accepted in the period and the time from the (last) submission to acceptance (Payments & Escrow:
    acceptance latency, which is what releases payment)."""
    from sqlalchemy import func

    hours = func.extract("epoch", Milestone.accepted_at - Milestone.submitted_at) / 3600
    n, med, p90 = (await session.execute(select(func.count(), func.percentile_cont(0.5).within_group(hours),
                                                func.percentile_cont(0.9).within_group(hours)).where(
        Milestone.accepted_at >= since, Milestone.accepted_at < until, Milestone.submitted_at.is_not(None)))).one()
    return {"milestonesAccepted": n or 0, "medianHoursSubmitToAccept": round(float(med), 1) if med is not None else None,
            "p90HoursSubmitToAccept": round(float(p90), 1) if p90 is not None else None}
