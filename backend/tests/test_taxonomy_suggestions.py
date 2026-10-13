"""More categories than Finance & Accounting, and "Can't find yours?": AI/keyword matching, suggestions, admin review."""

from __future__ import annotations

import pytest

from test_search import publish
from zoikorum.domains.ai import specializations as ai
from zoikorum.domains.marketplace.taxonomy_data import default_taxonomy_rows

T = "/v1/taxonomy"


def catalog() -> list[ai.CatalogEntry]:
    rows = default_taxonomy_rows()
    by_id = {r["id"]: r for r in rows}
    out = []
    for r in rows:
        if r["level"] == "SPECIALIZATION":
            g = by_id[r["parent_id"]]
            c = by_id[g["parent_id"]]
            out.append(ai.CatalogEntry(r["slug"], r["name"], c["slug"], c["name"], g["slug"], g["name"]))
    return out


# ---- Unit: data and the keyword fallback ---------------------------------------------------------------------------

@pytest.mark.unit
def test_taxonomy_covers_more_than_finance_with_unique_slugs():
    rows = default_taxonomy_rows()
    cats = [r["name"] for r in rows if r["level"] == "CATEGORY"]
    assert cats[0] == "Finance & Accounting" and "Technology & Software Development" in cats and len(cats) == 6
    slugs = [r["slug"] for r in rows]
    assert len(slugs) == len(set(slugs))
    legal = [r for r in rows if r["category_slug"] == "legal-services" and r["level"] == "SPECIALIZATION"]
    assert legal and all(r["requires_credential"] for r in legal)  # practising law needs a licence


@pytest.mark.unit
def test_keyword_matching_finds_the_closest_specializations():
    m = ai.keyword_match("I build machine learning models for invoice extraction", catalog())
    assert m.slugs[0] == "ai-machine-learning-engineering" and m.source == "fallback:keyword" and m.draft is None
    m = ai.keyword_match("Underwater basket weaving instruction", catalog())
    assert m.draft is not None and m.draft.name.startswith("Underwater basket weaving")


@pytest.mark.unit
async def test_ai_problems_never_reach_the_user(monkeypatch):
    async def broken(text, cat):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(ai, "_claude_match", broken)
    m = await ai.match_specializations("data engineering pipelines", catalog())
    assert m.source == "fallback:keyword" and "data-engineering" in m.slugs


@pytest.mark.unit
async def test_without_a_key_claude_is_not_called():
    assert await ai._claude_match("anything", catalog()) is None  # ai_provider defaults to offline


# ---- Integration: suggest, submit, admin decision ------------------------------------------------------------------

async def test_the_public_taxonomy_lists_every_category(client):
    cats = (await client.get(T)).json()["categories"]
    assert [c["slug"] for c in cats][:2] == ["finance-and-accounting", "technology-and-software-development"]


async def test_suggestions_are_reviewed_before_they_go_live(client, make_user, drain):
    u, pro = await publish(client, make_user, drain, "ann", headline="ML engineer", primary="finance-process-automation")
    r = await client.post(f"{T}/suggest", headers=u.h, json={"text": "I build machine learning models"})
    assert r.status_code == 200 and r.json()["matches"][0]["slug"] == "ai-machine-learning-engineering"

    body = {"text": "I build RPA bots for accounts payable", "name": "Robotic Process Automation", "groupSlug": "software-development",
            "description": "RPA bots for finance back-office work", "source": "fallback:keyword"}
    s = (await client.post(f"{T}/suggestions", headers=u.h, json=body)).json()
    assert s["status"] == "PENDING" and s["categorySlug"] == "technology-and-software-development"
    dup = await client.post(f"{T}/suggestions", headers=u.h, json={**body, "name": "Data Engineering"})
    assert dup.json()["code"] == "SPECIALIZATION_EXISTS"  # already in the list: pick it instead
    assert (await client.get(f"/v1/professionals/{pro['id']}")).json()["pendingSpecializations"] == ["Robotic Process Automation"]
    buyer = await make_user("bea")
    assert (await client.post(f"{T}/suggestions", headers=buyer.h, json=body)).json()["code"] == "PROFILE_REQUIRED"
    assert (await client.get("/v1/admin/taxonomy/suggestions", headers=u.h)).status_code == 403

    admin = await make_user("ada", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    (queued,) = (await client.get("/v1/admin/taxonomy/suggestions", headers=admin.h)).json()
    assert queued["professionalName"] == "Ann"
    r = await client.post(f"/v1/admin/taxonomy/suggestions/{queued['id']}/decision", headers=admin.h, json={"action": "APPROVE"})
    assert r.json()["status"] == "APPROVED" and r.json()["resolvedSlug"] == "robotic-process-automation"
    await drain()

    names = [s["name"] for c in (await client.get(T)).json()["categories"] for g in c["groups"] for s in g["specializations"]]
    assert "Robotic Process Automation" in names  # live for everyone
    me = (await client.get("/v1/professionals/me", headers=u.h)).json()
    assert "robotic-process-automation" in [s["slug"] for s in me["specializations"]] and me["pendingSpecializations"] == []


async def test_admin_can_merge_or_reject(client, make_user, drain):
    u, pro = await publish(client, make_user, drain, "ann", headline="Data person", primary="finance-process-automation")
    admin = await make_user("ada", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    a = (await client.post(f"{T}/suggestions", headers=u.h, json={"text": "ETL pipelines", "name": "ETL Pipelines"})).json()
    b = (await client.post(f"{T}/suggestions", headers=u.h, json={"text": "Astrology for CFOs", "name": "Financial Astrology"})).json()
    url = "/v1/admin/taxonomy/suggestions/{}/decision"
    r = await client.post(url.format(a["id"]), headers=admin.h, json={"action": "MERGE", "mergeSlug": "data-engineering",
                                                                      "note": "Covered by Data Engineering"})
    assert r.json()["status"] == "MERGED"
    assert (await client.post(url.format(b["id"]), headers=admin.h, json={"action": "REJECT"})).json()["code"] == "NOTE_REQUIRED"
    r = await client.post(url.format(b["id"]), headers=admin.h, json={"action": "REJECT", "note": "Not a professional service we list"})
    assert r.json()["status"] == "REJECTED"
    await drain()
    mine = (await client.get(f"{T}/suggestions/mine", headers=u.h)).json()
    assert {m["status"] for m in mine} == {"MERGED", "REJECTED"}
    me = (await client.get("/v1/professionals/me", headers=u.h)).json()
    assert "data-engineering" in [s["slug"] for s in me["specializations"]]
