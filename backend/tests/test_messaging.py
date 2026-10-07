"""Step 10: immutable request/engagement conversations, attachments and dispute locks."""

from __future__ import annotations

import base64
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from test_proposal import R, buyer_org, request_body, tier_b
from test_contract import signed_contract
from zoikorum.domains.messaging.facade import export_thread
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event


async def request_conversation(client, make_user, drain, *, nda=False):
    pro_user, pro = await tier_b(client, make_user, drain, "messaging-pro")
    buyer, org = await buyer_org(client, make_user, drain, "messaging-buyer")
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro, ndaRequired=nda))).json()[0]
    await drain()
    thread = (await client.get("/v1/threads", headers=buyer.h)).json()["items"][0]
    return pro_user, buyer, req, thread


@pytest.mark.asyncio
async def test_request_event_creates_thread_and_enforces_participants_and_nda(client, make_user, drain):
    pro, buyer, request, thread = await request_conversation(client, make_user, drain, nda=True)
    assert thread["contextType"] == "PROPOSAL_REQUEST"
    assert thread["contextId"] == request["id"]
    assert thread["lastMessage"] == "A professional request was sent."
    assert thread["lastMessageFromSystem"] is True

    hidden = (await client.get("/v1/threads", headers=pro.h)).json()["items"]
    assert hidden == []
    outsider = await make_user("messaging-outsider")
    assert (await client.get(f"/v1/threads/{thread['id']}", headers=outsider.h)).status_code == 404

    accepted = await client.post(f"{R}/{request['id']}/accept-nda", headers=pro.h)
    assert accepted.status_code == 200, accepted.text
    visible = (await client.get("/v1/threads", headers=pro.h)).json()["items"]
    assert [item["id"] for item in visible] == [thread["id"]]

    opened = await client.post("/v1/threads", headers=buyer.idem(), json={
        "contextType": "PROPOSAL_REQUEST", "contextId": request["id"],
    })
    assert opened.status_code == 201, opened.text
    assert opened.json()["id"] == thread["id"]


@pytest.mark.asyncio
async def test_messages_flags_read_positions_and_attachments(client, make_user, drain, sf):
    pro, buyer, request, thread = await request_conversation(client, make_user, drain)
    thread_id = thread["id"]
    send_headers = buyer.idem()
    send_body = {"body": "Please contact me at outside@example.com or +1 (212) 555-0188"}
    sent = await client.post(f"/v1/threads/{thread_id}/messages", headers=send_headers, json=send_body)
    assert sent.status_code == 201, sent.text
    assert sent.json()["sequence"] == 2
    replay = await client.post(f"/v1/threads/{thread_id}/messages", headers=send_headers, json=send_body)
    assert replay.status_code == 201
    assert replay.json()["id"] == sent.json()["id"]
    await drain()
    async with sf() as session:
        flagged = await session.scalar(
            text("SELECT count(*) FROM platform.outbox WHERE event_type = :event"),
            {"event": E.MESSAGE_FLAGGED},
        )
    assert flagged == 1
    pro_threads = (await client.get("/v1/threads", headers=pro.h)).json()["items"]
    assert pro_threads[0]["unreadCount"] == 2  # lifecycle system note plus the buyer's message
    assert (await client.get("/v1/threads/summary", headers=pro.h)).json() == {"unreadThreads": 1, "unreadMessages": 2}
    page = await client.get(f"/v1/threads/{thread_id}/messages", headers=pro.h)
    assert page.status_code == 200
    assert page.json()["items"][0]["body"].startswith("Please contact")

    read = await client.post(f"/v1/threads/{thread_id}/read", headers=pro.h, json={"throughSequence": 2})
    assert read.status_code == 204
    assert (await client.get("/v1/threads", headers=pro.h)).json()["items"][0]["unreadCount"] == 0
    assert (await client.get("/v1/threads/summary", headers=pro.h)).json()["unreadMessages"] == 0

    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
    upload = await client.post(
        f"/v1/threads/{thread_id}/attachments",
        headers=buyer.idem(),
        json={"name": "Scope.pdf", "dataBase64": base64.b64encode(pdf).decode()},
    )
    assert upload.status_code == 201, upload.text
    attachment = upload.json()
    attached = await client.post(
        f"/v1/threads/{thread_id}/messages",
        headers=buyer.idem(),
        json={"attachments": [attachment["id"]]},
    )
    assert attached.status_code == 201, attached.text
    assert attached.json()["attachments"][0]["sha256"] == attachment["sha256"]

    download = await client.get(
        f"/v1/threads/{thread_id}/attachments/{attachment['id']}", headers=pro.h
    )
    assert download.status_code == 200
    assert download.content == pdf
    assert download.headers["cache-control"] == "private, no-store"

    async with sf() as session:
        exported = await export_thread(session, "PROPOSAL_REQUEST", uuid.UUID(request["id"]))
    assert [message.body for message in exported][-1] == ""
    assert exported[-1].attachment_hashes == (attachment["sha256"],)
    assert exported[-1].content_hash == attached.json()["contentHash"]

    with pytest.raises(DBAPIError):
        async with sf() as session, session.begin():
            await session.execute(
                text("UPDATE messaging.attachments SET name = 'changed' WHERE id = :id"),
                {"id": attachment["id"]},
            )


@pytest.mark.asyncio
async def test_dispute_events_lock_and_unlock_after_last_open_case(client, make_user, drain, sf):
    _, _, buyer, contract = await signed_contract(client, make_user, drain)
    request_threads = (await client.get("/v1/threads", headers=buyer.h)).json()["items"]
    request_thread = next(t for t in request_threads if t["contextType"] == "PROPOSAL_REQUEST")
    contract_thread = next(t for t in request_threads if t["contextType"] == "CONTRACT")

    async def publish(event_type, dispute_id):
        async with sf() as session, session.begin():
            record_event(
                session,
                event_type,
                aggregate_type="Dispute",
                aggregate_id=dispute_id,
                tenant_id=contract["organizationId"],
                payload={
                    "disputeId": dispute_id,
                    "contractId": contract["id"],
                    "organizationId": contract["organizationId"],
                    "professionalId": contract["professionalId"],
                    "milestoneIds": [],
                    "category": "QUALITY",
                    "initiatedBy": str(buyer.id),
                },
            )
        await drain()

    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    await publish(E.DISPUTE_INITIATED, first)
    await publish(E.DISPUTE_INITIATED, second)

    active = (await client.get("/v1/threads", headers=buyer.h)).json()["items"]
    assert all(thread["locked"] for thread in active if thread["contextType"] != "DISPUTE")
    dispute_thread = next(t for t in active if t["contextType"] == "DISPUTE" and t["contextId"] == second)
    dispute_history = await client.get(f"/v1/threads/{dispute_thread['id']}/messages", headers=buyer.h)
    assert dispute_history.status_code == 200
    assert dispute_history.json()["items"][0]["body"] == "A dispute workspace has been opened."
    async with sf() as session:
        evidence = await export_thread(session, "DISPUTE", uuid.UUID(second))
    assert [message.body for message in evidence] == ["A dispute workspace has been opened."]
    cannot_create_dispute_thread = await client.post(
        "/v1/threads",
        headers=buyer.idem(),
        json={"contextType": "DISPUTE", "contextId": second},
    )
    assert cannot_create_dispute_thread.status_code == 409
    assert cannot_create_dispute_thread.json()["code"] == "DISPUTE_THREAD_SYSTEM_CREATED"

    blocked = await client.post(
        f"/v1/threads/{contract_thread['id']}/messages",
        headers=buyer.idem(),
        json={"body": "I would like to discuss this."},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "THREAD_READ_ONLY"
    read = await client.get(f"/v1/threads/{contract_thread['id']}/messages", headers=buyer.h)
    assert read.status_code == 200
    assert read.json()["items"][0]["senderIdentityId"] is None

    await publish(E.DISPUTE_CLOSED, first)
    still_locked = (await client.get("/v1/threads", headers=buyer.h)).json()["items"]
    assert next(t for t in still_locked if t["id"] == contract_thread["id"])["locked"] is True

    await publish(E.DISPUTE_CLOSED, second)
    unlocked = (await client.get("/v1/threads", headers=buyer.h)).json()["items"]
    assert next(t for t in unlocked if t["id"] == contract_thread["id"])["locked"] is False
    assert next(t for t in unlocked if t["id"] == request_thread["id"])["locked"] is False

    async with sf() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("UPDATE messaging.messages SET body = 'changed'"))


async def test_private_upload_versions_pagination_and_live_membership(client, make_user, drain, sf):
    pro, buyer, _, thread = await request_conversation(client, make_user, drain)
    root = f"/v1/threads/{thread['id']}"
    content = b"A real versioned document"
    body = {"name": "scope.txt", "dataBase64": base64.b64encode(content).decode()}
    first = await client.post(f"{root}/attachments", headers=buyer.idem(), json=body)
    assert first.status_code == 201, first.text
    file = first.json()
    assert (await client.get(f"{root}/attachments/{file['id']}", headers=pro.h)).status_code == 404
    second = await client.post(f"{root}/attachments", headers=buyer.idem(), json=body)
    assert second.json()["fileVersion"] == 2
    bad = await client.post(f"{root}/attachments", headers=buyer.idem(), json={**body, "name": "../scope.txt"})
    assert bad.status_code == 422
    shared = await client.post(f"{root}/messages", headers=buyer.idem(), json={"body": "The scope", "attachments": [file['id']]})
    assert shared.status_code == 201, shared.text
    assert (await client.get(f"{root}/attachments/{file['id']}", headers=pro.h)).content == content
    stolen = await client.post(f"{root}/messages", headers=pro.idem(), json={"attachments": [file['id']]})
    assert stolen.status_code == 422
    page = (await client.get(f"{root}/messages", headers=pro.h, params={"limit": 1})).json()
    assert len(page["items"]) == 1 and page["nextCursor"]
    older = (await client.get(f"{root}/messages", headers=pro.h, params={"before": page["nextCursor"]})).json()
    assert older["items"][0]["sequence"] < page["items"][0]["sequence"]
    assert (await client.post(f"{root}/read", headers=pro.h, json={"throughSequence": 2})).status_code == 204
    assert (await client.post(f"{root}/read", headers=pro.h, json={"throughSequence": 1})).status_code == 204
    assert (await client.get(root, headers=pro.h)).json()["unreadCount"] == 0
    assert (await client.post(f"{root}/read", headers=pro.h, json={"throughSequence": 999})).status_code == 422
    async with sf() as session, session.begin():
        await session.execute(text("UPDATE buyer.members SET status = 'REMOVED' WHERE identity_id = :id"), {"id": buyer.id})
    assert (await client.get(root, headers=buyer.h)).status_code == 404
    assert (await client.get(f"{root}/attachments/{file['id']}", headers=buyer.h)).status_code == 404
    assert (await client.post(f"{root}/messages", headers=buyer.idem(), json={"body": "Stale token"})).status_code == 404


async def test_closed_dispute_cannot_be_reopened_by_delayed_initiation(client, make_user, drain, sf):
    from datetime import timedelta
    from zoikorum.domains.messaging import service
    from zoikorum.shared import clock
    _, _, buyer, agreement = await signed_contract(client, make_user, drain)
    case_id = str(uuid.uuid4())
    payload = {"disputeId": case_id, "contractId": agreement["id"], "category": "QUALITY"}
    older = clock.now() - timedelta(hours=1)
    initiated = SimpleNamespace(payload=payload, aggregateId=case_id, eventId=uuid.uuid4(), occurredAt=older)
    closed = SimpleNamespace(payload=payload, aggregateId=case_id, eventId=uuid.uuid4(), occurredAt=clock.now())
    async with sf() as session, session.begin():
        await service.on_dispute_closed(session, closed)
    async with sf() as session, session.begin():
        await service.on_dispute_initiated(session, initiated)
    threads = (await client.get("/v1/threads", headers=buyer.h)).json()["items"]
    assert next(t for t in threads if t["contextType"] == "CONTRACT")["canSend"]
    assert not any(t["contextType"] == "DISPUTE" and t["contextId"] == case_id for t in threads)
