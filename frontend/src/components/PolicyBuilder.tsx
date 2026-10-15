import { useEffect, useState } from 'react'
import { policyApi, type PolicyChecks, type PolicyDashboard as Dashboard, type PolicyRule } from '../api/policy'
import { formatMoney } from '../api/orgs'
import { ErrorAlert } from './ui'

/* Structured policy builder (Enterprise policy profiles: no JSON boxes for everyday settings). Every control edits the
   same settings/rules JSON the page saves, so the advanced JSON view stays in step. */

const DIMENSIONS: [string, string][] = [['identity', 'Identity'], ['credentials', 'Credentials'], ['jurisdiction', 'Right to practise'],
  ['restrictions', 'Sanctions screening'], ['insurance', 'Indemnity insurance']]
const CLAUSES: [string, string][] = [['CONFIDENTIALITY', 'Confidentiality'], ['IP_OWNERSHIP', 'IP ownership'], ['TERMINATION', 'Termination'],
  ['GOVERNING_LAW', 'Governing law']]
const DEADLINES: [string, string][] = [['acceptanceWindowDays', 'Days to review submitted work'], ['autoAcceptAfterDays', 'Accept automatically after (days)'],
  ['signatureDeadlineDays', 'Days to sign a contract'], ['disputeEvidenceDays', 'Days to add dispute evidence']]
export const ACTIONS: [string, string][] = [['ENGAGEMENT_ELIGIBILITY', 'Sending a request'], ['PROPOSAL_SUBMIT', 'Receiving a proposal'],
  ['PROPOSAL_ACCEPT', 'Accepting a proposal'], ['CONTRACT_SIGN', 'Signing the contract'], ['CHANGE_ORDER_APPROVE', 'Approving a change order'],
  ['ESCROW_FUND', 'Funding escrow'], ['MILESTONE_ACCEPT', 'Accepting work'], ['ESCROW_RELEASE', 'Releasing payment']]
const FIELDS: [string, string, 'money' | 'bool' | 'text' | 'tier'][] = [
  ['engagement.valueMinor', 'Engagement value', 'money'], ['action.amountMinor', 'Amount of this action', 'money'],
  ['engagement.crossBorder', 'Professional in another country', 'bool'], ['engagement.regulated', 'Regulated work', 'bool'],
  ['professional.tier', 'Professional trust tier', 'tier'], ['engagement.type', 'Engagement type', 'text'],
  ['buyer.country', 'Your organisation country', 'text'], ['engagement.currency', 'Currency', 'text']]
const ROLES = ['APPROVER', 'BUDGET_OWNER', 'LEGAL_REVIEWER', 'EXCEPTION_AUTHORITY', 'ORG_ADMIN']
const DECISION_LABEL: Record<string, string> = { REQUIRE_APPROVAL: 'Needs approval', REQUIRE_EXCEPTION: 'Needs an exception', BLOCK: 'Blocked' }

function parse<T>(json: string, fallback: T): T {
  try { const v = JSON.parse(json); return (v ?? fallback) as T } catch { return fallback }
}
const list = (v: unknown) => (Array.isArray(v) ? (v as string[]) : [])

export function PolicySettingsForm({ settings, onChange, disabled }: { settings: string; onChange: (v: string) => void; disabled: boolean }) {
  const s = parse<Record<string, unknown>>(settings, {})
  const set = (key: string, value: unknown) => onChange(JSON.stringify({ ...s, [key]: value }, null, 2))
  const toggle = (key: string, value: string) => { const cur = list(s[key]); set(key, cur.includes(value) ? cur.filter((x) => x !== value) : [...cur, value]) }
  const codes = (key: string, v: string, n: number) => {
    const items = v.split(',').map((x) => x.trim().toUpperCase()).filter((x) => x.length === n)
    set(key, items.length ? items : null)
  }
  return (
    <fieldset disabled={disabled} className="panel policy-form"><legend>Who can be engaged</legend>
      <label>Minimum trust tier
        <select className="input" value={String(s.minTrustTier ?? 'B')} onChange={(e) => set('minTrustTier', e.target.value)}>
          <option value="A">Tier A: fully verified</option><option value="B">Tier B: verified identity</option></select></label>
      <p className="small" style={{ margin: '10px 0 4px' }}>Checks that must be complete</p>
      {DIMENSIONS.map(([k, l]) => <label key={k} className="checkbox small" style={{ display: 'inline-flex', marginRight: 12 }}>
        <input type="checkbox" checked={list(s.requiredDimensions ?? ['identity']).includes(k)} onChange={() => toggle('requiredDimensions', k)} /> <span>{l}</span></label>)}
      <div className="row" style={{ marginTop: 10 }}>
        <label style={{ flex: 1 }}>Countries professionals must serve (two-letter codes; empty: any)
          <input className="input" defaultValue={list(s.allowedJurisdictions).join(', ')} key={`j${list(s.allowedJurisdictions).join()}`}
            onBlur={(e) => codes('allowedJurisdictions', e.target.value, 2)} placeholder="GB, IE, DE" /></label>
        <label style={{ flex: 1 }}>Currencies allowed (empty: any)
          <input className="input" defaultValue={list(s.allowedCurrencies).join(', ')} key={`c${list(s.allowedCurrencies).join()}`}
            onBlur={(e) => codes('allowedCurrencies', e.target.value, 3)} placeholder="USD, EUR" /></label>
      </div>
      <h4 style={{ margin: '14px 0 4px' }}>Deadlines (empty: platform default)</h4>
      <div className="row">{DEADLINES.map(([k, l]) => <label key={k} style={{ flex: 1, minWidth: 150 }}>{l}
        <input className="input" type="number" min={1} max={90} value={typeof s[k] === 'number' ? String(s[k]) : ''}
          onChange={(e) => set(k, e.target.value ? Math.min(90, Math.max(1, Math.round(Number(e.target.value)))) : null)} /></label>)}</div>
      <h4 style={{ margin: '14px 0 4px' }}>Contracts</h4>
      {CLAUSES.map(([k, l]) => <label key={k} className="checkbox small" style={{ display: 'inline-flex', marginRight: 12 }}>
        <input type="checkbox" checked={list(s.requiredClauses ?? CLAUSES.map(([c]) => c)).includes(k)} onChange={() => toggle('requiredClauses', k)} /> <span>{l} clause required</span></label>)}
      <label style={{ display: 'block', marginTop: 8 }}>Governing law (optional)
        <input className="input" value={String(s.governingLaw ?? '')} onChange={(e) => set('governingLaw', e.target.value || null)} placeholder="e.g. England and Wales" /></label>
      <label className="checkbox small" style={{ marginTop: 8 }}><input type="checkbox" checked={s.stepUpForApprovals !== false}
        onChange={(e) => set('stepUpForApprovals', e.target.checked)} /> <span>Approvers confirm with two-step verification</span></label>
    </fieldset>
  )
}

export function RuleBuilder({ rules, onChange, disabled }: { rules: string; onChange: (v: string) => void; disabled: boolean }) {
  const current = parse<PolicyRule[]>(rules, [])
  const [f, setF] = useState({ actions: ['PROPOSAL_ACCEPT'], field: 'engagement.valueMinor', op: 'GT', value: '', decision: 'REQUIRE_APPROVAL', message: '', role: 'APPROVER' })
  const kind = FIELDS.find(([k]) => k === f.field)?.[2] ?? 'text'
  const save = (next: PolicyRule[]) => onChange(JSON.stringify(next, null, 2))
  function add() {
    const value = kind === 'money' ? Math.round(Number(f.value) * 100) : kind === 'bool' ? f.value !== 'false' : f.value.trim().toUpperCase()
    const id = `rule-${current.length + 1}-${Date.now().toString(36).slice(-4)}`
    save([...current, { id, appliesTo: f.actions, condition: { field: f.field, op: kind === 'bool' || kind === 'text' || kind === 'tier' ? 'EQ' : f.op, value },
      decision: f.decision, reasonCode: id.toUpperCase().replace(/-/g, '_'), message: f.message.trim(),
      ...(f.decision === 'REQUIRE_APPROVAL' ? { approval: { mode: 'SINGLE', steps: [{ role: f.role, count: 1 }], timeoutHours: 48, escalationRole: 'ORG_ADMIN' } } : {}) }])
    setF({ ...f, value: '', message: '' })
  }
  const describe = (r: PolicyRule) => {
    const c = r.condition as { field?: string; op?: string; value?: unknown; all?: unknown; any?: unknown }
    if (!c.field) return 'Complex condition (see JSON)'
    const [, label, k] = FIELDS.find(([x]) => x === c.field) ?? [c.field, c.field, 'text']
    const v = k === 'money' ? (Number(c.value) / 100).toLocaleString() : k === 'bool' ? (c.value ? 'yes' : 'no') : String(c.value)
    return `${label} ${({ GT: 'above', GTE: 'at least', LT: 'below', LTE: 'at most', EQ: 'is', NEQ: 'is not' } as Record<string, string>)[c.op ?? ''] ?? c.op} ${v}`
  }
  return (
    <fieldset disabled={disabled} className="panel policy-form"><legend>Rules</legend>
      {current.length === 0 ? <p className="muted small">No rules: only the settings above apply.</p> : (
        <table className="data small"><thead><tr><th>When</th><th>If</th><th>Then</th><th /></tr></thead>
          <tbody>{current.map((r, i) => <tr key={r.id}>
            <td>{r.appliesTo.map((a) => ACTIONS.find(([x]) => x === a)?.[1] ?? a).join(', ')}</td>
            <td>{describe(r)}</td>
            <td>{DECISION_LABEL[r.decision] ?? r.decision}{r.approval && ` (${r.approval.steps.map((s) => s.role.replace(/_/g, ' ').toLowerCase()).join(' + ')})`}
              <div className="muted">{r.message}</div></td>
            <td><button type="button" className="btn btn-ghost btn-sm" onClick={() => save(current.filter((_, j) => j !== i))}>Remove</button></td></tr>)}</tbody></table>)}
      <details style={{ marginTop: 10 }}><summary className="small"><strong>Add a rule</strong></summary>
        <p className="small" style={{ margin: '8px 0 4px' }}>When</p>
        {ACTIONS.map(([k, l]) => <label key={k} className="checkbox small" style={{ display: 'inline-flex', marginRight: 10 }}>
          <input type="checkbox" checked={f.actions.includes(k)} onChange={() => setF({ ...f, actions: f.actions.includes(k) ? f.actions.filter((x) => x !== k) : [...f.actions, k] })} /> <span>{l}</span></label>)}
        <div className="row" style={{ marginTop: 8 }}>
          <label>If<select className="input" value={f.field} onChange={(e) => setF({ ...f, field: e.target.value, value: '' })}>
            {FIELDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          {kind === 'money' && <label>is<select className="input" value={f.op} onChange={(e) => setF({ ...f, op: e.target.value })}>
            <option value="GT">above</option><option value="GTE">at least</option><option value="LT">below</option></select></label>}
          <label>{kind === 'money' ? 'Amount' : 'Value'}
            {kind === 'bool' ? <select className="input" value={f.value || 'true'} onChange={(e) => setF({ ...f, value: e.target.value })}>
              <option value="true">yes</option><option value="false">no</option></select>
              : kind === 'tier' ? <select className="input" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })}>
                <option value="">Choose…</option><option>A</option><option>B</option></select>
              : <input className="input" type={kind === 'money' ? 'number' : 'text'} min={0} value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} />}</label>
        </div>
        <div className="row">
          <label>Then<select className="input" value={f.decision} onChange={(e) => setF({ ...f, decision: e.target.value })}>
            {Object.entries(DECISION_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          {f.decision === 'REQUIRE_APPROVAL' && <label>Approved by<select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{r.replace(/_/g, ' ').toLowerCase()}</option>)}</select></label>}
        </div>
        <label style={{ display: 'block' }}>Message people see (why, and what to do)
          <input className="input" value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} maxLength={500} /></label>
        <button type="button" className="btn btn-secondary btn-sm" style={{ marginTop: 8 }}
          disabled={f.actions.length === 0 || (kind !== 'bool' && !f.value.trim()) || f.message.trim().length < 5} onClick={add}>Add rule</button>
      </details>
    </fieldset>
  )
}

const SEVERITY: Record<string, string> = { ERROR: 'warn', WARNING: '', INFO: 'green' }

/** Checks for the draft and the review-and-activate checklist. */
export function PolicyChecksPanel({ profileId, refreshKey, hasDraft, saved }: { profileId: string; refreshKey: string; hasDraft: boolean; saved: boolean }) {
  const [data, setData] = useState<PolicyChecks | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { policyApi.checks(profileId).then(setData).catch(setError) }, [profileId, refreshKey])
  if (error) return <ErrorAlert error={error} />
  if (!data) return null
  const errors = data.checks.filter((c) => c.severity === 'ERROR')
  return (
    <section className="policy-checks" aria-label="Policy checks">
      <div className="badges" style={{ margin: '12px 0 8px' }}>
        <span className={`badge ${data.riskLevel === 'HIGH' ? 'warn' : data.riskLevel === 'LOW' ? 'green' : ''}`}>{data.riskLevel.toLowerCase()} risk</span>
        <span className="badge">Applies to: {data.appliesTo.join(', ')}</span>
      </div>
      {data.checks.length === 0 ? <p className="small ok-text">No problems found in the {data.version} version.</p> :
        <ul className="checklist">{data.checks.map((c, i) => <li key={i}><span className="small">{c.message}</span>
          <span className={`badge ${SEVERITY[c.severity]}`}>{c.severity.toLowerCase()}</span></li>)}</ul>}
      {hasDraft && <><h4 style={{ margin: '12px 0 4px' }}>Before you activate</h4>
        <ul className="checklist small">
          <li><span>Draft saved</span><span className={`badge ${saved ? 'green' : 'warn'}`}>{saved ? 'yes' : 'save first'}</span></li>
          <li><span>No blocking problems</span><span className={`badge ${errors.length ? 'warn' : 'green'}`}>{errors.length ? `${errors.length} to fix` : 'yes'}</span></li>
          <li><span>Impact on who can be engaged previewed</span><span className="badge">use Preview Impact</span></li>
          <li><span>Two-step confirmation when activating</span><span className="badge">asked on activate</span></li>
        </ul>
        <p className="muted small">Engagements already agreed keep the version they started with.</p></>}
    </section>
  )
}

export function PolicyDashboardView({ orgId }: { orgId: string }) {
  const [days, setDays] = useState(30)
  const [d, setD] = useState<Dashboard | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { policyApi.dashboard(orgId, days).then(setD).catch(setError) }, [orgId, days])
  if (error) return <ErrorAlert error={error} />
  if (!d) return <div className="card panel skeleton" style={{ height: 140 }} aria-busy="true" />
  const pct = (v: number | null) => v == null ? '—' : `${v}%`
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Policy dashboard</h2>
        <select className="input" aria-label="Period" style={{ maxWidth: 160 }} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90, 365].map((n) => <option key={n} value={n}>Last {n} days</option>)}</select></div>
      <div className="stat-row four">
        <div className="card kpi"><strong>{d.evaluations}</strong><span className="muted small">actions checked by policy</span></div>
        <div className="card kpi"><strong>{pct(d.interventionRate)}</strong><span className="muted small">needed approval, exception or were blocked</span></div>
        <div className="card kpi"><strong>{d.approvals.medianHoursToDecide == null ? '—' : `${d.approvals.medianHoursToDecide} h`}</strong><span className="muted small">median time to decide an approval</span></div>
        <div className="card kpi"><strong>{pct(d.exceptions.rate)}</strong><span className="muted small">exception rate ({d.exceptions.requested} requested, {d.exceptions.emergency} emergency)</span></div>
      </div>
      <div className="row" style={{ alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}><h3>Decisions</h3><ul className="checklist small">
          {Object.entries(d.decisions).map(([k, v]) => <li key={k}><span>{k === 'ALLOW' ? 'Allowed' : DECISION_LABEL[k] ?? k}</span><strong>{v}</strong></li>)}
          {Object.keys(d.decisions).length === 0 && <li><span className="muted">Nothing checked yet</span></li>}</ul></div>
        <div style={{ flex: 1 }}><h3>Approvals</h3><ul className="checklist small">
          <li><span>Requested</span><strong>{d.approvals.requested}</strong></li><li><span>Waiting</span><strong>{d.approvals.pending}</strong></li>
          <li><span>Granted / denied</span><strong>{d.approvals.granted} / {d.approvals.denied}</strong></li><li><span>Timed out</span><strong>{d.approvals.expired}</strong></li></ul></div>
        <div style={{ flex: 1 }}><h3>Spend held back</h3><ul className="checklist small">
          {d.spendHeldBack.map((s) => <li key={s.currency}><span>Blocked commitments</span><strong>{formatMoney({ amountMinor: s.amountMinor, currency: s.currency })}</strong></li>)}
          {d.spendHeldBack.length === 0 && <li><span className="muted">None blocked</span></li>}</ul>
          {d.topReasons.length > 0 && <><h3>Most common reasons</h3><ul className="checklist small">
            {d.topReasons.map((r) => <li key={r.code}><span>{r.code.replace(/_/g, ' ').toLowerCase()}</span><strong>{r.count}</strong></li>)}</ul></>}</div>
      </div>
      <p className="muted small">{d.activeProfiles} active and {d.draftProfiles} draft policies. Dry runs and previews are not counted.</p>
    </section>
  )
}
