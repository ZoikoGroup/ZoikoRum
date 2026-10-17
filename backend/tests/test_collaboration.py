"""Working together inside an engagement: meetings in the conversation (and the calendar feed), and a shared task list."""

from __future__ import annotations

from datetime import timedelta

from test_contract import C, signed_contract
from zoikorum.shared import clock


async def contract_thread(client, user, contract_id):
    rows = (await client.get("/v1/threads", headers=user.h, params={"contextType": "CONTRACT", "contextId": contract_id})).json()["items"]
    if rows:
        return rows[0]
    return (await client.post("/v1/threads", headers=user.idem(), json={"contextType": "CONTRACT", "contextId": contract_id})).json()


async def test_meetings_are_scheduled_in_the_conversation_and_reach_the_calendar(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    t = await contract_thread(client, buyer, c["id"])
    starts = (clock.now() + timedelta(days=2)).replace(microsecond=0)
    url = f"/v1/threads/{t['id']}/meetings"

    own = await client.post(url, headers=buyer.idem(), json={"title": "Kick-off", "startsAt": starts.isoformat(), "durationMinutes": 45,
                                                              "joinUrl": "https://example.zoom.us/j/123"})
    assert own.status_code == 201, own.text
    assert own.json()["joinUrl"] == "https://example.zoom.us/j/123"
    made = (await client.post(url, headers=pro_user.idem(), json={"title": "Weekly check-in", "startsAt": starts.isoformat(),
                                                                   "durationMinutes": 30})).json()
    assert made["joinUrl"].startswith("https://meet.jit.si/zoikorum-") and len(made["joinUrl"]) > 40  # unguessable room
    bad = await client.post(url, headers=buyer.idem(), json={"title": "x call", "startsAt": starts.isoformat(), "durationMinutes": 30,
                                                              "joinUrl": "http://insecure.example.com"})
    assert bad.json()["code"] == "MEETING_LINK_INVALID"
    past = await client.post(url, headers=buyer.idem(), json={"title": "Late", "startsAt": (clock.now() - timedelta(days=1)).isoformat(),
                                                               "durationMinutes": 30})
    assert past.json()["code"] == "MEETING_IN_PAST"

    messages = (await client.get(f"/v1/threads/{t['id']}/messages", headers=buyer.h)).json()["items"]
    assert any(m["body"].startswith("Meeting scheduled: Kick-off") for m in messages)
    listed = (await client.get(url, headers=pro_user.h)).json()
    assert [m["title"] for m in listed] == ["Kick-off", "Weekly check-in"]
    stranger = await make_user("meeting-stranger")
    assert (await client.get(url, headers=stranger.h)).status_code == 404

    link = (await client.put("/v1/calendar/link", headers=pro_user.h, json={"enabled": True})).json()
    feed = (await client.get(link["url"])).text
    assert "SUMMARY:Kick-off" in feed and "URL:https://example.zoom.us/j/123" in feed and f"DTSTART:{starts.strftime('%Y%m%dT%H%M%SZ')}" in feed

    cancelled = (await client.post(f"/v1/meetings/{own.json()['id']}/cancel", headers=buyer.idem())).json()
    assert cancelled["status"] == "CANCELLED"
    assert "SUMMARY:Kick-off" not in (await client.get(link["url"])).text


async def test_the_task_list_is_shared_by_both_sides(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    url = f"{C}/{c['id']}/tasks"
    due = (clock.now().date() - timedelta(days=1)).isoformat()
    t1 = (await client.post(url, headers=buyer.idem(), json={"title": "Share the trial balances", "owner": "BUYER", "dueDate": due})).json()
    assert t1["overdue"] is True and t1["done"] is False
    t2 = (await client.post(url, headers=pro_user.idem(), json={"title": "Draft the master file", "owner": "PROFESSIONAL",
                                                                 "milestoneId": c["milestones"][0]["id"]})).json()
    done = (await client.patch(f"/v1/contract-tasks/{t1['id']}", headers=pro_user.idem(), json={"done": True})).json()
    assert done["done"] is True and done["overdue"] is False
    listed = (await client.get(url, headers=buyer.h)).json()
    assert [x["title"] for x in listed] == ["Draft the master file", "Share the trial balances"]  # open ones first
    assert (await client.delete(f"/v1/contract-tasks/{t2['id']}", headers=buyer.idem())).status_code == 204
    assert len((await client.get(url, headers=pro_user.h)).json()) == 1
    stranger = await make_user("task-stranger")
    assert (await client.get(url, headers=stranger.h)).status_code == 404
    assert (await client.post(url, headers=buyer.idem(), json={"title": "x", "owner": "BUYER"})).status_code == 422
