from zoikorum.domains.search.opensearch import reciprocal_rank_fusion

def test_rrf_combines_rankings_and_deduplicates_each_source():
    ids, scores = reciprocal_rank_fusion([['lexical', 'both', 'lexical'], ['both', 'semantic']])
    assert ids[0] == 'both'
    assert scores['lexical'] == 1 / 61
    assert scores['both'] == 1 / 62 + 1 / 61

def test_rrf_orders_ties_deterministically():
    assert reciprocal_rank_fusion([['b'], ['a']])[0] == ['a', 'b']


async def test_external_candidates_cannot_bypass_publish_or_jurisdiction(client, make_user, drain, monkeypatch):
    from test_search import publish, URL
    from zoikorum.domains.search import opensearch
    user, pro = await publish(client, make_user, drain, 'semantic-profile', headline='Financial analyst', primary='fractional-cfo', served=('US',))
    async def candidates(query, limit):
        return [pro['id']], {pro['id']: 1.0}
    monkeypatch.setattr(opensearch, 'configured', lambda: True)
    monkeypatch.setattr(opensearch, 'hybrid_search', candidates)
    result = await client.get(URL, params={'q': 'a semantically related term absent from the profile'})
    assert result.status_code == 200, result.text
    assert [r['professionalId'] for r in result.json()['items']] == [pro['id']]
    excluded = await client.get(URL, params={'q': 'semantic request', 'jurisdiction': 'GB'})
    assert excluded.json()['items'] == []
    await client.post('/v1/professionals/me/unpublish', headers=user.h)
    # No drain: a stale external index and a stale SQL projection still must not reveal this profile.
    hidden = await client.get(URL, params={'q': 'semantic request'})
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()['items'] == []
