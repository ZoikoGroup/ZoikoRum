"""Help requests: a person asks with context, a support agent answers in the same conversation, late first answers
go to the top of the queue, and people only ever see their own requests."""

from __future__ import annotations

from sqlalchemy import text

from test_contract import signed_contract
from test_dispute import staff

S = "/v1/support/requests"


async def test_ask_answer_resolve_with_context(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    r = await client.post(S, headers=buyer.h, json={
        "topic": "PAYMENTS", "subject": "Card payment did not go through",
        "message": "I tried to fund milestone 1 twice and both times it said processing.",
        "context": {"page": "/app/engagements/x", "contractId": c["id"], "errorReference": "corr-123"}})
    assert r.status_code == 201
    req = r.json()
    assert req["reference"].startswith("ZK-SUP-") and req["status"] == "OPEN" and req["context"]["engagement"] == c["reference"]
    assert len(req["messages"]) == 1 and req["overdue"] is False

    # Only the person who asked sees it; staff without the role cannot read the queue.
    assert (await client.get(f"{S}/{req['id']}", headers=pro_user.h)).status_code == 404
    other_staff = await staff(make_user, "fin", "FINANCIAL_OPS")
    assert (await client.get("/v1/admin/support/requests", headers=other_staff.h)).status_code == 403

    agent = await staff(make_user, "sam", "SUPPORT_AGENT")
    (queued,) = (await client.get("/v1/admin/support/requests", headers=agent.h)).json()
    assert queued["requesterName"] == buyer.user["displayName"]
    r = await client.post(f"/v1/admin/support/requests/{req['id']}/messages", headers=agent.h,
                          json={"message": "The payment partner was slow; it has now completed. Please refresh."})
    assert r.json()["status"] == "WAITING_ON_YOU" and r.json()["firstRespondedAt"]
    await drain()
    titles = [n["title"] for n in (await client.get("/v1/notifications", headers=buyer.h)).json()["items"]]
    assert "Support replied to your request" in titles
    mine = (await client.get(f"{S}/{req['id']}", headers=buyer.h)).json()
    assert [m["authorName"] for m in mine["messages"]][-1] == "Zoikorum support"  # agents are not named to customers

    r = await client.post(f"{S}/{req['id']}/messages", headers=buyer.h, json={"message": "Thanks, it shows now."})
    assert r.json()["status"] == "OPEN"
    r = await client.post(f"{S}/{req['id']}/resolve", headers=buyer.h)
    assert r.json()["status"] == "RESOLVED" and r.json()["resolvedAt"]


async def test_late_first_answers_come_first(client, make_user, sf):
    a, b = await make_user("ann"), await make_user("ben")
    first = (await client.post(S, headers=a.h, json={"topic": "ACCOUNT", "subject": "Cannot change email",
                                                     "message": "The change email button does nothing."})).json()
    async with sf() as session, session.begin():  # its first-answer deadline has passed
        await session.execute(text("UPDATE support.requests SET first_response_due_at = now() - interval '1 day' WHERE id = :i"),
                              {"i": first["id"]})
    await client.post(S, headers=b.h, json={"topic": "OTHER", "subject": "A new question",
                                            "message": "Where can I see my invoices?"})
    agent = await staff(make_user, "sam", "SUPPORT_AGENT")
    queue = (await client.get("/v1/admin/support/requests", headers=agent.h)).json()
    assert queue[0]["id"] == first["id"] and queue[0]["overdue"] is True and queue[1]["overdue"] is False
