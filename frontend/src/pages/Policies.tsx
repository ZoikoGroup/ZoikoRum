import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { orgApi, type Organization, type BusinessUnit } from '../api/orgs'
import { ApiError } from '../api/client'
import { openStoredFile, toUpload } from '../api/files'
import { policyApi, type Approval, type ExceptionRequest, type PolicyProfile, type PolicyRule } from '../api/policy'
import { ErrorAlert, Field, useStepUp } from '../components/ui'

export default function PoliciesPage() {
  const [params] = useSearchParams()
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [units, setUnits] = useState<BusinessUnit[]>([])
  const [simulation, setSimulation] = useState<string | null>(null)
  const [orgId, setOrgId] = useState(params.get('orgId') || '')
  const [profiles, setProfiles] = useState<PolicyProfile[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [exceptions, setExceptions] = useState<ExceptionRequest[]>([])
  const [tab, setTab] = useState(params.get('tab') || 'profiles')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<PolicyProfile | null>(null)
  const [settings, setSettings] = useState('{}')
  const [rules, setRules] = useState('[]')
  const [impact, setImpact] = useState<string | null>(null)
  const { run, modal } = useStepUp(setError)
  const org = orgs.find(o => o.id === orgId)
  const admin = !!org?.myRoles.includes('ORG_ADMIN')
  const reload = useCallback(async () => {
    if (!orgId) return
    // Follow all cursors so older pending approvals never disappear from the workspace.
    async function collect<T>(fetch: (cursor?: string) => Promise<{ items: T[]; nextCursor: string | null }>) {
      const items: T[] = []; let cursor: string | undefined
      do { const page = await fetch(cursor); items.push(...page.items); cursor = page.nextCursor ?? undefined } while (cursor)
      return items
    }
    const [p, a, e] = await Promise.all([collect(c => policyApi.profiles(orgId, c)), collect(c => policyApi.approvals(orgId, c)), collect(c => policyApi.exceptions(orgId, c))])
    setProfiles(p); setApprovals(a); setExceptions(e)
  }, [orgId])
  useEffect(() => { orgApi.mine().then(items => { setOrgs(items); setOrgId(current => current || items[0]?.id || '') }).catch(setError) }, [])
  useEffect(() => { reload().catch(setError); const timer = window.setInterval(() => reload().catch(setError), 15000); return () => window.clearInterval(timer) }, [reload])
  useEffect(() => { if (orgId) orgApi.businessUnits(orgId).then(setUnits).catch(setError) }, [orgId])
  function choose(p: PolicyProfile) {
    setSelected(p); setImpact(null)
    const v = p.versions.find(v => v.id === (p.draftVersionId || p.activeVersionId)) || p.versions[0]
    setSettings(JSON.stringify(v.settings, null, 2)); setRules(JSON.stringify(v.rules, null, 2))
  }
  async function action(work: () => Promise<unknown>) {
    setBusy(true); setError(null)
    try { await work(); await reload() } catch (err) { if (err instanceof ApiError && err.code === 'STEP_UP_REQUIRED') throw err; setError(err) } finally { setBusy(false) }
  }
  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget)
    await action(async () => choose(await policyApi.create({ orgId, name: String(f.get('name')), description: String(f.get('description')), template: String(f.get('template')), businessUnitIds: f.getAll('businessUnitIds').map(String), riskLevel: String(f.get('riskLevel')) })))
  }
  async function requestException(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget)
    await action(async () => { const documents = await Promise.all(f.getAll('documents').filter((v): v is File => v instanceof File && v.size > 0).map(file => toUpload(file))); await policyApi.requestException({ orgId, subjectType: String(f.get('subjectType')), subjectId: String(f.get('subjectId')), action: String(f.get('action')), justification: String(f.get('justification')), documents, expiresAt: new Date(String(f.get('expiresAt'))).toISOString() }) })
  }
  return <div className="page">
    <div className="page-header"><div><h1>Policies &amp; approvals</h1><p className="muted">Control eligibility, spend authority and documented exceptions.</p></div><button className="btn" onClick={() => action(reload)} disabled={busy}>Refresh</button></div>
    <ErrorAlert error={error} />{modal}
    <Field label="Organisation" id="policy-org"><select id="policy-org" className="input" value={orgId} onChange={e => { setOrgId(e.target.value); setSelected(null) }}>{orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
    <div className="tabs">{['profiles', 'approvals', 'exceptions'].map(t => <button key={t} className={`btn ${tab === t ? 'btn-primary' : ''}`} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>)}</div>
    {tab === 'profiles' && <>
      {admin && <form className="card" onSubmit={create}><h2>Create policy profile</h2><div className="row"><input className="input" name="name" aria-label="Profile name" placeholder="Profile name" required minLength={2} maxLength={80} /><select className="input" name="template" aria-label="Policy template">{['ENTERPRISE_STANDARD', 'REGULATED', 'CROSS_BORDER', 'GROWTH_ADVISORY'].map(t => <option key={t}>{t}</option>)}</select></div><input className="input" name="description" aria-label="Description" placeholder="Description" /><Field label="Risk level" id="policy-risk"><select className="input" id="policy-risk" name="riskLevel"><option>MEDIUM</option><option>LOW</option><option>HIGH</option></select></Field>{!!units.length && <Field label="Business units (leave empty for organisation-wide policy)" id="policy-units"><select className="input" id="policy-units" name="businessUnitIds" multiple>{units.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></Field>}<button className="btn btn-primary" disabled={busy}>Create draft</button></form>}
      {profiles.map(p => <button key={p.id} className="card" onClick={() => choose(p)}><strong>{p.name}</strong> · {p.status}<p>{p.description}</p></button>)}
      {!profiles.length && <p className="muted">No policy profiles. The platform baseline currently applies.</p>}
      {selected && <section className="card"><h2>{selected.name}</h2><p>{selected.versions.map(v => `${v.label} (${v.status})`).join(' · ')}</p><p className="muted">Active versions are immutable. Existing engagements retain their agreed version. Escrow is required by the platform baseline.</p>
        <Field label="Settings" id="policy-settings"><textarea id="policy-settings" className="input" rows={16} value={settings} readOnly={!admin || !selected.draftVersionId} onChange={e => setSettings(e.target.value)} /></Field>
        <Field label="Rules — conditions, actions and approval steps" id="policy-rules"><textarea id="policy-rules" className="input" rows={12} value={rules} readOnly={!admin || !selected.draftVersionId} onChange={e => setRules(e.target.value)} /></Field>
        <p className="muted">Conditions support all/any groups or field/op/value. Approval modes: SINGLE, SEQUENTIAL, PARALLEL. Decisions: REQUIRE_APPROVAL, REQUIRE_EXCEPTION, BLOCK.</p>
        <div className="row">{admin && (selected.draftVersionId ? <><button className="btn" disabled={busy} onClick={() => action(async () => choose(await policyApi.save(selected.id, selected.version, JSON.parse(settings), JSON.parse(rules) as PolicyRule[])))}>Save draft</button><button className="btn btn-primary" disabled={busy} onClick={() => run(() => action(async () => choose(await policyApi.activate(selected.id))))}>Activate saved draft</button></> : <button className="btn" onClick={() => action(async () => choose(await policyApi.draft(selected.id)))}>New version</button>)}<button className="btn" onClick={() => action(async () => { const result = await policyApi.impact(selected.id); setImpact(`${result.eligibleProfessionals} eligible professionals. ${result.scope}`) })}>Preview saved policy impact</button></div>{impact && <p>{impact}</p>}
      </section>}
      {admin && selected && <form className="card" onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); action(async () => { const result = await policyApi.dryRun({ orgId, previewProfileId: selected.id, subjectType: 'Simulation', subjectId: crypto.randomUUID(), action: String(f.get('action')), attributes: JSON.parse(String(f.get('attributes'))) }); setSimulation(`${result.decision}: ${result.reasons.map(r => r.message).join('; ')}`) }) }}><h2>Dry run saved policy</h2><p className="muted">Supply simulated facts as JSON. This records an evaluation without creating approvals or moving money.</p><input className="input" name="action" aria-label="Simulated action" required defaultValue="PROPOSAL_ACCEPT" /><textarea className="input" name="attributes" aria-label="Simulated facts" required rows={6} placeholder={'{"professional.tier":"B","professional.dimensions":{"identity":"VERIFIED"},"engagement.valueMinor":100000,"engagement.currency":"USD","buyer.country":"US"}'} /><button className="btn" disabled={busy}>Run simulation</button>{simulation && <p>{simulation}</p>}</form>}
    </>}
    {tab === 'approvals' && <><p className="muted">After approval, retry the original action. Escrow release resumes automatically. Decisions require current authority; requesters cannot approve their own actions.</p>{!approvals.length && <p>No approval requests.</p>}{approvals.map(a => <section className="card" key={a.id}><h2>{a.action.replaceAll('_', ' ')}</h2><p>{a.subjectType} · {a.subjectId}</p><p><strong>{a.status}</strong> · Due {new Date(a.deadline).toLocaleString()}</p>{a.reasons.map((r, i) => <p key={i}>{r.message}</p>)}{a.workflows.map((w, i) => <p key={i}>{w.mode}: {w.steps.map(s => `${s.role} × ${s.count}`).join(' → ')}</p>)}{a.votes.map(v => <p key={v.id}>{v.role} · {v.decision} · {v.reason}{!v.valid && v.decision === 'GRANT' ? ' (authority no longer valid)' : ''}</p>)}{a.status === 'PENDING' && <form onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); run(() => action(() => policyApi.decide(a.id, String(f.get('decision')) as 'GRANT' | 'DENY', String(f.get('reason')), String(f.get('stepId'))))) }}><select className="input" name="stepId" aria-label="Approval step">{a.workflows.flatMap(w => w.steps).map(s => <option key={s.id} value={s.id}>{s.role} ({s.id})</option>)}</select><textarea className="input" name="reason" aria-label="Decision reason" required minLength={3} maxLength={1000} /><select className="input" name="decision" aria-label="Decision"><option value="GRANT">Approve</option><option value="DENY">Deny</option></select><button className="btn btn-primary" disabled={busy}>Record decision</button></form>}</section>)}</>}
    {tab === 'exceptions' && <>
      <form className="card" onSubmit={requestException}><h2>Request exception</h2><p className="muted">First attempt the commercial action. Exceptions apply to that recorded evaluation, require justification and expire.</p><input className="input" name="subjectType" aria-label="Subject type" required placeholder="Subject type" defaultValue={params.get('subjectType') || ''} /><input className="input" name="subjectId" aria-label="Subject reference" required placeholder="Subject reference" defaultValue={params.get('subjectId') || ''} /><input className="input" name="action" aria-label="Policy action" required placeholder="Policy action" defaultValue={params.get('action') || ''} /><textarea className="input" name="justification" aria-label="Justification" required minLength={10} maxLength={4000} /><input name="documents" type="file" multiple aria-label="Supporting documents" accept=".pdf,.docx,.xlsx,.csv,.jpg,.jpeg,.png" /><input className="input" name="expiresAt" type="datetime-local" aria-label="Exception expiry" required /><button className="btn btn-primary" disabled={busy}>Request exception</button></form>
      {exceptions.map(x => <section className="card" key={x.id}><h2>{x.action.replaceAll('_', ' ')} · {x.status}</h2><p>{x.justification}</p><p>Expires {new Date(x.expiresAt).toLocaleString()}</p>{x.documents.map(d => <button className="btn" key={d.sha256} onClick={() => openStoredFile(`/v1/policy/exceptions/${x.id}/documents/${d.sha256}`).catch(setError)}>{d.name}</button>)}{x.decisionReason && <p>{x.decisionReason}</p>}{x.status === 'PENDING' && org?.myRoles.includes('EXCEPTION_AUTHORITY') && <form onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); run(() => action(() => policyApi.decideException(x.id, String(f.get('decision')) as 'GRANT' | 'DENY', String(f.get('reason'))))) }}><textarea className="input" name="reason" aria-label="Exception decision reason" required minLength={3} /><select className="input" name="decision" aria-label="Exception decision"><option value="GRANT">Grant</option><option value="DENY">Deny</option></select><button className="btn btn-primary" disabled={busy}>Record decision</button></form>}</section>)}
    </>}
  </div>
}
