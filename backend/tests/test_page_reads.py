"""Smoke coverage for the data reads behind each account's application pages."""
import pytest


@pytest.mark.parametrize("role", ["BUYER", "PROFESSIONAL", "ENTERPRISE", "FIRM"])
async def test_application_page_reads_do_not_raise_server_errors(client, make_user, drain, role):
    user = await make_user("page-user", account_type=role,
                           organization="Page smoke organisation" if role in ("ENTERPRISE", "FIRM") else None)
    if role == "PROFESSIONAL":
        created = await client.post("/v1/professionals", headers=user.h, json={})
        assert created.status_code == 201, created.text
    await drain()
    if role in ("ENTERPRISE", "FIRM"):
        await user.step_up()
    shared = ["/v1/me", "/v1/organizations/mine", "/v1/threads", "/v1/threads/summary",
              "/v1/notifications", "/v1/notifications/unread-count", "/v1/notification-preferences",
              "/v1/contracts", "/v1/proposal-requests", "/v1/proposal-requests/summary",
              "/v1/disputes", "/v1/enforcement-cases", "/v1/payments/configuration",
              "/v1/verification/configuration", "/v1/search/professionals"]
    for url in shared:
        response = await client.get(url, headers=user.h)
        assert response.status_code == 200, f"{role} {url}: {response.status_code} {response.text}"
    orgs = (await client.get("/v1/organizations/mine", headers=user.h)).json()
    for org in orgs:
        for url in ["/v1/payments/invoices", "/v1/payments/charges", "/v1/payments/refunds", "/v1/dashboards/buyer", "/v1/reports/buyer"]:
            response = await client.get(url, headers=user.h, params={"organizationId": org["id"]})
            assert response.status_code == 200, f"{role} {url}: {response.text}"
        for url in ["/v1/policy/profiles", "/v1/policy/approvals", "/v1/policy/exceptions"]:
            response = await client.get(url, headers=user.h, params={"orgId": org["id"]})
            assert response.status_code == 200, f"{role} {url}: {response.text}"
    if role == "PROFESSIONAL":
        for url in ["/v1/professionals/me", "/v1/payments/earnings/me", "/v1/dashboards/professional", "/v1/reports/professional"]:
            response = await client.get(url, headers=user.h)
            assert response.status_code == 200, f"{url}: {response.text}"
    if role == "FIRM":
        response = await client.get("/v1/firms/mine", headers=user.h)
        assert response.status_code == 200, response.text


async def test_staff_page_reads_do_not_raise_server_errors(client, make_user, drain):
    user = await make_user("page-staff", platform_roles=("PLATFORM_ADMIN", "COMPLIANCE_OFFICER", "FINANCIAL_OPS", "AI_SAFETY_REVIEWER"))
    await drain()
    await user.step_up()
    for url in ["/v1/admin/overview", "/v1/admin/enforcement-cases", "/v1/admin/dead-letters",
                "/v1/admin/duplicate-accounts", "/v1/admin/taxonomy/suggestions",
                "/v1/verification/review-queue", "/v1/verification/appeals",
                "/v1/payments/reconciliations", "/v1/analytics/marketplace-health",
                "/v1/ai/prompts", "/v1/ai/inferences", "/v1/audit/records"]:
        response = await client.get(url, headers=user.h)
        assert response.status_code == 200, f"{url}: {response.status_code} {response.text}"
