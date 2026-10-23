"""Incident register: unacknowledged -> investigating -> mitigating -> monitoring -> recovered -> closed. Recovery is verified
by someone other than the owner and the mitigator; serious incidents need a root cause, done remediation and a review."""

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
    assert r.status_code == 201 and r.json()["reference"].startswith("ZK-INC-") and r.json()["status"] == "UNACKNOWLEDGED", r.text
    iid = r.json()["id"]
    url = f"{I}/{iid}"
    assert (await client.patch(url, headers=ops.h, json={"advanceTo": "MITIGATING"})).json()["code"] == "INVALID_STEP"
    await client.patch(url, headers=ops.h, json={"advanceTo": "INVESTIGATING", "note": "Looking at provider errors."})
    r = await client.patch(url, headers=ops.h, json={"advanceTo": "MITIGATING", "note": "Payouts paused via switches.",
                                                     "notified": [{"party": "Professionals affected", "note": "In-app banner"}]})
    assert r.json()["mitigatedBy"] and r.json()["mitigatingAt"]
    await client.patch(url, headers=ops.h, json={"advanceTo": "MONITORING", "addRemediation": ["Alert on payout error rate"]})
    # Mitigation is not verified recovery: the owner (who also mitigated) cannot mark it recovered.
    own = await client.patch(url, headers=ops.h, json={"advanceTo": "RECOVERED", "recoveryNote": "Payouts flowing again."})
    assert own.json()["code"] == "INDEPENDENT_VERIFICATION_REQUIRED"
    nonote = await client.patch(url, headers=lead.h, json={"advanceTo": "RECOVERED"})
    assert nonote.json()["code"] == "RECOVERY_NOTE_REQUIRED"
    r = await client.patch(url, headers=lead.h, json={"advanceTo": "RECOVERED", "recoveryNote": "50 test payouts settled; error rate 0%."})
    assert r.json()["status"] == "RECOVERED" and r.json()["recoveredAt"] and r.json()["recoveryVerifiedBy"]
    assert r.json()["recoveryNote"] == "50 test payouts settled; error rate 0%."
    blocked = await client.patch(url, headers=lead.h, json={"advanceTo": "CLOSED"})
    assert blocked.json()["code"] == "REVIEW_REQUIRED" and "root cause" in blocked.json()["detail"]
    r = await client.patch(url, headers=lead.h, json={"rootCause": "Expired provider API key.", "completeRemediation": [0],
                                                      "review": "Key rotation is now calendared; alert added.",
                                                      "uxImpact": "Professionals saw payouts delayed by up to a day.",
                                                      "policyUpdates": "None proposed: the payout policy held.", "advanceTo": "CLOSED"})
    body = r.json()
    assert body["status"] == "CLOSED" and body["closedAt"] and body["remediation"][0]["done"]
    assert [t["note"] for t in body["timeline"]][-1] == "Status: closed" and body["notifications"][0]["party"] == "Professionals affected"
    assert (await client.patch(url, headers=lead.h, json={"note": "late"})).json()["code"] == "INCIDENT_CLOSED"
    assert [i["reference"] for i in (await client.get(I, headers=ops.h)).json()] == [body["reference"]]


async def test_recovery_needs_someone_other_than_the_mitigator(client, make_user, drain):
    owner = await staff(make_user, "owner", "SUPPORT_AGENT")
    lead = await staff(make_user, "lead", "PLATFORM_ADMIN")
    peer = await staff(make_user, "peer", "SUPPORT_AGENT")
    iid = (await client.post(I, headers=owner.h, json={"title": "Search is slow", "kind": "OUTAGE", "severity": "SEV4",
                                                       "summary": "Search p99 is over two seconds."})).json()["id"]
    url = f"{I}/{iid}"
    assert (await client.patch(url, headers=peer.h, json={"advanceTo": "INVESTIGATING"})).json()["code"] == "NOT_INCIDENT_OWNER"
    await client.patch(url, headers=owner.h, json={"advanceTo": "INVESTIGATING"})
    await client.patch(url, headers=lead.h, json={"advanceTo": "MITIGATING", "note": "Scaled the search nodes."})
    await client.patch(url, headers=owner.h, json={"advanceTo": "MONITORING"})
    assert (await client.patch(url, headers=lead.h, json={"advanceTo": "RECOVERED", "recoveryNote": "Looks fine to me now."})).json()["code"] \
        == "INDEPENDENT_VERIFICATION_REQUIRED"  # the lead set mitigating
    r = await client.patch(url, headers=peer.h, json={"advanceTo": "RECOVERED", "recoveryNote": "p99 under 300 ms for an hour."})
    assert r.status_code == 200 and r.json()["status"] == "RECOVERED"
    r = await client.patch(url, headers=owner.h, json={"advanceTo": "CLOSED"})  # SEV4: no review needed
    assert r.json()["status"] == "CLOSED"
