"""Engineering Handbook 14.3 and 21.3-21.4: retries are spaced with jitter, failures that cannot succeed are not retried,
partners behind circuit breakers, and every built-in AI prompt is registered, can be switched off and is logged."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from test_taxonomy_suggestions import catalog
from zoikorum.config import Settings
from zoikorum.domains.ai import claude, documents, intent
from zoikorum.domains.ai.models import InferenceLog
from zoikorum.domains.notification import providers as mail
from zoikorum.shared.errors import Conflict, NotFound, PolicyBlocked, RateLimited, ServiceUnavailable, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event, registry
from zoikorum.shared.platform_models import ConsumerFailure
from zoikorum.shared.relay import relay_once
from zoikorum.shared.retry import exponential, is_permanent, jittered, scheduled

# ---- Retry spacing and worthiness -------------------------------------------------------------------------------------


@pytest.mark.unit
def test_retries_are_spread_between_half_and_all_of_the_delay():
    delays = [jittered(100) for _ in range(500)]
    assert all(50 <= d <= 100 for d in delays) and max(delays) - min(delays) > 20  # spread, not one moment
    assert 15 <= exponential(1) <= 30 and 30 <= exponential(2) <= 60 and 1800 <= exponential(40) <= 3600
    assert 900 <= scheduled(9, (5, 30, 1800)) <= 1800  # the last step repeats


@pytest.mark.unit
def test_only_failures_that_cannot_succeed_are_permanent():
    assert all(is_permanent(e) for e in (ValidationFailed(), NotFound(), PolicyBlocked()))
    assert not any(is_permanent(e) for e in (Conflict(), RateLimited(), ServiceUnavailable(), RuntimeError(), TimeoutError()))


async def test_a_consumer_failure_that_cannot_succeed_goes_to_an_operator_at_once(sf):
    calls = {"n": 0}

    @registry.subscribe(E.LISTING_VIEWED, consumer="test.resilience_invalid")
    async def _h(session, env):
        calls["n"] += 1
        raise ValidationFailed("the event refers to a milestone that does not exist")

    async with sf() as s, s.begin():
        record_event(s, E.LISTING_VIEWED, aggregate_type="Listing", aggregate_id="p1", payload={})
    await relay_once(sf)
    async with sf() as s:
        f = await s.scalar(select(ConsumerFailure).where(ConsumerFailure.consumer == "test.resilience_invalid"))
    assert f.status == "DEAD" and f.attempts == 1 and calls["n"] == 1 and f.next_attempt_at is None


# ---- Circuit breakers -------------------------------------------------------------------------------------------------


@pytest.mark.unit
async def test_a_mail_outage_makes_queued_emails_fail_fast(monkeypatch):
    connects = {"n": 0}

    def down(*a, **kw):
        connects["n"] += 1
        raise ConnectionRefusedError("mail server down")

    monkeypatch.setattr(mail.smtplib, "SMTP", down)
    monkeypatch.setattr(mail, "get_settings", lambda: Settings(_env_file=None, email_provider="smtp", smtp_host="mail.test"))
    breaker = mail.mail_breaker()
    breaker.reset()
    for _ in range(breaker.failure_threshold):
        with pytest.raises(ConnectionRefusedError):
            await mail.SMTPEmailProvider().send("a@example.com", "Hi", "Body", "m1")
    with pytest.raises(ServiceUnavailable):
        await mail.SMTPEmailProvider().send("a@example.com", "Hi", "Body", "m2")
    assert connects["n"] == breaker.failure_threshold  # the server is not even contacted while the circuit is open
    breaker.reset()


# ---- Built-in AI prompts --------------------------------------------------------------------------------------------


def fake_claude(monkeypatch, answer=None, error: Exception | None = None, disabled: tuple[str, ...] = ()):
    calls = []

    class Messages:
        async def parse(self, **kwargs):
            calls.append(kwargs)
            if error:
                raise error
            return SimpleNamespace(stop_reason="end_turn", parsed_output=answer)

    class Client:
        def __init__(self, **kwargs):
            self.messages = Messages()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setitem(__import__("sys").modules, "anthropic", SimpleNamespace(AsyncAnthropic=Client, APIError=Exception))
    configured = Settings(_env_file=None, ai_provider="anthropic", anthropic_api_key="test-key", ai_disabled_prompts=list(disabled))
    monkeypatch.setattr(claude, "get_settings", lambda: configured)
    monkeypatch.setattr(intent, "get_settings", lambda: configured)
    monkeypatch.setattr(documents, "get_settings", lambda: configured)
    return calls


async def test_each_claude_call_is_logged_with_a_hash_never_the_text(monkeypatch, sf):
    answer = intent._IntentOut(specialization_slugs=["fractional-cfo"], engagement_type="FRACTIONAL")
    calls = fake_claude(monkeypatch, answer)
    who = uuid.uuid4()
    async with sf() as s, s.begin():
        i = await intent.extract_search_intent("a fractional CFO, my phone is 0123", catalog(), session=s, requested_by=who)
    assert i.source == "ai:claude-opus-5-5@search-intent-1" and len(calls) == 1
    async with sf() as s:
        row = await s.scalar(select(InferenceLog))
    assert row.purpose == "search-intent" and row.prompt_version == 1 and row.requested_by == who and not row.fallback_used
    assert row.input_sha256 == claude.input_hash("a fractional CFO, my phone is 0123") and "0123" not in row.output


async def test_a_failed_call_falls_back_and_is_logged_as_such(monkeypatch, sf):
    fake_claude(monkeypatch, error=TimeoutError("slow"))
    async with sf() as s, s.begin():
        i = await intent.extract_search_intent("fractional CFO", catalog(), session=s)
    assert i.source == "fallback:keyword"
    async with sf() as s:
        row = await s.scalar(select(InferenceLog))
    assert row.fallback_used and row.output == "[failed: TimeoutError]" and row.requested_by is None


@pytest.mark.unit
async def test_a_switched_off_prompt_is_not_called(monkeypatch):
    calls = fake_claude(monkeypatch, disabled=("document-check",))
    result = await documents.assess_document(b"\x89PNG....", "image/png", "a passport")
    assert result.verdict == "NOT_CHECKED" and calls == []


@pytest.mark.unit
async def test_a_claude_outage_opens_one_breaker_for_every_feature(monkeypatch):
    calls = fake_claude(monkeypatch, error=ConnectionError("down"))
    claude.breaker().reset()
    for _ in range(claude.breaker().failure_threshold):
        await intent.extract_search_intent("fractional CFO", catalog())
    tried = len(calls)
    assert (await documents.assess_document(b"\x89PNG....", "image/png", "a passport")).verdict == "NOT_CHECKED"
    assert len(calls) == tried  # the document check fell back without calling a partner known to be down
    claude.breaker().reset()


async def test_reviewers_see_the_built_in_prompts(client, make_user):
    reviewer = await make_user("prompts", platform_roles=("AI_SAFETY_REVIEWER",))
    await reviewer.step_up()  # staff access needs two-step sign-in
    r = await client.get("/v1/ai/prompts/built-in", headers=reviewer.h)
    assert r.status_code == 200, r.text
    rows = {p["promptKey"]: p for p in r.json()}
    assert set(rows) == {"search-intent", "document-check", "spec-match"}
    assert all(p["status"] == "NOT_CONFIGURED" and p["goldenTests"].startswith("tests/golden/") for p in rows.values())
    buyer = await make_user("nosy")
    assert (await client.get("/v1/ai/prompts/built-in", headers=buyer.h)).status_code == 403


@pytest.mark.unit
def test_every_built_in_prompt_has_a_golden_set():
    from pathlib import Path
    import json

    root = Path(__file__).resolve().parents[1]
    for p in claude.BUILT_IN.values():
        cases = json.loads((root / p.golden_tests).read_text(encoding="utf-8"))
        assert len(cases) >= 4 and all("expect" in c for c in cases), p.key



# ---- Two people editing the same thing (Engineering Handbook 18.4) ---------------------------------------------------


async def test_an_edit_made_on_an_old_copy_of_a_proposal_is_refused(client, make_user, drain):
    from test_doc_review_bugs import submitted_proposal
    from test_proposal import P, proposal_body

    pro_user, pro, buyer, org, p = await submitted_proposal(client, make_user, drain, "editor")
    first = await client.patch(f"{P}/{p['id']}", headers={**pro_user.h, "If-Match": str(p["version"])},
                               json=proposal_body(summary="Master and local files, with a kick-off call."))
    assert first.status_code == 200, first.text
    assert first.json()["version"] > p["version"]
    stale = await client.patch(f"{P}/{p['id']}", headers={**pro_user.h, "If-Match": str(p["version"])},
                               json=proposal_body(summary="An edit from a tab opened before the first save."))
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    again = await client.patch(f"{P}/{p['id']}", headers={**pro_user.h, "If-Match": f'"{first.json()["version"]}"'},
                               json=proposal_body())
    assert again.status_code == 200, again.text


async def test_an_edit_made_on_an_old_copy_of_an_organisation_is_refused(client, make_user, drain):
    from test_proposal import buyer_org

    buyer, current = await buyer_org(client, make_user, drain)
    org = current["id"]
    renamed = await client.patch(f"/v1/organizations/{org}", headers={**buyer.h, "If-Match": str(current["version"])},
                                 json={"name": "Acme Holdings"})
    assert renamed.status_code == 200, renamed.text
    other_tab = await client.patch(f"/v1/organizations/{org}", headers={**buyer.h, "If-Match": str(current["version"])},
                                   json={"name": "Acme Group"})
    assert other_tab.status_code == 409 and other_tab.json()["code"] == "VERSION_CONFLICT"
    assert (await client.get(f"/v1/organizations/{org}", headers=buyer.h)).json()["name"] == "Acme Holdings"


# ---- Metrics, worker backlog and clean-up (Engineering Handbook 24.1, 28) ---------------------------------------------


async def test_metrics_need_the_token_and_report_routes_and_the_worker_backlog(client, monkeypatch, sf):
    import zoikorum.main as main

    assert (await client.get("/metrics")).status_code == 404  # no token configured: the page does not exist
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None, metrics_token="scrape-secret"))
    assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 404
    await client.get("/v1/search/professionals", params={"q": "tax"})
    async with sf() as s, s.begin():
        record_event(s, E.LISTING_VIEWED, aggregate_type="Listing", aggregate_id="p1", payload={})  # not yet relayed
    r = await client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    text = r.text
    assert 'zk_http_request_duration_seconds_count{method="GET",route="/v1/search/professionals",status="2xx"}' in text
    import re

    assert float(re.search(r"^zk_outbox_unpublished_events (\S+)$", text, re.M).group(1)) >= 1  # waits for the worker
    assert "zk_consumer_dead_letters 0.0" in text
    assert 'zk_circuit_open{breaker="AI assistant"} 0.0' in text
    assert "?" not in "".join(l for l in text.splitlines() if l.startswith("zk_http"))  # route templates, no query strings


async def test_staff_see_how_far_behind_the_worker_is(client, make_user, sf):
    admin = await make_user("ops", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    async with sf() as s, s.begin():
        record_event(s, E.LISTING_VIEWED, aggregate_type="Listing", aggregate_id="p1", payload={})
    r = await client.get("/v1/admin/worker", headers=admin.h)
    assert r.status_code == 200, r.text
    assert r.json()["unpublishedEvents"] >= 1 and r.json()["deadLetters"] == 0
    buyer = await make_user("not-staff")
    assert (await client.get("/v1/admin/worker", headers=buyer.h)).status_code == 403


async def test_housekeeping_removes_old_bookkeeping_only(sf):
    from datetime import timedelta

    from sqlalchemy import text

    from zoikorum.shared import clock, housekeeping

    old = clock.now() - timedelta(days=45)
    async with sf() as s, s.begin():
        for scope, at in (("old-key", old), ("new-key", clock.now())):
            await s.execute(text("INSERT INTO platform.idempotency_keys (scope, request_hash, response_status, created_at) "
                                 "VALUES (:s, 'h', 200, :at)"), {"s": scope, "at": at})
        for name, published in (("handled", old), ("waiting", None)):
            record_event(s, E.LISTING_VIEWED, aggregate_type="Listing", aggregate_id=name, payload={})
            await s.flush()
            await s.execute(text("UPDATE platform.outbox SET created_at = :at, published_at = :p WHERE aggregate_id = :a"),
                            {"at": old, "p": published, "a": name})
        for status in ("RESOLVED", "DEAD"):
            await s.execute(text(
                "INSERT INTO platform.consumer_failures (id, consumer, event_id, event_type, envelope, attempts, status, "
                "financial, created_at) VALUES (gen_random_uuid(), :c, gen_random_uuid(), 'x', '{}', 1, :st, false, :at)"),
                {"c": f"test.{status}", "st": status, "at": old})
    async with sf() as s, s.begin():
        removed = await housekeeping.clean_up(s)
    assert removed == {"idempotencyKeys": 1, "publishedEvents": 1, "handledMarkers": 0, "resolvedFailures": 1}
    async with sf() as s:
        assert await s.scalar(text("SELECT array_agg(scope) FROM platform.idempotency_keys")) == ["new-key"]
        assert await s.scalar(text("SELECT array_agg(aggregate_id) FROM platform.outbox")) == ["waiting"]  # never relayed
        assert await s.scalar(text("SELECT array_agg(status) FROM platform.consumer_failures")) == ["DEAD"]  # for an operator


# ---- Long lists come in pages, never silently cut off (Engineering Handbook 18.3) -----------------------------------


async def test_lists_that_grow_come_in_pages_in_their_order(client, make_user, drain):
    from test_taxonomy_suggestions import T
    from test_search import publish

    admin = await make_user("ada", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    names = []
    for who, name in (("ann", "Robotic Process Automation"), ("ben", "Carbon Accounting"), ("cat", "Grant Writing")):
        u, _ = await publish(client, make_user, drain, who, headline="Consultant", primary="business-strategy")
        body = {"text": f"I do {name.lower()}", "name": name, "groupSlug": "software-development",
                "description": "A new kind of work", "source": "fallback:keyword"}
        assert (await client.post(f"{T}/suggestions", headers=u.h, json=body)).status_code in (200, 201)
        names.append(name)

    seen, cursor = [], None
    while True:  # the review queue: oldest first, one per page
        page = (await client.get("/v1/admin/taxonomy/suggestions", headers=admin.h,
                                 params={"limit": 1, **({"cursor": cursor} if cursor else {})})).json()
        seen += [s["name"] for s in page["items"]]
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert seen == names

    buyer, pros = await make_user("bea"), []
    for who in ("dan", "eve", "fay"):
        _, pro = await publish(client, make_user, drain, who, headline="Adviser", primary="business-strategy")
        await client.post("/v1/saved/professionals", headers=buyer.h, json={"professionalId": pro["id"]})
        pros.append(pro["id"])
    first = (await client.get("/v1/saved/professionals", headers=buyer.h, params={"limit": 2})).json()
    rest = (await client.get("/v1/saved/professionals", headers=buyer.h,
                             params={"limit": 2, "cursor": first["nextCursor"]})).json()
    assert [s["professionalId"] for s in first["items"] + rest["items"]] == pros[::-1]  # newest first
    assert rest["nextCursor"] is None
    assert (await client.get("/v1/saved/professionals", headers=buyer.h, params={"cursor": "junk"})).status_code == 422
