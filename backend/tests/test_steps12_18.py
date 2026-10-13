"""Security boundaries and real delivery/reporting flows for the remaining product steps."""
import hashlib
import hmac
import uuid
from datetime import timedelta
from sqlalchemy import select, text
from zoikorum.shared import clock
from zoikorum.shared.crypto import canonical_json
from zoikorum.shared.report_pdf import render_pdf
from zoikorum.domains.notification import providers
from zoikorum.shared.errors import ValidationFailed
import pytest
from sqlalchemy.exc import DBAPIError


def test_reviews_reject_whitespace_and_preserve_valid_text():
    from pydantic import ValidationError
    from zoikorum.domains.review.api import ReviewIn
    with pytest.raises(ValidationError):
        ReviewIn(rating=5, comment=' ' * 30)
    assert ReviewIn(rating=4, comment='  Delivered the agreed scope.  ').comment == 'Delivered the agreed scope.'


def test_dashboard_signature_actions_follow_the_current_contract_version():
    from types import SimpleNamespace
    from zoikorum.domains.analytics.service import summarize
    from zoikorum.shared.event_catalog import E
    rows = []
    def event(kind, **payload):
        rows.append(SimpleNamespace(event_type=kind, payload={'contractId': 'agreement', **payload}, aggregate_id='agreement', occurred_at=clock.now()))
    event(E.CONTRACT_GENERATED)
    assert summarize(rows)['pendingActions'] == 1
    assert summarize(rows, role='professional')['pendingActions'] == 0
    event(E.CONTRACT_SIGNED, party='BUYER')
    assert summarize(rows)['pendingActions'] == 0
    assert summarize(rows, role='professional')['pendingActions'] == 1
    event(E.CONTRACT_ACTIVATED)
    assert summarize(rows)['activeEngagements'] == 1
    event(E.CONTRACT_AMENDED)
    assert summarize(rows)['pendingActions'] == 1
    assert summarize(rows, role='professional')['pendingActions'] == 0


def test_webhook_destinations_and_pdf():
    for url in ['http://public.example/events', 'https://localhost/events', 'https://u:p@public.example/events', 'https://[broken',
                'https://127.0.0.1/events', 'https://[::1]/events', 'https://169.254.169.254/events']:
        with pytest.raises(ValidationFailed): providers.checked_url(url)
    assert providers.checked_url('https://public.example/events?source=zoikorum').hostname == 'public.example'
    pdf = render_pdf([f'Financial row {i}' for i in range(100)])
    assert pdf.startswith(b'%PDF-') and b'/Count 3' in pdf and pdf.endswith(b'%%EOF\n')


@pytest.mark.unit
async def test_webhook_dns_rebinding_is_blocked_before_connecting(monkeypatch):
    import socket
    def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
    monkeypatch.setattr(providers.socket, 'getaddrinfo', resolve)
    def connect(*args, **kwargs):
        pytest.fail('A mixed public/private DNS response must never connect')
    monkeypatch.setattr(providers.socket, 'create_connection', connect)
    with pytest.raises(ValueError, match='public addresses'):
        await providers.post_webhook('https://public.example/events', b'{}', {})


@pytest.mark.unit
async def test_webhook_connects_to_the_checked_address_with_the_original_tls_hostname(monkeypatch):
    import io
    import socket
    connected, tls_names = [], []
    class Socket:
        def sendall(self, data): pass
        def makefile(self, *args): return io.BytesIO(b'HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n')
        def close(self): pass
    class TLS:
        def wrap_socket(self, raw, *, server_hostname):
            tls_names.append(server_hostname); return raw
    monkeypatch.setattr(providers.socket, 'getaddrinfo', lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443))])
    def connect(address, timeout):
        connected.append(address); return Socket()
    monkeypatch.setattr(providers.socket, 'create_connection', connect)
    monkeypatch.setattr(providers.ssl, 'create_default_context', lambda: TLS())
    status = await providers.post_webhook('https://public.example/events', b'{}', {'Content-Type': 'application/json'})
    assert status == 204 and connected == [('1.1.1.1', 443)] and tls_names == ['public.example']


async def test_notification_preferences_mandatory_security_and_ownership(client, make_user, drain):
    owner, outsider = await make_user('notice-owner'), await make_user('notice-other')
    await drain()
    inbox = (await client.get('/v1/notifications', headers=owner.h)).json()
    assert inbox['items']
    nid = inbox['items'][0]['id']
    assert (await client.post(f'/v1/notifications/{nid}/read', headers=outsider.h)).status_code == 404
    assert (await client.post(f'/v1/notifications/{nid}/read', headers=owner.h)).status_code == 200
    response = await client.put('/v1/notification-preferences', headers=owner.h,
        json={'email': False, 'inApp': False, 'sms': False, 'marketing': False})
    assert response.status_code == 200, response.text
    await owner.enable_mfa(); await drain()
    rows = (await client.get('/v1/notifications', headers=owner.h)).json()['items']
    assert any(r['mandatory'] and 'Two-step' in r['title'] for r in rows)


async def test_webhook_signatures_retry_logs_and_access(client, make_user, drain, sf, monkeypatch):
    owner, outsider = await make_user('webhook-owner'), await make_user('webhook-other')
    await drain(); await owner.refresh(); await owner.step_up()
    org = (await client.get('/v1/organizations/mine', headers=owner.h)).json()[0]
    events = (await client.get('/v1/webhook-event-types', headers=owner.h)).json()
    event_types = [events[0]['eventType']]
    response = await client.post('/v1/webhook-endpoints', headers=owner.h,
        json={'organizationId': org['id'], 'url': 'https://public.example/events', 'eventTypes': event_types})
    assert response.status_code == 201, response.text
    endpoint = response.json(); secret = endpoint['secret']
    assert 'secret' not in (await client.get('/v1/webhook-endpoints', headers=owner.h, params={'organizationId': org['id']})).json()[0]
    assert (await client.post(f"/v1/webhook-endpoints/{endpoint['id']}/test", headers=outsider.h)).status_code == 403
    sent = []
    async def send(url, body, headers):
        sent.append((body, headers)); return 503 if len(sent) == 1 else 204
    monkeypatch.setattr(providers, 'post_webhook', send)
    response = await client.post(f"/v1/webhook-endpoints/{endpoint['id']}/test", headers=owner.h)
    assert response.status_code == 202, response.text
    await drain(); clock.advance(timedelta(seconds=61)); await drain(); clock.set_now(None)
    assert len(sent) == 2
    raw, headers = sent[0]
    timestamp, signature = headers['X-Zoikorum-Signature'].split(',')
    expected = hmac.new(secret.encode(), timestamp[2:].encode() + b'.' + raw, hashlib.sha256).hexdigest()
    assert signature == 'v1=' + expected
    page = (await client.get('/v1/webhook-deliveries', headers=owner.h, params={'endpointId': endpoint['id']})).json()
    assert page['items'][0]['status'] == 'DELIVERED' and page['items'][0]['attempts'] == 2
    delivery_id = page['items'][0]['id']
    attempts = await client.get(f'/v1/webhook-deliveries/{delivery_id}/attempts', headers=owner.h)
    assert [row['responseStatus'] for row in attempts.json()] == [503, 204]
    assert (await client.get(f'/v1/webhook-deliveries/{delivery_id}/attempts', headers=outsider.h)).status_code == 403
    with pytest.raises(DBAPIError):
        async with sf() as s, s.begin():
            await s.execute(text('DELETE FROM notification.delivery_attempts WHERE delivery_id = :id'), {'id': uuid.UUID(delivery_id)})


async def test_ai_authorization_prompt_gates_and_provider_failure(client, make_user, drain, sf, monkeypatch):
    from test_contract import signed_contract
    from zoikorum.domains.ai import providers as ai_providers
    from zoikorum.domains.ai.models import InferenceLog
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    outsider = await make_user('ai-outsider')
    assert (await client.post('/v1/ai/contract-summary', headers=outsider.h, json={'contractId': c['id']})).status_code == 404
    result = await client.post('/v1/ai/contract-summary', headers=buyer.h, json={'contractId': c['id']})
    assert result.status_code == 200, result.text
    assert result.json()['fallbackUsed'] and result.json()['documentHash'] == c['termsHash']
    reviewer = await make_user('ai-reviewer', platform_roles=('AI_SAFETY_REVIEWER',)); await reviewer.step_up()
    draft = await client.post('/v1/ai/prompts', headers=reviewer.idem(), json={'promptKey': 'contract-summary', 'targetModel': 'offline:v1',
        'instructions': 'Summarize supplied contract facts. Never execute actions or invent facts.', 'goldenTests': [{'input': 'Contract facts', 'mustContain': ['Contract']}]})
    assert draft.status_code == 201, draft.text
    pid = draft.json()['id']
    assert (await client.post(f'/v1/ai/prompts/{pid}/approve', headers=reviewer.idem())).status_code == 200
    with pytest.raises(DBAPIError):
        async with sf() as s, s.begin():
            await s.execute(text("UPDATE ai.prompt_versions SET instructions = 'Changed approved instructions' WHERE id = :id"), {'id': uuid.UUID(pid)})
    async def fail(self, instructions, data): raise RuntimeError('Provider unavailable')
    monkeypatch.setattr(ai_providers.OfflineProvider, 'generate', fail)
    new_draft = await client.post('/v1/ai/prompts', headers=reviewer.idem(), json={'promptKey': 'contract-summary', 'targetModel': 'offline:v1',
        'instructions': 'Summarize only supplied contract facts without making decisions.', 'goldenTests': [{'input': 'Contract facts', 'mustContain': ['Contract']}]})
    assert new_draft.status_code == 201, new_draft.text
    approval = await client.post(f"/v1/ai/prompts/{new_draft.json()['id']}/approve", headers=reviewer.idem())
    assert approval.status_code == 409, approval.text
    prompts = (await client.get('/v1/ai/prompts', headers=reviewer.h)).json()
    assert next(p for p in prompts if p['id'] == new_draft.json()['id'])['status'] == 'DRAFT'
    result = await client.post('/v1/ai/contract-summary', headers=buyer.h, json={'contractId': c['id']})
    assert result.status_code == 200 and result.json()['fallbackUsed']
    async with sf() as session:
        assert len((await session.scalars(select(InferenceLog))).all()) == 2
    assert (await client.get(f"/v1/contracts/{c['id']}", headers=buyer.h)).json()['status'] == 'ACTIVE'


async def test_review_verified_completion_and_reports_rebuild(client, make_user, drain, sf):
    from test_dispute import funded_contract
    from zoikorum.domains.analytics.models import EventFact
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain, both=True)
    future_report = await client.get('/v1/reports/buyer', headers=buyer.h, params={
        'organizationId': c['organizationId'], 'from': (clock.now() + timedelta(days=1)).isoformat()})
    assert future_report.status_code == 200, future_report.text
    assert future_report.json()['items'] == []
    assert future_report.json()['summaryScope'] == 'current snapshot'
    assert future_report.json()['summary']['activeEngagements'] == 1
    response = await client.post(f"/v1/contracts/{c['id']}/review", headers=buyer.idem(), json={'rating': 5, 'comment': 'Work delivered successfully.'})
    assert response.status_code == 409
    for m in c['milestones']:
        submitted = await client.post(f"/v1/milestones/{m['id']}/submit", headers=pro_user.idem(), json={'note': 'Completed agreed deliverables', 'files': []})
        assert submitted.status_code == 200, submitted.text
        accepted = await client.post(f"/v1/milestones/{m['id']}/accept", headers=buyer.idem())
        assert accepted.status_code == 200, accepted.text
        await drain()
    body = {'rating': 5, 'comment': 'Work delivered successfully and on schedule.'}
    response = await client.post(f"/v1/contracts/{c['id']}/review", headers=buyer.idem(), json=body)
    assert response.status_code == 201, response.text
    assert (await client.post(f"/v1/contracts/{c['id']}/review", headers=buyer.idem(), json=body)).status_code == 409
    assert (await client.post(f"/v1/contracts/{c['id']}/review", headers=pro_user.idem(), json=body)).status_code == 403
    public = await client.get(f"/v1/professionals/{pro['id']}/reviews")
    assert public.status_code == 200 and public.json()['reviewCount'] == 1
    org_id = c['organizationId']
    saved = await client.post('/v1/saved/professionals', headers=buyer.h, json={'professionalId': pro['id']})
    assert saved.status_code == 204, saved.text
    await drain()
    dashboard = (await client.get('/v1/dashboards/buyer', headers=buyer.h, params={'organizationId': org_id})).json()
    assert dashboard['savedProfessionals'] == 1
    assert (await client.delete(f"/v1/saved/professionals/{pro['id']}", headers=buyer.h)).status_code == 204
    await drain()
    dashboard = (await client.get('/v1/dashboards/buyer', headers=buyer.h, params={'organizationId': org_id})).json()
    assert dashboard['savedProfessionals'] == 0
    outsider = await make_user('reports-outsider')
    assert (await client.get('/v1/reports/buyer', headers=outsider.h, params={'organizationId': org_id})).status_code == 404
    for format, mime in [('json', 'application/json'), ('csv', 'text/csv'), ('pdf', 'application/pdf')]:
        r = await client.get('/v1/reports/buyer', headers=buyer.h, params={'organizationId': org_id, 'format': format})
        assert r.status_code == 200 and mime in r.headers['content-type'], r.text
    before = (await client.get('/v1/dashboards/buyer', headers=buyer.h, params={'organizationId': org_id})).json()
    admin = await make_user('reports-admin', platform_roles=('PLATFORM_ADMIN',)); await admin.step_up(); await drain()
    invalid = await client.get('/v1/analytics/marketplace-health', headers=admin.h, params={'from': '2026-10-08T00:00:00'})
    assert invalid.status_code == 422, invalid.text
    rebuilt = await client.post('/v1/admin/analytics/rebuild', headers=admin.h)
    assert rebuilt.status_code == 200, rebuilt.text
    after = (await client.get('/v1/dashboards/buyer', headers=buyer.h, params={'organizationId': org_id})).json()
    assert after['fundsInProtectionMinor'] == before['fundsInProtectionMinor'] == {'USD': 0}
    assert after['savedProfessionals'] == 0


async def test_dispute_appeal_independence_and_preserved_decision(client, make_user, drain, sf):
    from test_dispute import funded_contract, dispute_body, staff
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    original_reviewer = await staff(make_user, 'original-legal', 'LEGAL')
    reviewer = await staff(make_user, 'appeal-legal', 'LEGAL')
    opened = await client.post('/v1/disputes', headers=buyer.idem(), json=dispute_body(c))
    assert opened.status_code == 201
    did = opened.json()['id']
    # Fixture: a sealed platform decision. Appeal commands must never rewrite it.
    decision = {'decisionPath': 'PLATFORM', 'decidedBy': str(original_reviewer.id), 'originalReviewers': [str(original_reviewer.id)],
                'plainSummary': 'Original decision', 'outcome': 'REWORK', 'allocations': [], 'evidenceReferences': [], 'policyCitations': [], 'appealEligible': True, 'appealNote': 'Appeal window open'}
    import json
    async with sf() as s, s.begin():
        await s.execute(text('UPDATE dispute.cases SET status = :status, decision = CAST(:decision AS jsonb), decided_at = :now WHERE id = :id'),
            {'status': 'CLOSED', 'decision': json.dumps(decision), 'now': clock.now(), 'id': uuid.UUID(did)})
    response = await client.post(f'/v1/disputes/{did}/appeal', headers=buyer.idem(), json={'grounds': 'PROCEDURAL_ERROR', 'explanation': 'Material evidence was excluded from the original review.'})
    assert response.status_code == 201, response.text
    body = {'outcome': 'UPHELD', 'reason': 'A procedural error requires an independent follow-up review.', 'remediation': 'A separate Legal reviewer will review the omitted evidence.'}
    assert (await client.post(f'/v1/disputes/{did}/appeal/decision', headers=original_reviewer.idem(), json=body)).status_code == 403
    response = await client.post(f'/v1/disputes/{did}/appeal/decision', headers=reviewer.idem(), json=body)
    assert response.status_code == 200 and response.json()['status'] == 'UPHELD', response.text
    async with sf() as s:
        current = await s.scalar(text('SELECT decision FROM dispute.cases WHERE id = :id'), {'id': uuid.UUID(did)})
        assert current == decision
    with pytest.raises(DBAPIError):
        async with sf() as s, s.begin():
            await s.execute(text("UPDATE dispute.cases SET decision = '{}'::jsonb WHERE id = :id"), {'id': uuid.UUID(did)})
    with pytest.raises(DBAPIError):
        async with sf() as s, s.begin():
            await s.execute(text("UPDATE dispute.appeals SET status = 'REJECTED' WHERE case_id = :id"), {'id': uuid.UUID(did)})


async def test_enforcement_live_suspension_independent_appeal(client, make_user, drain, sf):
    subject = await make_user('safety-subject', platform_roles=('EXECUTIVE',))
    users = {}
    for name, role in [('analyst', 'TS_ANALYST'), ('risk', 'RISK_LEAD'), ('executive', 'EXECUTIVE'), ('legal', 'LEGAL'), ('appeal', 'LEGAL')]:
        users[name] = await make_user('safety-' + name, platform_roles=(role,)); await users[name].step_up()
    response = await client.post('/v1/admin/enforcement-cases', headers=users['analyst'].idem(), json={'subjectType': 'IDENTITY', 'subjectId': str(subject.id), 'signalSource': 'HUMAN_REVIEW', 'summary': 'Confirmed account risk requires an independently approved restriction.', 'evidenceRefs': ['review-evidence-001']})
    assert response.status_code == 201, response.text
    cid = response.json()['id']; root = f'/v1/admin/enforcement-cases/{cid}'
    assert (await client.post(root + '/assess', headers=users['risk'].idem(), json={'level': 4, 'reasonCode': 'CONFIRMED_RISK'})).status_code == 200
    notice = {key: 'Review the documented account restriction and contact support for help.' for key in ['whatHappened', 'whyItHappened', 'whatChanged', 'whatYouCanDo', 'whatHappensNext', 'howToGetHelp']}
    assert (await client.post(root + '/propose-action', headers=users['analyst'].idem(), json={'action': 'SUSPEND_ACCOUNT', 'notice': notice})).status_code == 200
    assert (await client.post(root + '/approve-action', headers=users['executive'].idem())).json()['status'] == 'AWAITING_APPROVAL'
    assert (await client.post(root + '/approve-action', headers=users['legal'].idem())).json()['status'] == 'ACTIVE'
    # Denied even before asynchronous account-status projection catches up.
    assert (await client.get('/v1/organizations/mine', headers=subject.h)).status_code == 403
    from zoikorum.domains.identity import facade as identity
    async with sf() as session:
        assert not await identity.account_is_active(session, subject.id)
        assert await identity.live_platform_roles(session, subject.id) == frozenset()
    await drain()
    restricted_login = await client.post('/v1/auth/login', json={'email': subject.email, 'password': subject.password})
    assert restricted_login.status_code == 200, restricted_login.text
    restricted_headers = {'Authorization': 'Bearer ' + restricted_login.json()['tokens']['accessToken']}
    assert (await client.get('/v1/organizations/mine', headers=restricted_headers)).status_code == 403
    assert (await client.get('/v1/enforcement-cases', headers=restricted_headers)).status_code == 200
    assert (await client.get('/v1/enforcement-cases', headers=subject.h)).status_code == 401
    refreshed = await client.post('/v1/auth/refresh', json={'refreshToken': restricted_login.json()['tokens']['refreshToken']})
    assert refreshed.status_code == 200, refreshed.text
    restricted_headers = {'Authorization': 'Bearer ' + refreshed.json()['accessToken']}
    me = await client.get('/v1/me', headers=restricted_headers)
    assert me.status_code == 200 and me.json()['status'] == 'SUSPENDED' and me.json()['platformRoles'] == []
    assert (await client.patch('/v1/me', headers=restricted_headers, json={'displayName': 'Blocked change'})).status_code == 403
    assert (await client.get('/v1/organizations/mine', headers=restricted_headers)).status_code == 403
    appeal = await client.post(f'/v1/enforcement-cases/{cid}/appeal', headers={**restricted_headers, 'Idempotency-Key': str(uuid.uuid4())}, json={'reason': 'The restriction should be reconsidered based on the documented evidence.'})
    assert appeal.status_code == 200, appeal.text
    body = {'upheld': True, 'reason': 'Independent evidence review supports reversal of the restriction.'}
    assert (await client.post(root + '/appeal/decision', headers=users['legal'].idem(), json=body)).status_code == 403
    assert (await client.post('/v1/auth/logout', headers=restricted_headers)).status_code == 204
    assert (await client.get('/v1/enforcement-cases', headers=restricted_headers)).status_code == 401
    recovery = await client.post('/v1/auth/password/forgot', json={'email': subject.email})
    assert recovery.status_code == 202 and recovery.json()['resetToken'], recovery.text
    await drain()
    from zoikorum.domains.notification.models import Notification
    from zoikorum.shared.event_catalog import E
    async with sf() as session:
        email = await session.scalar(select(Notification).where(Notification.identity_id == subject.id, Notification.event_type == E.PASSWORD_RESET_REQUESTED))
        assert email and email.email_status == 'LOCAL_ONLY'
    subject.password = 'Recovered-Password-2026!'
    reset = await client.post('/v1/auth/password/reset', json={'token': recovery.json()['resetToken'], 'newPassword': subject.password})
    assert reset.status_code == 204, reset.text
    recovered = await client.post('/v1/auth/login', json={'email': subject.email, 'password': subject.password})
    assert recovered.status_code == 200 and recovered.json()['user']['status'] == 'SUSPENDED', recovered.text
    recovery_headers = {'Authorization': 'Bearer ' + recovered.json()['tokens']['accessToken']}
    assert (await client.get('/v1/organizations/mine', headers=recovery_headers)).status_code == 403
    assert (await client.get('/v1/enforcement-cases', headers=recovery_headers)).status_code == 200
    assert (await client.post(root + '/appeal/decision', headers=users['appeal'].idem(), json=body)).status_code == 200
    await drain()
    login = await client.post('/v1/auth/login', json={'email': subject.email, 'password': subject.password})
    assert login.status_code == 200, login.text
    async with sf() as session:
        reversal = await session.scalar(select(Notification).where(Notification.identity_id == subject.id,
            Notification.event_type == E.ENFORCEMENT_ACTION_REVERSED))
        assert reversal and reversal.mandatory and 'no longer active' in reversal.notice['whatChanged']
        assert reversal.notice['whyItHappened'] == body['reason']


async def test_expiring_one_enforcement_case_preserves_another_active_restriction(client, make_user, drain, sf):
    from test_proposal import tier_b
    from zoikorum.domains.admin import facade as admin
    pro_user, pro = await tier_b(client, make_user, drain, 'overlapping-restrictions')
    staff = {}
    for name, role in [('analyst', 'TS_ANALYST'), ('risk', 'RISK_LEAD'), ('legal', 'LEGAL')]:
        staff[name] = await make_user('overlap-' + name, platform_roles=(role,)); await staff[name].step_up()
    notice = {key: 'Read the independently reviewed restriction and available appeal process.' for key in
        ['whatHappened', 'whyItHappened', 'whatChanged', 'whatYouCanDo', 'whatHappensNext', 'howToGetHelp']}
    async def suspend(duration):
        opened = await client.post('/v1/admin/enforcement-cases', headers=staff['analyst'].idem(), json={
            'subjectType': 'PROFESSIONAL', 'subjectId': pro['id'], 'signalSource': 'HUMAN_REVIEW',
            'summary': 'An independent compliance review confirmed an engagement restriction.', 'evidenceRefs': ['verified-case-reference']})
        assert opened.status_code == 201, opened.text
        root = '/v1/admin/enforcement-cases/' + opened.json()['id']
        assessed = await client.post(root + '/assess', headers=staff['risk'].idem(), json={'level': 3, 'reasonCode': 'CONFIRMED_COMPLIANCE'})
        assert assessed.status_code == 200, assessed.text
        proposed = await client.post(root + '/propose-action', headers=staff['analyst'].idem(), json={'action': 'ENGAGEMENT_SUSPENSION', 'durationDays': duration, 'notice': notice})
        assert proposed.status_code == 200, proposed.text
        approved = await client.post(root + '/approve-action', headers=staff['legal'].idem())
        assert approved.status_code == 200 and approved.json()['status'] == 'ACTIVE', approved.text
        return root
    first, second = await suspend(1), await suspend(None)
    await drain()
    clock.advance(timedelta(days=2)); await drain(); clock.set_now(None)
    async with sf() as session:
        assert 'ENGAGEMENT_SUSPENSION' in await admin.active_restrictions(session, 'PROFESSIONAL', uuid.UUID(pro['id']))
    trust_url = f"/v1/trust/professionals/{pro['id']}"
    assert (await client.get(trust_url)).json()['tier'] == 'C'
    reversed = await client.post(second + '/reverse', headers=staff['risk'].idem(), json={'reason': 'A completed independent review authorizes reversal of the remaining case.'})
    assert reversed.status_code == 200, reversed.text
    await drain()
    assert (await client.get(trust_url)).json()['tier'] == 'B'
