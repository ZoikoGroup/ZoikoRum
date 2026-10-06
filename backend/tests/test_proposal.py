"""Step 6: buyer requests -> professional proposals -> buyer decision (RFP wireframe, BUILD_SPEC s.proposal)."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from test_search import publish, verify_identity
from zoikorum.shared import clock

R = "/v1/proposal-requests"
P = "/v1/proposals"


def _day(n: int) -> str:
    return (clock.now().date() + timedelta(days=n)).isoformat()


async def tier_b(client, make_user, drain, name):
    u, pro = await publish(client, make_user, drain, name, headline="Tax adviser", primary="transfer-pricing")
    await verify_identity(client, make_user, drain, u, pro)
    return u, pro


async def buyer_org(client, make_user, drain, name="bea"):
    b = await make_user(name)
    await drain()
    await b.refresh()
    org = (await client.get("/v1/organizations/mine", headers=b.h)).json()[0]
    return b, org


def request_body(org, *pros, **over):
    body = {"organizationId": org["id"], "professionalIds": [p["id"] for p in pros], "service": "Transfer pricing review",
            "engagementType": "PROJECT", "objective": "Prepare transfer pricing documentation for FY2026",
            "details": "Two subsidiaries; intercompany services.", "desiredStartDate": _day(10),
            "estimatedDuration": "THREE_SIX_WEEKS", "budget": {"maxMinor": 2_000_000, "currency": "USD"},
            "acknowledged": True}
    return {**body, **over}


def proposal_body(total=1_500_000, **over):
    body = {"summary": "I will prepare the master and local files.", "scopeAlignment": "CONFIRMED",
            "deliverables": [{"key": "master", "title": "Master file", "acceptanceCriteria": "OECD-compliant master file"},
                             {"key": "local", "title": "Local file", "acceptanceCriteria": "Local file for each subsidiary"}],
            "milestones": [{"title": "Master file", "amountMinor": total - 500_000, "deliverableKeys": ["master"]},
                           {"title": "Local files", "amountMinor": 500_000, "deliverableKeys": ["local"]}],
            "pricingModel": "FIXED", "currency": "USD", "startDate": _day(10), "endDate": _day(40), "validUntil": _day(14),
            "assumptions": ["Trial balances provided by week 1"], "exclusions": ["Tax filings"]}
    return {**body, **over}


async def test_request_proposal_accept_happy_path(client, make_user, drain, sf):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)

    r = await client.post(R, headers=buyer.idem(), json=request_body(org, pro))
    assert r.status_code == 201, r.text
    req = r.json()[0]
    assert req["status"] == "OPEN" and req["professional"]["tier"] == "B" and req["groupSize"] == 1

    # The professional sees it in their inbox and answers with a structured proposal.
    inbox = (await client.get(R, headers=pro_user.h, params={"role": "professional"})).json()["items"]
    assert [i["id"] for i in inbox] == [req["id"]] and inbox[0]["viewerRole"] == "PROFESSIONAL"
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    assert p["status"] == "DRAFT" and p["total"] == {"amountMinor": 1_500_000, "currency": "USD"} and p["currency"] == "USD"
    assert (await client.get(f"{P}/{p['id']}", headers=buyer.h)).status_code == 404  # buyers never see drafts

    r = await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    assert r.status_code == 200 and r.json()["status"] == "SUBMITTED"
    deltas = {d["field"]: d["status"] for d in r.json()["deltas"]}
    assert deltas["price"] == "WITHIN" and deltas["startDate"] == "MATCH" and deltas["duration"] == "WITHIN"

    # Buyer asks for a change, the professional revises, the buyer accepts.
    r = await client.post(f"{P}/{p['id']}/request-revision", headers=buyer.h,
                          json={"changes": [{"field": "price", "requested": "Can the local files be cheaper?"}]})
    assert r.json()["status"] == "REVISION_REQUESTED" and r.json()["revisionCount"] == 1
    r = await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    assert r.status_code == 409 and r.json()["code"] == "REVISION_PENDING"
    await client.patch(f"{P}/{p['id']}", headers=pro_user.h, json=proposal_body(total=1_400_000))
    assert (await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())).json()["status"] == "SUBMITTED"

    key = buyer.idem()
    r = await client.post(f"{P}/{p['id']}/accept", headers=key)
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert accepted["status"] == "ACCEPTED" and len(accepted["termsHash"]) == 64
    replay = await client.post(f"{P}/{p['id']}/accept", headers=key)
    assert replay.headers.get("Idempotent-Replayed") == "true" and replay.json()["id"] == p["id"]

    assert (await client.get(f"{R}/{req['id']}", headers=buyer.h)).json()["status"] == "CLOSED"
    async with sf() as s:
        events = (await s.scalars(text("SELECT event_type FROM platform.outbox WHERE aggregate_id IN (:r, :p) ORDER BY seq"),
                                  {"r": req["id"], "p": p["id"]})).all()
        payload = await s.scalar(text("SELECT envelope->'payload' FROM platform.outbox WHERE event_type LIKE '%proposal.accepted%' "
                                      "AND aggregate_id = :p"), {"p": p["id"]})
    assert [e.split(".")[-2] for e in events] == ["created", "submitted", "revision_requested", "revised", "accepted"]
    assert payload["totalMinor"] == 1_400_000 and payload["termsHash"] == accepted["termsHash"]
    assert [m["sequence"] for m in payload["terms"]["milestones"]] == [1, 2]

    summary = (await client.get(f"{R}/summary", headers=buyer.h)).json()
    assert summary["requests"] == {"CLOSED": 1} and summary["proposals"] == {"ACCEPTED": 1}


async def test_compare_up_to_three_and_accepting_one_closes_the_rest(client, make_user, drain):
    a_user, a = await tier_b(client, make_user, drain, "ann")
    b_user, b = await tier_b(client, make_user, drain, "ben")
    buyer, org = await buyer_org(client, make_user, drain)
    reqs = (await client.post(R, headers=buyer.idem(), json=request_body(org, a, b))).json()
    assert len(reqs) == 2 and reqs[0]["groupId"] == reqs[1]["groupId"] and reqs[0]["groupSize"] == 2

    by_pro = {r["professional"]["id"]: r for r in reqs}
    pa = (await client.post(f"{R}/{by_pro[a['id']]['id']}/proposals", headers=a_user.h, json=proposal_body())).json()
    await client.post(f"{P}/{pa['id']}/submit", headers=a_user.idem())
    pb = (await client.post(f"{R}/{by_pro[b['id']]['id']}/proposals", headers=b_user.h, json=proposal_body(total=2_500_000))).json()
    await client.post(f"{P}/{pb['id']}/submit", headers=b_user.idem())

    # One comparison view across both professionals; B is over budget.
    both = (await client.get(f"{R}/{reqs[0]['id']}/proposals", headers=buyer.h)).json()
    assert {x["professional"]["displayName"] for x in both} == {"Ann", "Ben"}
    assert next(x for x in both if x["id"] == pb["id"])["deltas"][0]["status"] == "ABOVE"
    # A professional only ever sees their own proposal.
    assert [x["id"] for x in (await client.get(f"{R}/{by_pro[a['id']]['id']}/proposals", headers=a_user.h)).json()] == [pa["id"]]

    assert (await client.post(f"{P}/{pa['id']}/accept", headers=buyer.idem())).json()["status"] == "ACCEPTED"
    assert (await client.get(f"{P}/{pb['id']}", headers=b_user.h)).json()["reasonCode"] == "ANOTHER_PROPOSAL_ACCEPTED"
    assert (await client.get(f"{R}/{by_pro[b['id']]['id']}", headers=b_user.h)).json()["status"] == "CLOSED"


async def test_eligibility_rules(client, make_user, drain, sf):
    c_user, c = await publish(client, make_user, drain, "cara", headline="Bookkeeper", primary="transfer-pricing")  # Tier C
    buyer, org = await buyer_org(client, make_user, drain)

    # Tier C can be asked, but cannot send a proposal until verified.
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, c))).json()[0]
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=c_user.h, json=proposal_body())).json()
    r = await client.post(f"{P}/{p['id']}/submit", headers=c_user.idem())
    assert r.status_code == 403 and r.json()["code"] == "POLICY_BLOCKED_MINIMUM_TRUST_TIER"

    # Acknowledgement, start date and requester role are enforced; self-requests are refused.
    bad = await client.post(R, headers=buyer.idem(), json=request_body(org, c, acknowledged=False))
    assert bad.status_code == 422 and bad.json()["code"] == "ACKNOWLEDGEMENT_REQUIRED"
    bad = await client.post(R, headers=buyer.idem(), json=request_body(org, c, desiredStartDate=_day(-1)))
    assert bad.json()["code"] == "START_DATE_IN_PAST"
    assert (await client.post(R, headers=buyer.h, json=request_body(org, c))).json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    stranger = await make_user("sam")
    assert (await client.post(R, headers=stranger.idem(), json=request_body(org, c))).status_code == 404
    assert (await client.get(f"{R}/{req['id']}", headers=stranger.h)).status_code == 404

    # Restricted professionals cannot be engaged.
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE trust.profiles SET dimensions = dimensions || '{\"restrictions\": \"FLAGGED\"}' "
                             "WHERE professional_id = :p"), {"p": c["id"]})
    r = await client.post(R, headers=buyer.idem(), json=request_body(org, c))
    assert r.status_code == 403 and r.json()["code"] == "POLICY_BLOCKED_RESTRICTIONS"


async def test_spend_limit_blocks_acceptance(client, make_user, drain, sf):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE buyer.members SET spend_limit_minor = 1000000, spend_limit_currency = 'USD' "
                             "WHERE organization_id = :o AND identity_id = :i"), {"o": org["id"], "i": buyer.id})
    r = await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    assert r.status_code == 403 and r.json()["code"] == "SPEND_LIMIT_EXCEEDED"


async def test_nda_hides_details_until_accepted(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro, ndaRequired=True))).json()[0]
    seen = (await client.get(f"{R}/{req['id']}", headers=pro_user.h)).json()
    assert seen["detailsHidden"] and seen["objective"] is None and seen["details"] is None
    r = await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())
    assert r.status_code == 403 and r.json()["code"] == "NDA_NOT_ACCEPTED"
    seen = (await client.post(f"{R}/{req['id']}/accept-nda", headers=pro_user.h)).json()
    assert not seen["detailsHidden"] and seen["objective"].startswith("Prepare transfer pricing")
    assert (await client.get(f"{R}/{req['id']}", headers=buyer.h)).json()["objective"]  # the buyer always sees it


async def test_decline_draft_send_cancel_and_validation(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)

    # Drafts are invisible to the professional until sent.
    draft = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro, draft=True, acknowledged=False))).json()[0]
    assert draft["status"] == "DRAFT"
    assert (await client.get(f"{R}/{draft['id']}", headers=pro_user.h)).status_code == 404
    assert (await client.post(f"{R}/{draft['id']}/send", headers=buyer.idem(), json={})).json()["code"] == "ACKNOWLEDGEMENT_REQUIRED"
    sent = (await client.post(f"{R}/{draft['id']}/send", headers=buyer.idem(), json={"acknowledged": True})).json()
    assert sent[0]["status"] == "OPEN"

    r = await client.post(f"{R}/{draft['id']}/decline", headers=pro_user.h, json={"reasonCode": "NO_CAPACITY", "note": "Fully booked"})
    assert r.json()["status"] == "DECLINED" and r.json()["reasonCode"] == "NO_CAPACITY"
    assert (await client.post(f"{R}/{draft['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()["code"] == "REQUEST_NOT_OPEN"

    # Buyer cancels an open request.
    other = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]
    assert (await client.post(f"{R}/{other['id']}/cancel", headers=buyer.h, json={})).json()["status"] == "CANCELLED"

    # Proposal validation: milestones must sum to the total and map to real deliverables; incomplete drafts cannot be sent.
    third = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]
    bad = await client.post(f"{R}/{third['id']}/proposals", headers=pro_user.h,
                            json=proposal_body() | {"total": {"amountMinor": 1, "currency": "USD"}})
    assert bad.status_code == 422
    bad = proposal_body()
    bad["milestones"][0]["deliverableKeys"] = ["nope"]
    assert (await client.post(f"{R}/{third['id']}/proposals", headers=pro_user.h, json=bad)).status_code == 422
    p = (await client.post(f"{R}/{third['id']}/proposals", headers=pro_user.h,
                           json={"currency": "USD", "summary": "Draft"})).json()
    r = await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    assert r.status_code == 422 and r.json()["code"] == "PROPOSAL_INCOMPLETE"


async def test_proposals_expire_after_their_validity_date(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body(validUntil=_day(2)))).json()
    await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())

    clock.advance(timedelta(days=4))
    await drain()
    got = (await client.get(f"{P}/{p['id']}", headers=buyer.h)).json()
    assert got["status"] == "EXPIRED" and got["expired"]
    r = await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    assert r.status_code == 409
    assert (await client.get(f"{R}/{req['id']}", headers=buyer.h)).json()["status"] == "CLOSED"
    assert date.fromisoformat(got["validUntil"]) < clock.now().date()
