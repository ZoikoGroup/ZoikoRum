"""Audit archive to write-once storage after 90 days; email digests; private calendar feed."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from test_contract import signed_contract
from test_proposal import buyer_org
from zoikorum.shared import clock


async def test_old_audit_records_are_archived_and_can_be_verified(client, make_user, drain, sf):
    from zoikorum.domains.audit import archive

    await buyer_org(client, make_user, drain, "arch-buyer")  # some audit records
    await drain()
    clock.set_now(clock.now() + timedelta(days=91))
    try:
        async with sf() as s, s.begin():
            batch = await archive.archive_due(s, rearm=False)
            again = await archive.archive_due(s, rearm=False)  # nothing new to archive
    finally:
        clock.set_now(None)
    assert batch is not None and batch.record_count > 0 and again is None
    admin = await make_user("arch-admin", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    listed = (await client.get("/v1/admin/audit/archives", headers=admin.h)).json()
    assert listed[0]["toSeq"] == batch.to_seq and listed[0]["objectKey"].startswith("audit-archive/")
    checked = (await client.post(f"/v1/admin/audit/archives/{listed[0]['id']}/verify", headers=admin.h)).json()
    assert checked["ok"] is True and checked["lastVerifiedAt"]


async def test_digest_bundles_non_urgent_emails(client, make_user, drain, sf):
    from zoikorum.domains.notification import service as notifications
    from zoikorum.domains.notification.models import Notification

    buyer, _ = await buyer_org(client, make_user, drain, "digest-buyer")
    prefs = (await client.put("/v1/notification-preferences", headers=buyer.h, json={"email": True, "inApp": True, "digest": "DAILY"})).json()
    assert prefs["digest"] == "DAILY"
    nid = uuid.uuid4()
    async with sf() as s, s.begin():
        s.add(Notification(id=nid, source_event_id=uuid.uuid4(), identity_id=buyer.id, event_type="zoikorum.contract.retainer.paused.v1",
                           title="Retainer paused", body="Your retainer was paused.", url="/app/engagements", in_app=True, mandatory=False,
                           email_status="PENDING", email_attempts=0))
    async with sf() as s, s.begin():
        await notifications.deliver_email(s, str(nid))
    async with sf() as s:
        assert (await s.get(Notification, nid)).email_status == "DIGEST"
    async with sf() as s, s.begin():
        assert await notifications.send_digests(s, rearm=False) == 1
    async with sf() as s:
        assert (await s.get(Notification, nid)).email_status == "DIGESTED"


async def test_private_calendar_feed_lists_due_dates(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    link = (await client.put("/v1/calendar/link", headers=buyer.h, json={"enabled": True})).json()
    assert link["url"].startswith("/v1/calendar/") and link["url"].endswith(".ics")
    feed = await client.get(link["url"])  # calendar apps fetch it without signing in
    assert feed.status_code == 200 and feed.headers["content-type"].startswith("text/calendar")
    body = feed.text
    assert body.startswith("BEGIN:VCALENDAR") and body.rstrip().endswith("END:VCALENDAR")
    if any(m["dueDate"] for m in c["milestones"]):
        assert "BEGIN:VEVENT" in body and c["reference"] in body
    new = (await client.put("/v1/calendar/link", headers=buyer.h, json={"enabled": True})).json()
    assert (await client.get(link["url"])).status_code == 404 and (await client.get(new["url"])).status_code == 200  # replaced
    await client.put("/v1/calendar/link", headers=buyer.h, json={"enabled": False})
    assert (await client.get(new["url"])).status_code == 404
