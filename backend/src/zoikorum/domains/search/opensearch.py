"""Optional lexical/neural retrieval. PostgreSQL remains authoritative for eligibility."""
from __future__ import annotations
import asyncio
import re
from urllib.parse import quote, urlsplit
import httpx
from zoikorum.config import get_settings
from zoikorum.shared.errors import ServiceUnavailable


def reciprocal_rank_fusion(rankings, constant=60):
    scores = {}
    for ranking in rankings:
        seen = set()
        for rank, item in enumerate(ranking, 1):
            if item not in seen:
                scores[item] = scores.get(item, 0.0) + 1 / (constant + rank)
                seen.add(item)
    return sorted(scores, key=lambda item: (-scores[item], item)), scores


def configured():
    settings = get_settings()
    if settings.search_provider != 'opensearch':
        return False
    url = urlsplit(settings.opensearch_url or '')
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
        raise ServiceUnavailable('Configure a trusted OpenSearch URL', code='SEARCH_NOT_CONFIGURED')
    if settings.env not in ('local', 'development', 'test') and url.scheme != 'https':
        raise ServiceUnavailable('Production OpenSearch requires HTTPS', code='SEARCH_NOT_CONFIGURED')
    if not settings.opensearch_model_id or not settings.opensearch_ingest_pipeline or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', settings.opensearch_index):
        raise ServiceUnavailable('Configure the deployed embedding model, ingestion pipeline and index', code='SEARCH_NOT_CONFIGURED')
    return True


async def request(method, path, body=None, params=None):
    settings = get_settings()
    auth = (settings.opensearch_username, settings.opensearch_password or '') if settings.opensearch_username else None
    try:
        async with httpx.AsyncClient(timeout=settings.opensearch_timeout_seconds, auth=auth) as client:
            result = await client.request(method, settings.opensearch_url.rstrip('/') + '/' + path,
                                          json=body, params=params)
            if method == 'DELETE' and result.status_code == 404:
                return {}
            result.raise_for_status()
            return result.json()
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise ServiceUnavailable('Search provider could not complete the operation', code='SEARCH_PROVIDER_UNAVAILABLE') from error


async def index_professional_profile(profile_id, document):
    if not configured():
        return
    settings = get_settings()
    path = settings.opensearch_index + '/_doc/' + quote(str(profile_id), safe='')
    if document is None or not document.get('visible'):
        await request('DELETE', path)
        return
    await request('PUT', path, document, {'pipeline': settings.opensearch_ingest_pipeline})


async def hybrid_search(query, limit=500):
    if not configured():
        return [], {}
    settings = get_settings()
    # The configured pipeline embeds `text` into `embedding` using this same deployed model.
    bodies = [
        {'size': limit, '_source': False, 'query': {'bool': {'must': {'match': {'text': query}}, 'filter': {'term': {'visible': True}}}}},
        {'size': limit, '_source': False, 'query': {'neural': {'embedding': {'query_text': query,
          'model_id': settings.opensearch_model_id, 'k': limit, 'filter': {'term': {'visible': True}}}}}},
    ]
    responses = await asyncio.gather(*(request('POST', settings.opensearch_index + '/_search', body) for body in bodies))
    try:
        rankings = [[hit['_id'] for hit in response['hits']['hits']] for response in responses]
    except (KeyError, TypeError) as error:
        raise ServiceUnavailable('Search provider returned an invalid result', code='SEARCH_PROVIDER_UNAVAILABLE') from error
    return reciprocal_rank_fusion(rankings)


async def bootstrap():
    if not configured():
        raise ServiceUnavailable('Enable and configure OpenSearch first', code='SEARCH_NOT_CONFIGURED')
    settings = get_settings()
    await request('PUT', '_ingest/pipeline/' + quote(settings.opensearch_ingest_pipeline, safe=''), {
        'description': 'Embed published professional text', 'processors': [{'text_embedding': {
            'model_id': settings.opensearch_model_id, 'field_map': {'text': 'embedding'}}}]})
    simulation = await request('POST', '_ingest/pipeline/' + quote(settings.opensearch_ingest_pipeline, safe='') + '/_simulate',
        {'docs': [{'_source': {'text': 'Professional services', 'visible': True}}]})
    try:
        vector = simulation['docs'][0]['doc']['_source']['embedding']
        if len(vector) != settings.opensearch_embedding_dimension:
            raise ValueError('dimension mismatch')
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise ServiceUnavailable('The embedding model did not produce the configured dimension', code='SEARCH_MODEL_INVALID') from error
    # Never silently replace the mapping of an existing index: operators must version incompatible models.
    try:
        mapping = await request('GET', settings.opensearch_index + '/_mapping')
    except ServiceUnavailable as error:
        if not isinstance(error.__cause__, httpx.HTTPStatusError) or error.__cause__.response.status_code != 404:
            raise
        await request('PUT', settings.opensearch_index, {
            'settings': {'index.knn': True, 'default_pipeline': settings.opensearch_ingest_pipeline},
            'mappings': {'properties': {
                'visible': {'type': 'boolean'}, 'text': {'type': 'text'},
                'embedding': {'type': 'knn_vector', 'dimension': settings.opensearch_embedding_dimension,
                  'method': {'name': 'hnsw', 'space_type': 'cosinesimil', 'engine': 'lucene'}}}}})
    else:
        vector = mapping.get(settings.opensearch_index, {}).get('mappings', {}).get('properties', {}).get('embedding', {})
        if vector.get('type') != 'knn_vector' or vector.get('dimension') != settings.opensearch_embedding_dimension:
            raise ServiceUnavailable('Existing index mapping does not match the configured embedding model; use a versioned index', code='SEARCH_INDEX_INCOMPATIBLE')
    return {'index': settings.opensearch_index, 'configured': True}
