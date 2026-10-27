"""Live policy indicators for engagements, and the policy part of an engagement's evidence pack."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from zoikorum.domains.policy.facade import PolicyAction
from zoikorum.domains.policy.models import ApprovalRequest, ApprovalVote, ExceptionRequest, PolicyEvaluation, PolicyProfile, PolicyVersion

RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
ELIGIBILITY_ACTIONS = (PolicyAction.ENGAGEMENT_ELIGIBILITY, PolicyAction.PROPOSAL_SUBMIT, PolicyAction.PROPOSAL_ACCEPT,
                       PolicyAction.CONTRACT_SIGN)
OPEN_EXCEPTION = ("PENDING", "GRANTED")


async def _subjects(session, contract) -> list[uuid.UUID]:
    from zoikorum.domains.escrow import facade as escrow_facade

    ids = [contract.id, contract.proposal_id, contract.request_id, *(m.id for m in contract.milestones)]
    account = await escrow_facade.account_id_for_contract(session, contract.id)
    return ids + ([account] if account else [])


async def _requests(session, org_id, subject_ids):
    approvals = list((await session.scalars(select(ApprovalRequest).where(
        ApprovalRequest.organization_id == org_id, ApprovalRequest.subject_id.in_(subject_ids)).order_by(ApprovalRequest.created_at))).all())
    exceptions = list((await session.scalars(select(ExceptionRequest).where(
        ExceptionRequest.organization_id == org_id, ExceptionRequest.subject_id.in_(subject_ids)).order_by(ExceptionRequest.created_at))).all())
    return approvals, exceptions


async def _progress(session, request) -> dict:
    """Approval-chain progress: valid grants counted per step, and the role the next open step needs."""
    from zoikorum.domains.policy import service

    votes = await service.valid_votes(session, request)
    done = required = 0
    next_role = None
    for workflow in request.workflows:
        for step in workflow["steps"]:
            have = min(step["count"], sum(v.step_id == step["id"] for v in votes))
            done, required = done + have, required + step["count"]
            if have < step["count"] and next_role is None:
                next_role = step["role"]
    return {"id": request.id, "action": request.action, "subjectType": request.subject_type, "status": request.status,
            "stepsDone": done, "stepsRequired": required, "nextRole": next_role if request.status == "PENDING" else None,
            "deadline": request.deadline}


async def for_contracts(session, org_id, contract_ids) -> dict:
    from zoikorum.domains.contract import facade as contract_facade
    from zoikorum.domains.policy import service

    out = {}
    for contract_id in dict.fromkeys(contract_ids):
        c = await contract_facade.get_contract(session, contract_id)
        if c is None or c.organization_id != org_id:
            continue
        approvals, exceptions = await _requests(session, org_id, await _subjects(session, c))
        version = await session.get(PolicyVersion, c.policy_version_id) if c.policy_version_id else None
        profile = await session.get(PolicyProfile, version.profile_id) if version else None
        level, reasons = (profile.risk_level if profile else "LOW"), []
        if profile:
            reasons.append(f"Policy risk level: {profile.risk_level.lower()}")

        def raise_to(new, why):
            nonlocal level
            reasons.append(why)
            if RISK_RANK[new] > RISK_RANK[level]:
                level = new
        open_exceptions = [x for x in exceptions if x.status in OPEN_EXCEPTION]
        if open_exceptions:
            raise_to("HIGH", "A policy exception is open or in force")
        if any(a.status in ("DENIED", "EXPIRED") for a in approvals):
            raise_to("HIGH", "An approval was denied or timed out")
        if c.status == "DISPUTED":
            raise_to("HIGH", "The engagement is in dispute")
        pending = [a for a in approvals if a.status == "PENDING"]
        if pending:
            raise_to("MEDIUM", "Waiting for approval")
        current = pending[-1] if pending else (approvals[-1] if approvals else None)
        latest = exceptions[-1] if exceptions else None
        out[c.id] = {
            "contractId": c.id, "policyVersion": service.label(profile, version),
            "riskLevel": level, "riskReasons": reasons,
            "exception": {"flag": bool(open_exceptions), "open": sum(x.status == "PENDING" for x in exceptions),
                          "granted": sum(x.status == "GRANTED" for x in exceptions),
                          "latestStatus": latest.status if latest else None,
                          "emergency": any((x.justification or "").startswith("[EMERGENCY]") for x in open_exceptions)},
            "approvals": {"total": len(approvals), "pending": len(pending),
                          "granted": sum(a.status == "GRANTED" for a in approvals),
                          "denied": sum(a.status == "DENIED" for a in approvals),
                          "expired": sum(a.status == "EXPIRED" for a in approvals),
                          "current": await _progress(session, current) if current else None},
        }
    return out


async def record_ids(session, org_id, subject_ids) -> list[str]:
    approvals, exceptions = await _requests(session, org_id, subject_ids)
    return [str(a.id) for a in approvals] + [str(x.id) for x in exceptions]


async def evidence(session, org_id, subject_ids) -> dict:
    from zoikorum.domains.identity import facade as identity

    approvals, exceptions = await _requests(session, org_id, subject_ids)
    votes = list((await session.scalars(select(ApprovalVote).where(
        ApprovalVote.request_id.in_([a.id for a in approvals])).order_by(ApprovalVote.created_at))).all()) if approvals else []
    people = await identity.get_identities(session, list({v.identity_id for v in votes} | {x.decided_by for x in exceptions if x.decided_by}))
    name = lambda i: people[i].display_name if i in people else "Former member"  # noqa: E731
    evaluations = list((await session.scalars(select(PolicyEvaluation).where(
        PolicyEvaluation.organization_id == org_id, PolicyEvaluation.subject_id.in_(subject_ids),
        PolicyEvaluation.action.in_(ELIGIBILITY_ACTIONS), PolicyEvaluation.dry_run.is_(False)).order_by(PolicyEvaluation.created_at))).all())
    return {
        "approvals": [{"id": str(a.id), "action": a.action, "subjectType": a.subject_type, "status": a.status,
                       "requestedAt": a.created_at.isoformat(), "deadline": a.deadline.isoformat(),
                       "reasons": [r.get("message") for r in a.reasons],
                       "votes": [{"by": name(v.identity_id), "role": v.authority_role, "decision": v.decision, "reason": v.reason,
                                  "at": v.created_at.isoformat()} for v in votes if v.request_id == a.id]} for a in approvals],
        "exceptions": [{"id": str(x.id), "action": x.action, "subjectType": x.subject_type, "status": x.status,
                        "emergency": (x.justification or "").startswith("[EMERGENCY]"),
                        "justification": x.justification, "requestedAt": x.created_at.isoformat(), "expiresAt": x.expires_at.isoformat(),
                        "decidedBy": name(x.decided_by) if x.decided_by else None, "decisionReason": x.decision_reason,
                        "decidedAt": x.decided_at.isoformat() if x.decided_at else None,
                        "documents": [d.get("sha256") for d in x.documents]} for x in exceptions],
        "eligibility": [{"at": e.created_at.isoformat(), "action": e.action, "decision": e.decision, "policy": e.policy_version_label,
                         "professionalTier": e.attributes.get("professional.tier"),
                         "dimensions": e.attributes.get("professional.dimensions") or {},
                         "jurisdictions": e.attributes.get("professional.jurisdictions") or [],
                         "licensedJurisdictions": e.attributes.get("professional.licensedJurisdictions") or [],
                         "reasons": [r.get("code") for r in e.reasons], "contextHash": e.context_hash}
                        for e in evaluations],
    }
