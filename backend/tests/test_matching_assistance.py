"""Advisory suggestions are explicitly applied and restricted to the live taxonomy."""
from zoikorum.domains.ai import providers
from zoikorum.domains.ai.models import PromptVersion

async def test_matching_suggestions_validate_provider_output_and_fall_back(client, make_user, sf, monkeypatch):
    user = await make_user('matching-buyer')
    path = '/v1/ai/match-intent'
    assert (await client.post(path, json={"query": "fractional CFO"})).status_code == 401
    fallback = await client.post(path, headers=user.h, json={"query": "fractional CFO"})
    assert fallback.status_code == 200, fallback.text
    assert fallback.json()['fallbackUsed']
    assert any(s['slug'] == 'fractional-cfo' for s in fallback.json()['specializations'])
    async with sf() as session, session.begin():
        session.add(PromptVersion(prompt_key='match-intent', version=1, target_model='offline:v1',
            instructions='Return only approved taxonomy slugs in a specializations JSON array.',
            golden_tests=[], status='APPROVED'))
    class Partner:
        output = '{"specializations": ["fractional-cfo"]}'
        async def generate(self, instructions, text):
            return self.output
    partner = Partner()
    monkeypatch.setattr(providers, 'provider', lambda: partner)
    valid = await client.post(path, headers=user.h, json={"query": "fractional CFO"})
    assert not valid.json()['fallbackUsed']
    assert [s['slug'] for s in valid.json()['specializations']] == ['fractional-cfo']
    for output in ['{"specializations":["invented-license"]}', '{"specializations":[],"minimumTier":"C"}', 'not json']:
        partner.output = output
        invalid = await client.post(path, headers=user.h, json={"query": "fractional CFO"})
        assert invalid.status_code == 200 and invalid.json()['fallbackUsed'], invalid.text
        assert all(s['slug'] != 'invented-license' for s in invalid.json()['specializations'])
    assert (await client.post(path, headers=user.h, json={"query": 'x'*201})).status_code == 422
