"""Operations overview: real platform counts, staff only."""

from __future__ import annotations


async def test_overview_counts_and_access(client, make_user, drain):
    await make_user("bea")
    pro = await make_user("pia", account_type="PROFESSIONAL")
    await client.post("/v1/professionals", headers=pro.h, json={})
    await drain()
    await client.post("/v1/verification/cases", headers=pro.h, json={
        "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL",
        "subjectId": (await client.get("/v1/professionals/me", headers=pro.h)).json()["id"]})

    assert (await client.get("/v1/admin/overview", headers=pro.h)).status_code == 403
    admin = await make_user("admin", platform_roles=("PLATFORM_ADMIN",))
    assert (await client.get("/v1/admin/overview", headers=admin.h)).json()["code"] == "STEP_UP_REQUIRED"  # staff need MFA
    await admin.step_up()
    o = (await client.get("/v1/admin/overview", headers=admin.h)).json()
    assert o["accounts"]["total"] == 3 and o["accounts"]["buyers"] == 2 and o["accounts"]["professionals"] == 1
    assert o["professionalProfiles"] == {"total": 1, "published": 0}
    assert o["verification"] == {"open": 1, "overdue": 0}
