"""Incident register: open, contain, resolve, close; serious incidents need a root cause, done remediation and a review."""

from __future__ import annotations

from test_dispute import staff

I = "/v1/admin/incidents"


async def test_a_serious_incident_closes_only_after_root_cause_remediation_and_review(client, make_user, drain):
    ops = await staff(make_user, "ops", "FINANCIAL_OPS")
    lead = await staff(make_user, "lead", "RISK_LEAD")
    customer = await make_user("cust")
    assert (await client.post(I, headers=customer.h, json={"title": "x" * 5, "kind": "OTHER", "severity": "SEV4", "summary": "y" * 10})).status_code == 403
    r = await client.post(I, headers=ops.h, json={"title": "Payouts failing", "kind": "PAYMENTS", "severity": "SEV2",
                                                  "summary": "All payouts since 09:00 return a provider error."})
    assert r.status_code == 201 and r.json()["reference"].startswith("ZK-INC-") and r.json()["status"] == "OPEN"
    iid = r.json()["id"]
    url = f"{I}/{iid}"
    assert (await client.patch(url, headers=ops.h, json={"advanceTo": "RESOLVED"})).json()["code"] == "INVALID_STEP"
    await client.patch(url, headers=ops.h, json={"advanceTo": "CONTAINED", "note": "Payouts paused via switches.",
                                                 "notified": [{"party": "Professionals affected", "note": "In-app banner"}]})
    await client.patch(url, headers=ops.h, json={"advanceTo": "RESOLVED", "addRemediation": ["Alert on payout error rate"]})
    blocked = await client.patch(url, headers=lead.h, json={"advanceTo": "CLOSED"})
    assert blocked.json()["code"] == "REVIEW_REQUIRED" and "root cause" in blocked.json()["detail"]
    r = await client.patch(url, headers=lead.h, json={"rootCause": "Expired provider API key.", "completeRemediation": [0],
                                                      "review": "Key rotation is now calendared; alert added.", "advanceTo": "CLOSED"})
    body = r.json()
    assert body["status"] == "CLOSED" and body["closedAt"] and body["remediation"][0]["done"]
    assert [t["note"] for t in body["timeline"]][-1] == "Status: closed" and body["notifications"][0]["party"] == "Professionals affected"
    assert (await client.patch(url, headers=lead.h, json={"note": "late"})).json()["code"] == "INCIDENT_CLOSED"
    assert [i["reference"] for i in (await client.get(I, headers=ops.h)).json()] == [body["reference"]]
