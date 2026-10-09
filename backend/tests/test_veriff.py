"""Identity checks with Veriff (and the development simulator) through the hosted-verification integration: hosted
session, signed webhooks, fetching the answer on return, retakes, and the rule that only an approval verifies
automatically - a decline still goes to a compliance officer, who can decide from the partner's dashboard."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from test_verification import case_of, officer
from prodsettings import PRODUCTION
from zoikorum.config import Settings
from zoikorum.domains.verification import integration
from zoikorum.domains.verification.providers import VeriffProvider

SECRET = "veriff-test-secret"
WEBHOOK = "/v1/verification/webhooks/veriff"


def sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


class VeriffStation:
    """Stands in for stationapi.veriff.com and checks each request is authenticated and signed."""

    def __init__(self):
        self.decision: dict | None = None
        self.sessions = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["x-auth-client"] == "veriff-key"
        if request.method == "POST" and request.url.path == "/v1/sessions":
            assert request.headers["x-hmac-signature"] == sign(request.content)
            self.sessions += 1
            vendor = json.loads(request.content)["verification"]["vendorData"]
            return httpx.Response(201, json={"status": "success", "verification": {
                "id": f"sess-{self.sessions}", "url": f"https://alchemy.veriff.com/v/{vendor}-{self.sessions}"}})
        ref = request.url.path.split("/")[3]
        assert request.headers["x-hmac-signature"] == sign(ref.encode())
        return httpx.Response(200, json={"status": "success", "verification": self.decision})


@pytest.fixture
def veriff(monkeypatch):
    station = VeriffStation()
    settings = Settings(_env_file=None, env="test", verification_provider="veriff", veriff_api_key="veriff-key",
                        veriff_shared_secret=SECRET, veriff_base_url="https://veriff.test")
    monkeypatch.setattr(integration, "get_settings", lambda: settings)
    monkeypatch.setattr(integration, "VeriffProvider", lambda s: VeriffProvider(s, httpx.MockTransport(station.handle)))
    return station


@pytest.fixture
def simulated(monkeypatch):
    settings = Settings(_env_file=None, env="test", verification_provider="simulated")
    monkeypatch.setattr(integration, "get_settings", lambda: settings)


async def identity_case(client, make_user, drain, name="vera"):
    u = await make_user(name, account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await drain()
    await u.step_up()
    case = (await client.post("/v1/verification/cases", headers=u.h,
                              json={"verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    return u, pro, case


async def webhook(client, payload: dict, signature: str | None = None):
    body = json.dumps(payload).encode()
    return await client.post(WEBHOOK, content=body, headers={"x-hmac-signature": signature or sign(body)})


async def test_veriff_approval_verifies_identity_automatically(client, make_user, drain, veriff):
    u, pro, case = await identity_case(client, make_user, drain)
    config = (await client.get("/v1/verification/configuration", headers=u.h)).json()
    assert config == {"provider": "veriff", "hostedIdentity": True, "configured": True, "partnerName": "Veriff"}

    start = f"/v1/verification/cases/{case['id']}/hosted-session"
    first = (await client.post(start, headers=u.h)).json()
    assert first["url"] == f"https://alchemy.veriff.com/v/{case['id']}-1" and first["provider"] == "veriff"
    assert (await client.post(start, headers=u.h)).json()["url"] == first["url"] and veriff.sessions == 1  # resumed

    assert (await webhook(client, {"id": "sess-1", "action": "submitted"}, "0" * 64)).status_code == 401
    assert (await webhook(client, {"id": "sess-1", "action": "submitted", "vendorData": case["id"]})).status_code == 200
    assert (await case_of(client, u, pro, "IDENTITY"))["status"] == "IN_REVIEW"

    decision = {"status": "success", "verification": {"id": "sess-1", "status": "approved", "code": 9001, "vendorData": case["id"]}}
    assert (await webhook(client, decision)).json()["duplicate"] is False
    assert (await webhook(client, decision)).json()["duplicate"] is True  # Veriff retries deliveries
    checked = await case_of(client, u, pro, "IDENTITY")
    assert checked["status"] == "VERIFIED" and checked["hostedStatus"] == "approved" and checked["hostedProvider"] == "veriff"


async def test_answer_is_fetched_when_the_webhook_cannot_arrive(client, make_user, drain, veriff):
    u, pro, case = await identity_case(client, make_user, drain)
    await client.post(f"/v1/verification/cases/{case['id']}/hosted-session", headers=u.h)
    refresh = f"/v1/verification/cases/{case['id']}/hosted-refresh"
    assert (await client.post(refresh, headers=u.h)).json()["status"] == "PENDING"  # Veriff has not decided yet
    veriff.decision = {"id": "sess-1", "status": "approved", "code": 9001}
    assert (await client.post(refresh, headers=u.h)).json()["status"] == "VERIFIED"


async def test_a_decline_goes_to_a_compliance_officer(client, make_user, drain, veriff):
    u, pro, case = await identity_case(client, make_user, drain)
    await client.post(f"/v1/verification/cases/{case['id']}/hosted-session", headers=u.h)
    await webhook(client, {"verification": {"id": "sess-1", "status": "declined", "code": 9102, "reason": "Physical document not used"}})
    checked = await case_of(client, u, pro, "IDENTITY")
    assert checked["status"] == "IN_REVIEW" and checked["hostedReason"] == "Physical document not used"

    o = await officer(make_user)
    (item,) = [q for q in (await client.get("/v1/verification/review-queue", headers=o.h)).json()["items"]
               if q["verificationType"] == "IDENTITY"]
    assert item["hostedProvider"] == "veriff" and item["hostedStatus"] == "declined"
    # The photos are in Veriff's dashboard, so the officer can decide without an upload here.
    r = await client.post(f"/v1/verification/cases/{case['id']}/decision", headers=o.h,
                          json={"decision": "VERIFIED", "reasonCode": "PARTNER_DASHBOARD_REVIEW"})
    assert r.json()["status"] == "VERIFIED"


async def test_a_retake_opens_a_new_session(client, make_user, drain, veriff):
    u, pro, case = await identity_case(client, make_user, drain)
    start = f"/v1/verification/cases/{case['id']}/hosted-session"
    await client.post(start, headers=u.h)
    await webhook(client, {"verification": {"id": "sess-1", "status": "resubmission_requested", "reason": "Blurry"}})
    checked = await case_of(client, u, pro, "IDENTITY")
    assert checked["status"] == "NEEDS_INFO" and "try again" in checked["publicReason"]
    second = (await client.post(start, headers=u.h)).json()
    assert second["url"].endswith("-2") and veriff.sessions == 2
    await webhook(client, {"verification": {"id": "sess-2", "status": "approved"}})
    assert (await case_of(client, u, pro, "IDENTITY"))["status"] == "VERIFIED"
    # A late answer for the old session changes nothing.
    assert (await webhook(client, {"verification": {"id": "sess-1", "status": "declined"}})).status_code == 200
    assert (await case_of(client, u, pro, "IDENTITY"))["status"] == "VERIFIED"


async def test_development_simulator(client, make_user, drain, simulated):
    u, pro, case = await identity_case(client, make_user, drain)
    simulate = f"/v1/verification/cases/{case['id']}/hosted-simulate"
    assert (await client.post(simulate, headers=u.h, json={"status": "approved"})).json()["code"] == "HOSTED_NOT_STARTED"
    started = (await client.post(f"/v1/verification/cases/{case['id']}/hosted-session", headers=u.h)).json()
    assert started["url"] is None and started["provider"] == "simulated"
    stranger = await make_user("sam")
    assert (await client.post(simulate, headers=stranger.h, json={"status": "approved"})).status_code == 404
    assert (await client.post(simulate, headers=u.h, json={"status": "approved"})).json()["status"] == "VERIFIED"


async def test_simulator_is_refused_unless_switched_on(client, make_user, drain):
    u, pro, case = await identity_case(client, make_user, drain)
    r = await client.post(f"/v1/verification/cases/{case['id']}/hosted-simulate", headers=u.h, json={"status": "approved"})
    assert r.status_code == 404


def test_simulated_partner_is_refused_outside_development():
    with pytest.raises(ValueError, match="simulated"):
        Settings(_env_file=None, **PRODUCTION, verification_provider="simulated")
