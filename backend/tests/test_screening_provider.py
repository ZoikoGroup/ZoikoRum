"""Partner evidence cannot automatically clear an unverified profile name."""
import json
import httpx
import pytest
from zoikorum.config import Settings
from zoikorum.domains.verification.providers import ComplyAdvantageProvider, ScreeningProvider, ManualProvider
from zoikorum.shared.errors import ServiceUnavailable

@pytest.mark.parametrize("hits", [0, 3])
async def test_live_screening_records_evidence_but_requires_human_review(hits):
    def handle(request):
        assert str(request.url) == "https://api.complyadvantage.com/searches"
        assert request.headers["Authorization"] == "Token test-key"
        body = json.loads(request.content)
        assert body["search_term"] == "Example Person"
        assert body["filters"]["types"] == ["sanction", "warning", "pep"]
        return httpx.Response(200, json={"status": "success", "content": {"data": {"ref": "screen-reference", "total_hits": hits}}})
    settings = Settings(_env_file=None, complyadvantage_api_key="test-key")
    adapter = ScreeningProvider(ManualProvider(), ComplyAdvantageProvider(settings, httpx.MockTransport(handle)))
    details = {"name": "Example Person"}
    assert await adapter.check("RESTRICTIONS", details) == "REVIEW"
    assert details["_providerHits"] == hits
    assert details["_providerReference"] == "screen-reference"
    assert await adapter.check("IDENTITY", {}) == "REVIEW"

@pytest.mark.parametrize("status,body", [(429, {}), (200, {}), (200, {"status": "success", "content": {"data": {"ref": "ref", "total_hits": -1}}})])
async def test_partner_failures_never_clear_screening(status, body):
    settings = Settings(_env_file=None, complyadvantage_api_key="test-key")
    adapter = ComplyAdvantageProvider(settings, httpx.MockTransport(lambda request: httpx.Response(status, json=body)))
    with pytest.raises(ServiceUnavailable):
        await adapter.check("RESTRICTIONS", {"name": "Example Person"})

def test_missing_credentials_fail_closed():
    with pytest.raises(ServiceUnavailable):
        ComplyAdvantageProvider(Settings(_env_file=None))


async def test_screening_evidence_is_visible_only_to_staff(client, make_user, drain, monkeypatch):
    from zoikorum.domains.verification import service
    class Partner:
        async def check(self, verification_type, details):
            if verification_type == 'RESTRICTIONS':
                details.update({'_providerScreening': 'COMPLYADVANTAGE', '_providerHits': 2, '_providerReference': 'private-screening-reference'})
            return 'REVIEW'
    monkeypatch.setattr(service, 'get_provider', lambda: Partner())
    owner = await make_user('screening-owner', account_type='PROFESSIONAL')
    profile = await client.post('/v1/professionals', headers=owner.h, json={})
    assert profile.status_code == 201, profile.text
    await drain()
    staff = await make_user('screening-reviewer', platform_roles=('COMPLIANCE_OFFICER',))
    await staff.step_up()
    path = '/v1/verification/review-queue'
    assert (await client.get(path, headers=owner.h)).status_code == 403
    queue = await client.get(path, headers=staff.h)
    assert queue.status_code == 200, queue.text
    check = next(c for c in queue.json()['items'] if c['verificationType'] == 'RESTRICTIONS')
    assert check['screeningEvidence']['Hits'] == 2
    assert check['screeningEvidence']['Reference'] == 'private-screening-reference'
    own = await client.get('/v1/verification/cases/' + check['id'], headers=owner.h)
    assert own.status_code == 200
    assert 'private-screening-reference' not in own.text
