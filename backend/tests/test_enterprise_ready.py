"""Enterprise Ready: apply when the requirements hold, attest to security practice, a compliance officer decides,
and the designation shows on the profile and in search."""

from __future__ import annotations

from test_trust import published_pro, verify

ME = "/v1/professionals/me/enterprise"


async def test_apply_review_and_show_enterprise_ready(client, make_user, drain):
    u, pro = await published_pro(client, make_user, drain)
    status = (await client.get(ME, headers=u.h)).json()
    assert status["status"] == "NONE" and not all(r["met"] for r in status["requirements"])
    attest = {"attestation": {i["key"]: True for i in status["attestationItems"]}}
    r = await client.post(f"{ME}/apply", headers=u.h, json=attest)
    assert r.status_code == 409 and r.json()["code"] == "MFA_REQUIRED"  # two-step sign-in comes first
    await u.enable_mfa()
    r = await client.post(f"{ME}/apply", headers=u.h, json=attest)
    assert r.json()["code"] == "ENTERPRISE_REQUIREMENTS_NOT_MET" and "Green trust light" in r.json()["detail"]

    await verify(client, make_user, u, pro, "IDENTITY")
    await verify(client, make_user, u, pro, "JURISDICTION", jurisdiction="US")
    await drain()
    await u.step_up()
    partial = {"attestation": {**attest["attestation"], "breachNotice": False}}
    assert (await client.post(f"{ME}/apply", headers=u.h, json=partial)).json()["code"] == "ATTESTATION_INCOMPLETE"
    applied = (await client.post(f"{ME}/apply", headers=u.h, json=attest)).json()
    assert applied["status"] == "PENDING" and applied["attestation"]["version"] == applied["attestationVersion"]

    officer = await make_user("ent-officer", platform_roles=("COMPLIANCE_OFFICER",))
    await officer.step_up()
    assert (await client.get("/v1/professionals/admin/enterprise-applications", headers=u.h)).status_code == 403
    queue = (await client.get("/v1/professionals/admin/enterprise-applications", headers=officer.h)).json()
    assert [q["professionalId"] for q in queue] == [pro["id"]]
    decided = (await client.post(f"/v1/professionals/{pro['id']}/enterprise/decision", headers=officer.h,
                                 json={"approve": True, "reason": "Requirements and attestation in order."})).json()
    assert decided["status"] == "READY"
    await drain()

    public = (await client.get(f"/v1/professionals/{pro['id']}")).json()
    assert public["enterprise"]["enterpriseReady"] is True and "Two-step sign-in" in public["enterprise"]["signals"]
    found = (await client.get("/v1/search/professionals", params={"enterpriseReady": "true"})).json()
    assert [i["professionalId"] for i in found["items"]] == [pro["id"]] and found["items"][0]["enterpriseReady"] is True
    titles = [n["title"] for n in (await client.get("/v1/notifications", headers=u.h)).json()["items"]]
    assert "Enterprise readiness decided" in titles


def test_mfa_gate_refuses_without_two_step():
    import pytest
    from zoikorum.domains.professional.enterprise import require_mfa
    from zoikorum.shared.errors import Conflict
    off = [{"key": "tierA", "met": True}, {"key": "twoStep", "met": False}]
    with pytest.raises(Conflict) as e:
        require_mfa(off)
    assert e.value.code == "MFA_REQUIRED" and "two-step" in e.value.detail
    with pytest.raises(Conflict):
        require_mfa(off, own=False)
    require_mfa([{"key": "twoStep", "met": True}])
