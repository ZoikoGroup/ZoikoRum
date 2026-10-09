"""Real policy authority, immutable versions, deterministic rule precedence and expiry."""
from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from zoikorum.domains.policy import service
from zoikorum.domains.policy.facade import Attr, Decision, PolicyAction, PolicyContext
from zoikorum.domains.policy.models import ApprovalRequest, PolicyEvaluation
from zoikorum.domains.policy.rules import matches, template
from zoikorum.domains.policy.schemas import RuleIn, SettingsIn
from zoikorum.shared import clock


@pytest.mark.parametrize('condition,attrs,expected', [
    ({'field': 'n', 'op': 'GTE', 'value': 20}, {'n': 20}, True),
    ({'field': 'n', 'op': 'GT', 'value': 20}, {'n': 20}, False),
    ({'field': 'n', 'op': 'GT', 'value': 0}, {'n': True}, False),
    ({'field': 'n', 'op': 'EQ', 'value': 0}, {}, False),
    ({'field': 'n', 'op': 'EXISTS'}, {}, False),
    ({'all': [{'field': 'n', 'op': 'GTE', 'value': 20}, {'field': 'c', 'op': 'IN', 'value': ['USD']}]}, {'n': 21, 'c': 'EUR'}, False),
    ({'any': [{'field': 'n', 'op': 'GTE', 'value': 20}, {'field': 'c', 'op': 'IN', 'value': ['USD']}]}, {'n': 1, 'c': 'USD'}, True),
])
def test_conditions(condition, attrs, expected):
    assert matches(condition, attrs) is expected


def test_templates_and_safety_baseline():
    for name in ['REGULATED', 'ENTERPRISE_STANDARD', 'CROSS_BORDER', 'GROWTH_ADVISORY']:
        settings, rules = template(name)
        SettingsIn(**settings)
        for rule in rules:
            RuleIn(**rule)
    with pytest.raises(ValidationError):
        SettingsIn(escrowRequired=False)
    with pytest.raises(ValidationError):
        SettingsIn(autoAcceptAfterDays=1, acceptanceWindowDays=14)


def test_grants_are_bound_to_actor_terms_and_version():
    ctx = PolicyContext(uuid.uuid4(), PolicyAction.PROPOSAL_ACCEPT, 'Proposal', uuid.uuid4(), uuid.uuid4(),
        {Attr.AMOUNT_MINOR: 100, 'contract.termsHash': 'a'})
    version = uuid.uuid4()
    original = service.context_hash(ctx, version)
    from dataclasses import replace
    assert service.context_hash(replace(ctx, attributes={**ctx.attributes, Attr.PRO_TIER: 'A'}), version) == original
    assert service.context_hash(replace(ctx, attributes={**ctx.attributes, Attr.AMOUNT_MINOR: 101}), version) != original
    assert service.context_hash(replace(ctx, actor_identity_id=uuid.uuid4()), version) != original
    assert service.context_hash(ctx, uuid.uuid4()) != original


def test_parallel_requires_each_independent_step():
    workflows = [{'steps': [{'id': 'a', 'count': 1}, {'id': 'b', 'count': 1}]}]
    assert not service.steps_satisfied(workflows, [SimpleNamespace(step_id='a')])
    assert service.steps_satisfied(workflows, [SimpleNamespace(step_id='a'), SimpleNamespace(step_id='b')])


async def test_versions_dry_runs_and_cross_org_access(client, make_user, drain, sf):
    owner = await make_user('policy-owner')
    outsider = await make_user('policy-outsider')
    await drain(); await owner.refresh()
    org = (await client.get('/v1/organizations/mine', headers=owner.h)).json()[0]
    response = await client.post('/v1/policy/profiles', headers=owner.h,
        json={'orgId': org['id'], 'name': 'Enterprise standard', 'template': 'ENTERPRISE_STANDARD'})
    assert response.status_code == 201, response.text
    profile = response.json()
    assert (await client.get(f"/v1/policy/profiles/{profile['id']}", headers=outsider.h)).status_code == 404
    assert (await client.post(f"/v1/policy/profiles/{profile['id']}/activate", headers=owner.h)).json()['code'] == 'STEP_UP_REQUIRED'
    await owner.step_up()
    response = await client.post(f"/v1/policy/profiles/{profile['id']}/activate", headers=owner.h)
    assert response.status_code == 200, response.text
    active = response.json()
    old_version = active['activeVersionId']
    attrs = {Attr.PRO_TIER: 'B', Attr.PRO_DIMENSIONS: {'identity': 'VERIFIED'}, Attr.AMOUNT_MINOR: 100,
        Attr.ENGAGEMENT_CURRENCY: 'USD', Attr.BUYER_COUNTRY: 'US'}
    response = await client.post('/v1/policy/dry-run', headers=owner.h, json={'orgId': org['id'],
        'action': 'ESCROW_RELEASE', 'subjectType': 'Milestone', 'subjectId': str(uuid.uuid4()), 'attributes': attrs})
    assert response.status_code == 200, response.text
    assert response.json()['decision'] == 'REQUIRE_APPROVAL'
    async with sf() as session:
        assert await session.scalar(select(ApprovalRequest.id)) is None
        assert (await session.scalar(select(PolicyEvaluation))).dry_run
    response = await client.post(f"/v1/policy/profiles/{profile['id']}/draft", headers=owner.h)
    draft = response.json()
    settings = draft['versions'][0]['settings']; settings['minTrustTier'] = 'A'
    response = await client.put(f"/v1/policy/profiles/{profile['id']}/draft", headers=owner.h,
        json={'version': draft['version'], 'settings': settings, 'rules': []})
    assert response.status_code == 200, response.text
    assert (await client.post(f"/v1/policy/profiles/{profile['id']}/activate", headers=owner.h)).status_code == 200
    async with sf() as session, session.begin():
        pinned = await service.settings_for_org(session, uuid.UUID(org['id']), uuid.UUID(old_version))
        current = await service.settings_for_org(session, uuid.UUID(org['id']))
        assert pinned.min_trust_tier == 'B' and current.min_trust_tier == 'A'
    async with sf() as session, session.begin():
        with pytest.raises(Exception, match='immutable'):
            await session.execute(text("UPDATE policy.versions SET settings='{}' WHERE id=:id"), {'id': old_version})


async def test_approval_deduplication_self_decision_and_timeout(client, make_user, drain, sf):
    owner = await make_user('policy-approval')
    await drain(); await owner.refresh(); await owner.step_up()
    org = (await client.get('/v1/organizations/mine', headers=owner.h)).json()[0]
    profile = (await client.post('/v1/policy/profiles', headers=owner.h,
        json={'orgId': org['id'], 'name': 'Release approval', 'template': 'ENTERPRISE_STANDARD'})).json()
    assert (await client.post(f"/v1/policy/profiles/{profile['id']}/activate", headers=owner.h)).status_code == 200
    ctx = PolicyContext(uuid.UUID(org['id']), 'ESCROW_RELEASE', 'Milestone', uuid.uuid4(), owner.id,
        {Attr.PRO_TIER: 'B', Attr.PRO_DIMENSIONS: {'identity': 'VERIFIED'}, Attr.AMOUNT_MINOR: 100,
            Attr.ENGAGEMENT_CURRENCY: 'USD', Attr.BUYER_COUNTRY: 'US'})
    async with sf() as session, session.begin():
        first = await service.evaluate(session, ctx)
        repeated = await service.evaluate(session, ctx)
        assert first.approval_request_id == repeated.approval_request_id
    response = await client.post(f'/v1/policy/approvals/{first.approval_request_id}/decide', headers=owner.h,
        json={'decision': 'GRANT', 'reason': 'I approve this release'})
    assert response.status_code == 403 and response.json()['code'] == 'SEPARATION_OF_DUTIES'
    clock.set_now(clock.now() + timedelta(hours=49))
    async with sf() as session, session.begin():
        await service.approval_deadline(session, str(first.approval_request_id))
        request = await session.get(ApprovalRequest, first.approval_request_id)
        assert request.status == 'PENDING' and request.escalation_count == 1
    clock.set_now(clock.now() + timedelta(hours=49))
    async with sf() as session, session.begin():
        await service.approval_deadline(session, str(first.approval_request_id))
        assert (await session.get(ApprovalRequest, first.approval_request_id)).status == 'EXPIRED'
        assert (await service.evaluate(session, ctx)).decision == Decision.BLOCK


@pytest.mark.regression
async def test_real_escrow_stays_held_until_independent_approval(client, make_user, drain, sf):
    from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b
    from test_escrow import escrow_of
    from zoikorum.domains.buyer.models import OrgMember
    from zoikorum.domains.contract.facade import get_contract
    from zoikorum.domains.escrow.models import Release
    pro_user, pro = await tier_b(client, make_user, drain, 'policy-professional')
    owner, org = await buyer_org(client, make_user, drain, 'policy-customer')
    approver = await make_user('policy-independent-approver')
    await owner.step_up(); await approver.step_up()
    async with sf() as session, session.begin():
        session.add(OrgMember(organization_id=uuid.UUID(org['id']), identity_id=approver.id,
            email=approver.email, display_name='Independent approver', roles=['APPROVER'],
            spend_limit_minor=2_000_000, spend_limit_currency='USD'))
    response = await client.post('/v1/policy/profiles', headers=owner.h,
        json={'orgId': org['id'], 'name': 'Protected release', 'template': 'ENTERPRISE_STANDARD',
            'rules': [*template('ENTERPRISE_STANDARD')[1], {
                'id': 'approve-spend', 'appliesTo': ['PROPOSAL_ACCEPT'],
                'condition': {'field': 'engagement.valueMinor', 'op': 'GTE', 'value': 1000},
                'decision': 'REQUIRE_APPROVAL', 'reasonCode': 'SPEND_APPROVAL',
                'message': 'Independent spend approval is required'}]})
    assert response.status_code == 201, response.text
    profile = response.json()
    response = await client.post(f"/v1/policy/profiles/{profile['id']}/activate", headers=owner.h)
    assert response.status_code == 200, response.text
    version_id = response.json()['activeVersionId']
    response = await client.post(R, headers=owner.idem(), json=request_body(org, pro))
    assert response.status_code == 201, response.text
    req = response.json()[0]
    response = await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())
    assert response.status_code == 201, response.text
    proposal = response.json()
    assert (await client.post(f"{P}/{proposal['id']}/submit", headers=pro_user.idem())).status_code == 200
    response = await client.post(f"{P}/{proposal['id']}/accept", headers=owner.idem())
    assert response.status_code == 409 and response.json()['code'] == 'APPROVAL_REQUIRED', response.text
    await drain()
    assert not (await client.get('/v1/contracts', headers=owner.h)).json()['items']
    approval = (await client.get(f"/v1/policy/approvals?orgId={org['id']}", headers=owner.h)).json()['items'][0]
    assert approval['action'] == 'PROPOSAL_ACCEPT'
    response = await client.post(f"/v1/policy/approvals/{approval['id']}/decide", headers=approver.h,
        json={'decision': 'GRANT', 'reason': 'Commercial terms and spending approved'})
    assert response.status_code == 200, response.text
    response = await client.post(f"{P}/{proposal['id']}/accept", headers=owner.idem())
    assert response.status_code == 200, response.text
    await drain()
    contract = (await client.get('/v1/contracts', headers=owner.h)).json()['items'][0]
    async with sf() as session:
        assert (await get_contract(session, uuid.UUID(contract['id']))).policy_version_id == uuid.UUID(version_id)
    assert (await client.post(f"/v1/contracts/{contract['id']}/sign", headers=owner.idem(), json={'termsHash': contract['termsHash']})).status_code == 200
    await pro_user.step_up()
    assert (await client.post(f"/v1/contracts/{contract['id']}/sign", headers=pro_user.idem(), json={'termsHash': contract['termsHash']})).status_code == 200
    await drain()
    escrow = await escrow_of(client, owner, contract)
    response = await client.post(f"/v1/escrow/{escrow['id']}/fund", headers=owner.idem(),
        json={'all': True, 'paymentMethodToken': 'tok_visa'})
    assert response.status_code == 200, response.text
    await drain()
    milestone_id = contract['milestones'][0]['id']
    assert (await client.post(f'/v1/milestones/{milestone_id}/submit', headers=pro_user.idem(), json={'note': 'Delivered the master file', 'files': []})).status_code == 200
    assert (await client.post(f'/v1/milestones/{milestone_id}/accept', headers=owner.idem())).status_code == 200
    await drain()
    escrow = await escrow_of(client, owner, contract)
    assert escrow['allocations'][0]['state'] == 'RELEASE_PENDING_APPROVAL'
    async with sf() as session:
        assert await session.scalar(select(Release.id)) is None
    response = await client.get(f"/v1/policy/approvals?orgId={org['id']}", headers=owner.h)
    approval = response.json()['items'][0]
    assert (await client.post(f"/v1/policy/approvals/{approval['id']}/decide", headers=owner.h,
        json={'decision': 'GRANT', 'reason': 'Self approval attempt'})).status_code == 403
    response = await client.post(f"/v1/policy/approvals/{approval['id']}/decide", headers=approver.h,
        json={'decision': 'GRANT', 'reason': 'Deliverable accepted and within my spend authority'})
    assert response.status_code == 200, response.text
    await drain()
    assert (await escrow_of(client, owner, contract))['allocations'][0]['state'] == 'RELEASED'
    async with sf() as session:
        assert len((await session.scalars(select(Release))).all()) == 1


async def test_authority_revocation_invalidates_unconsumed_grant(client, make_user, drain, sf):
    from zoikorum.domains.buyer.models import OrgMember
    owner = await make_user('policy-requester')
    reviewer = await make_user('policy-reviewer')
    await drain(); await owner.refresh(); await owner.step_up(); await reviewer.step_up()
    org = (await client.get('/v1/organizations/mine', headers=owner.h)).json()[0]
    async with sf() as session, session.begin():
        session.add(OrgMember(organization_id=uuid.UUID(org['id']), identity_id=reviewer.id,
            email=reviewer.email, display_name='Reviewer', roles=['APPROVER'],
            spend_limit_minor=1000, spend_limit_currency='USD'))
    profile = (await client.post('/v1/policy/profiles', headers=owner.h,
        json={'orgId': org['id'], 'name': 'Authority checks', 'template': 'ENTERPRISE_STANDARD'})).json()
    assert (await client.post(f"/v1/policy/profiles/{profile['id']}/activate", headers=owner.h)).status_code == 200
    ctx = PolicyContext(uuid.UUID(org['id']), 'ESCROW_RELEASE', 'Milestone', uuid.uuid4(), owner.id,
        {Attr.PRO_TIER: 'B', Attr.PRO_DIMENSIONS: {'identity': 'VERIFIED'}, Attr.AMOUNT_MINOR: 100,
            Attr.ENGAGEMENT_CURRENCY: 'USD', Attr.BUYER_COUNTRY: 'US'})
    async with sf() as session, session.begin():
        decision = await service.evaluate(session, ctx)
    response = await client.post(f'/v1/policy/approvals/{decision.approval_request_id}/decide', headers=reviewer.h,
        json={'decision': 'GRANT', 'reason': 'Within my approved authority'})
    assert response.status_code == 200, response.text
    async with sf() as session, session.begin():
        assert (await service.evaluate(session, ctx)).allowed
        await session.execute(text("UPDATE buyer.members SET roles='{}' WHERE organization_id=:o AND identity_id=:i"),
            {'o': uuid.UUID(org['id']), 'i': reviewer.id})
        assert (await service.evaluate(session, ctx)).decision == Decision.BLOCK


@pytest.mark.unit
async def test_deadlines_have_one_source_the_platform_settings(monkeypatch):
    """A profile that leaves deadlines empty keeps the platform's (ZK_ACCEPTANCE_WINDOW_DAYS, ...); it never falls back to
    a second, hidden set of numbers. Deadlines a profile does set win."""
    from zoikorum.config import get_settings

    platform = get_settings()
    stored = service.stored_settings(SettingsIn(minTrustTier="A"))
    assert not set(service.DEADLINE_SETTINGS) & set(stored)  # empty deadlines are not saved as numbers
    profile, version = SimpleNamespace(id=uuid.uuid4(), name="Strict"), SimpleNamespace(id=uuid.uuid4(), number=1, settings=stored)

    async def effective(*_args, **_kwargs):
        return profile, version

    monkeypatch.setattr(service, "effective_version", effective)
    s = await service.settings_for_org(None, uuid.uuid4())
    assert s.min_trust_tier == "A"
    assert (s.acceptance_window_days, s.signature_deadline_days, s.dispute_evidence_days, s.direct_resolution_business_days,
            s.challenge_window_days) == (platform.acceptance_window_days, platform.signature_deadline_days,
                                         platform.dispute_evidence_days, platform.dispute_direct_resolution_business_days,
                                         platform.dispute_challenge_window_days)
    version.settings = service.stored_settings(SettingsIn(acceptanceWindowDays=10, signatureDeadlineDays=4))
    s = await service.settings_for_org(None, uuid.uuid4())
    assert (s.acceptance_window_days, s.signature_deadline_days) == (10, 4)

    async def none(*_args, **_kwargs):
        return None, None

    monkeypatch.setattr(service, "effective_version", none)
    default = await service.settings_for_org(None, uuid.uuid4())
    assert default.policy_version_label == "platform-default@1" and default.acceptance_window_days == platform.acceptance_window_days
