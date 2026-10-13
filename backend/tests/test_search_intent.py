""""Describe what you need": a buyer's own words become ordinary search filters, each with its reason (AI assists;
the buyer reviews them). Claude when configured; keyword rules otherwise or on any failure."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from test_search import URL, publish
from test_taxonomy_suggestions import catalog
from zoikorum.config import Settings
from zoikorum.domains.ai import claude
from zoikorum.domains.ai import intent as ai
from zoikorum.domains.search import api as search_api
from zoikorum.shared import ratelimit

I = "/v1/search/intent"


# ---- Unit: keyword rules -------------------------------------------------------------------------------------------

@pytest.mark.unit
def test_keyword_rules_read_the_common_parts_of_a_request():
    i = ai.keyword_intent("We need an ongoing fractional CFO in Germany who can start now, remote is fine", catalog())
    assert i.specializations == ("fractional-cfo",) and i.engagement_type == "FRACTIONAL" and i.delivery == "REMOTE"
    assert i.availability == "NOW" and i.jurisdiction == "DE" and i.keywords is None and i.source == "fallback:keyword"
    assert i.reasons == ("Specialization: Fractional CFO", "You asked for a fractional or part-time role", "Works remotely",
                         "Timing: can start now", "Serves Germany")

    i = ai.keyword_intent("Licensed tax adviser for transfer pricing documentation, UK, insured", catalog())
    assert i.specializations == ("transfer-pricing",) and i.jurisdiction == "GB" and i.verified == ("credentials", "insurance")
    assert "Serves the United Kingdom" in i.reasons

    assert ai.keyword_intent("need a data engineer for pipelines", catalog()).specializations == ("data-engineering",)


@pytest.mark.unit
def test_broad_words_alone_do_not_pick_a_specialization():
    i = ai.keyword_intent("Someone for a data pipeline in Snowflake and dbt for our retail business", catalog())
    assert i.specializations == () and i.keywords == "data pipeline snowflake dbt retail business"
    i = ai.keyword_intent("Underwater basket weaving lessons", catalog())
    assert i.specializations == () and i.engagement_type is None and i.jurisdiction is None


@pytest.mark.unit
async def test_ai_problems_never_reach_the_buyer(monkeypatch):
    async def broken(text, cat):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(ai, "_claude_intent", broken)
    i = await ai.extract_search_intent("fractional CFO", catalog())
    assert i.source == "fallback:keyword" and i.specializations == ("fractional-cfo",)


@pytest.mark.unit
async def test_without_a_key_claude_is_not_called():
    assert await ai._claude_intent("anything", catalog()) is None  # ai_provider defaults to offline


@pytest.mark.unit
async def test_claude_output_is_checked_against_the_catalog(monkeypatch):
    """Invented slugs, a malformed country code and extra keywords from the model are dropped, not trusted."""
    parsed = ai._IntentOut(specialization_slugs=["fractional-cfo", "made-up-slug"], engagement_type="RETAINER",
                           jurisdiction="germany", verified=["credentials"], keywords="one two three four five six seven")

    class Messages:
        async def parse(self, **kwargs):
            assert "<buyer_request>" in kwargs["messages"][0]["content"]  # the buyer's text is fenced as data
            return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)

    class Client:
        def __init__(self, **kwargs):
            self.messages = Messages()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    fake = SimpleNamespace(AsyncAnthropic=Client, APIError=Exception)
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake)
    configured = Settings(_env_file=None, ai_provider="anthropic", anthropic_api_key="test-key")
    monkeypatch.setattr(ai, "get_settings", lambda: configured)
    monkeypatch.setattr(claude, "get_settings", lambda: configured)
    i = await ai.extract_search_intent("an ongoing fractional CFO", catalog())
    assert i.source.startswith("ai:") and i.specializations == ("fractional-cfo",) and i.engagement_type == "RETAINER"
    assert i.jurisdiction is None and i.verified == ("credentials",) and i.keywords == "one two three four five six"


# ---- Integration ---------------------------------------------------------------------------------------------------

async def test_described_need_becomes_filters_that_find_the_right_people(client, make_user, drain):
    u, pro = await publish(client, make_user, drain, "tia", headline="Tax adviser", primary="transfer-pricing", served=("GB",))
    r = await client.post(I, json={"text": "Transfer pricing documentation for our UK subsidiary"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filters"]["spec"] == ["transfer-pricing"] and body["filters"]["jurisdiction"] == "GB"
    assert body["source"] == "fallback:keyword" and "Specialization: Transfer Pricing" in body["reasons"]

    f = body["filters"]
    found = (await client.get(URL, params={"spec": ",".join(f["spec"]), "jurisdiction": f["jurisdiction"]})).json()["items"]
    assert pro["id"] in [x["professionalId"] for x in found]

    assert (await client.post(I, json={"text": "hi"})).status_code == 422  # too short to mean anything


async def test_describe_has_its_own_tighter_budget(client, monkeypatch):
    shared = ratelimit.MemoryBuckets()
    monkeypatch.setattr(ratelimit, "get_buckets", lambda: shared)
    monkeypatch.setattr(search_api, "get_settings", lambda: Settings(_env_file=None, rate_limit_enabled=True))
    monkeypatch.setattr(search_api, "INTENT_LIMIT", (60, 2))
    codes = [(await client.post(I, json={"text": "fractional CFO"})).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
