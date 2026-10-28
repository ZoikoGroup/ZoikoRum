import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  formatMoney, ORG_ROLE_INFO, ORG_ROLES, orgApi,
  type BusinessUnit, type CostCenter, type Invitation, type Organization, type OrgMember, type OrgRole,
} from '../api/orgs'
import { ErrorAlert, Field, useDialog, useStepUp, Loading } from '../components/ui'
import { ApiError } from '../api/client'
import { policyApi, type CurrencyAmount, type PolicyDashboard, type PolicySetup, type ProfileInsight } from '../api/policy'
import { ActionList, greeting, Icon, type Action } from '../components/dashboard'
import { EmptyTable, PortalHeader, StatCard } from '../components/portal'
import { AuditExportButtons } from '../components/AuditExport'
import { saveBlob } from '../lib/exports'
import { useAuth } from '../auth/AuthContext'

const CURRENCIES = ['USD', 'GBP', 'EUR', 'INR', 'CAD', 'AUD', 'SGD', 'AED']

/** The enterprise organization the signed-in user works in (first non-individual one). */
// eslint-disable-next-line react-refresh/only-export-components
export function useEnterpriseOrg() {
  const [org, setOrg] = useState<Organization | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const alive = useRef(true)
  const reload = useCallback(async () => {
    try {
      setError(null)
      // Right after sign-up the organization is created by the background worker,
      // usually within a second: retry briefly instead of showing an empty page.
      for (let attempt = 0; attempt < 10 && alive.current; attempt++) {
        const found = (await orgApi.mine()).find((o) => o.orgType !== 'INDIVIDUAL') ?? null
        if (alive.current) setOrg(found)
        if (found) break
        await new Promise((r) => setTimeout(r, 800))
      }
    } catch (err) {
      if (alive.current) setError(err)
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [])
  useEffect(() => { alive.current = true; reload(); return () => { alive.current = false } }, [reload])
  return { org, loading, error, reload, isAdmin: !!org?.myRoles.includes('ORG_ADMIN') }
}

export function RoleBadges({ roles }: { roles: string[] }) {
  return (
    <div className="badges">
      {roles.map((r) => <span key={r} className="badge">{ORG_ROLE_INFO[r as OrgRole]?.label ?? r}</span>)}
    </div>
  )
}

function RolePicker({ value, onChange, labelledBy }: { value: OrgRole[]; onChange: (roles: OrgRole[]) => void; labelledBy: string }) {
  const toggle = (r: OrgRole) => onChange(value.includes(r) ? value.filter((x) => x !== r) : [...value, r])
  return (
    <div className="role-grid" role="group" aria-labelledby={labelledBy}>
      {ORG_ROLES.map((r) => (
        <label key={r} className="role-option">
          <input type="checkbox" checked={value.includes(r)} onChange={() => toggle(r)} />
          <span><strong>{ORG_ROLE_INFO[r].label}</strong><span className="muted small">{ORG_ROLE_INFO[r].desc}</span></span>
        </label>
      ))}
    </div>
  )
}

function SpendLimitInput({ id, amount, currency, onAmount, onCurrency }: {
  id: string; amount: string; currency: string; onAmount: (v: string) => void; onCurrency: (v: string) => void
}) {
  return (
    <div className="row" style={{ alignItems: 'stretch' }}>
      <input id={id} className="input" style={{ flex: 1 }} inputMode="decimal" placeholder="e.g. 50000"
        value={amount} onChange={(e) => onAmount(e.target.value.replace(/[^\d.]/g, ''))} />
      <select className="input" style={{ width: 110 }} aria-label="Currency" value={currency} onChange={(e) => onCurrency(e.target.value)}>
        {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
      </select>
    </div>
  )
}

const toMinor = (amount: string) => Math.round(parseFloat(amount) * 100)

export function EnterpriseTeamPage() {
  const { org, loading, error: orgError, isAdmin } = useEnterpriseOrg()
  const [members, setMembers] = useState<OrgMember[]>([])
  const [invites, setInvites] = useState<Invitation[]>([])
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<{ text: string; link?: string | null } | null>(null)
  const [email, setEmail] = useState('')
  const [roles, setRoles] = useState<OrgRole[]>(['REQUESTER'])
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [editing, setEditing] = useState<OrgMember | null>(null)
  const { run, modal } = useStepUp(setError)

  const load = useCallback(async () => {
    if (!org) return
    try {
      setMembers(await orgApi.members(org.id))
      if (org.myRoles.includes('ORG_ADMIN')) setInvites(await orgApi.invitations(org.id))
    } catch (err) {
      setError(err)
    }
  }, [org])
  useEffect(() => { load() }, [load])

  if (loading) return <Loading />
  if (!org) return <><ErrorAlert error={orgError} /><p className="muted">Your enterprise organization is still being set up. Refresh in a moment.</p></>

  function sendInvite(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setNotice(null)
    run(async () => {
      const inv = await orgApi.invite(org!.id, {
        email: email.trim(), roles,
        spendLimit: amount ? { amountMinor: toMinor(amount), currency } : null,
      })
      setNotice({ text: `Invitation sent to ${inv.email}. It expires in 7 days.`, link: inv.devInviteUrl })
      setEmail('')
      setAmount('')
      setRoles(['REQUESTER'])
      await load()
    })
  }

  function revoke(inv: Invitation) {
    run(async () => {
      await orgApi.revokeInvitation(org!.id, inv.id)
      setNotice({ text: `Invitation to ${inv.email} revoked.` })
      await load()
    })
  }

  function remove(m: OrgMember) {
    if (!confirm(`Remove ${m.displayName} from ${org!.name}? They lose access immediately.`)) return
    run(async () => {
      await orgApi.removeMember(org!.id, m.identityId)
      setNotice({ text: `${m.displayName} was removed.` })
      await load()
    })
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Team &amp; roles</h1>
          <p className="muted" style={{ margin: 0 }}>{org.name} · Who can request, approve and release spend.</p>
        </div>
      </div>
      <ErrorAlert error={error} />
      {notice && (
        <div className="alert alert-success" role="status">
          {notice.text}
          {notice.link && (
            <span className="ref">Development mode (no email provider yet). Share this link: <a href={notice.link}>{notice.link}</a></span>
          )}
        </div>
      )}

      {isAdmin && (
        <section className="card panel">
          <h2>Invite a team member</h2>
          <p className="muted small">They'll get an invitation link. Accounts are matched by email address.</p>
          <form onSubmit={sendInvite}>
            <Field label="Work email" id="inv-email">
              <input id="inv-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <div className="field">
              <span className="field-title" id="invite-roles">Roles</span>
              <RolePicker value={roles} onChange={setRoles} labelledBy="invite-roles" />
            </div>
            <div className="field" style={{ maxWidth: 360 }}>
              <label htmlFor="invite-spend-limit">Approval spend limit (optional)</label>
              <SpendLimitInput id="invite-spend-limit" amount={amount} currency={currency} onAmount={setAmount} onCurrency={setCurrency} />
              <span className="hint">The most this person can approve per engagement or release. Leave empty for no approval authority.</span>
            </div>
            <button className="btn btn-primary" disabled={!email || roles.length === 0}>Send invitation</button>
          </form>
        </section>
      )}

      <section className="card panel">
        <h2>Members ({members.length})</h2>
        <div style={{ overflowX: 'auto' }}>
          <table className="data">
            <thead><tr><th>Name</th><th>Roles</th><th>Spend limit</th>{isAdmin && <th aria-label="Actions" />}</tr></thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.identityId}>
                  <td><strong>{m.displayName}</strong><div className="muted small">{m.email}</div></td>
                  <td><RoleBadges roles={m.roles} /></td>
                  <td>{m.spendLimit ? formatMoney(m.spendLimit) : m.roles.includes('ORG_ADMIN') ? 'Unlimited' : 'None'}</td>
                  {isAdmin && (
                    <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                      <button className="btn btn-secondary btn-sm" onClick={() => setEditing(m)}>Edit</button>{' '}
                      <button className="btn btn-danger btn-sm" onClick={() => remove(m)}>Remove</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {isAdmin && invites.length > 0 && (
        <section className="card panel">
          <h2>Pending invitations</h2>
          <table className="data">
            <thead><tr><th>Email</th><th>Roles</th><th>Expires</th><th aria-label="Actions" /></tr></thead>
            <tbody>
              {invites.map((i) => (
                <tr key={i.id}>
                  <td>{i.email}</td>
                  <td><RoleBadges roles={i.roles} /></td>
                  <td>{new Date(i.expiresAt).toLocaleDateString()}</td>
                  <td style={{ textAlign: 'right' }}><button className="btn btn-danger btn-sm" onClick={() => revoke(i)}>Revoke</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {editing && (
        <EditMemberModal orgId={org.id} member={editing} onClose={() => setEditing(null)} run={run} setError={setError}
          onSaved={async (name) => { setEditing(null); setNotice({ text: `${name}'s access was updated.` }); await load() }} />
      )}
      {modal}
    </>
  )
}

function EditMemberModal({ orgId, member, onClose, onSaved, run, setError }: {
  orgId: string; member: OrgMember; onClose: () => void; onSaved: (name: string) => Promise<void>
  run: (action: () => Promise<void>) => Promise<void>; setError: (e: unknown) => void
}) {
  const dialog = useDialog(onClose)
  const [roles, setRoles] = useState<OrgRole[]>(member.roles)
  const [amount, setAmount] = useState(member.spendLimit ? String(member.spendLimit.amountMinor / 100) : '')
  const [currency, setCurrency] = useState(member.spendLimit?.currency ?? 'USD')

  function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    run(async () => {
      await orgApi.updateMember(orgId, member.identityId, amount
        ? { roles, spendLimit: { amountMinor: toMinor(amount), currency } }
        : { roles, clearSpendLimit: true })
      await onSaved(member.displayName)
    })
  }

  return (
    <div ref={dialog} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="edit-title">
      <form className="card modal" style={{ maxWidth: 620 }} onSubmit={save}>
        <h2 id="edit-title">Edit {member.displayName}</h2>
        <p className="muted small">{member.email}</p>
        <div className="field"><span className="field-title" id="edit-roles">Roles</span><RolePicker value={roles} onChange={setRoles} labelledBy="edit-roles" /></div>
        <div className="field">
          <label htmlFor="edit-spend-limit">Approval spend limit</label>
          <SpendLimitInput id="edit-spend-limit" amount={amount} currency={currency} onAmount={setAmount} onCurrency={setCurrency} />
          <span className="hint">Leave empty to remove approval authority (Org Admins are unlimited).</span>
        </div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={roles.length === 0}>Save changes</button>
        </div>
      </form>
    </div>
  )
}

export function EnterpriseStructurePage() {
  const { org, loading, error: orgError, isAdmin } = useEnterpriseOrg()
  const [units, setUnits] = useState<BusinessUnit[]>([])
  const [centers, setCenters] = useState<CostCenter[]>([])
  const [error, setError] = useState<unknown>(null)
  const [unitName, setUnitName] = useState('')
  const [cc, setCc] = useState({ name: '', code: '', unit: '', amount: '', currency: 'USD' })
  const [merge, setMerge] = useState({ from: '', into: '' })
  const { run, modal } = useStepUp(setError)
  const canManageCostCenters = !!org?.myRoles.some((r) => r === 'ORG_ADMIN' || r === 'BUDGET_OWNER')

  const load = useCallback(async () => {
    if (!org) return
    try {
      setUnits(await orgApi.businessUnits(org.id))
      setCenters(await orgApi.costCenters(org.id))
    } catch (err) {
      setError(err)
    }
  }, [org])
  useEffect(() => { load() }, [load])
  if (loading) return <Loading />
  if (!org) return <><ErrorAlert error={orgError} />{!orgError && <p className="muted">Your enterprise organization is still being set up. Refresh in a moment.</p>}</>

  async function addUnit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await orgApi.createBusinessUnit(org!.id, unitName.trim())
      setUnitName('')
      await load()
    } catch (err) {
      setError(err)
    }
  }

  function mergeUnits(e: FormEvent) {
    e.preventDefault()
    const from = units.find((u) => u.id === merge.from)?.name, into = units.find((u) => u.id === merge.into)?.name
    if (!confirm(`Fold "${from}" into "${into}"? Its sub-units, cost centers, members and policies move to "${into}", and "${from}" is removed.`)) return
    setError(null)
    run(async () => { setUnits(await orgApi.mergeBusinessUnits(org!.id, merge.from, merge.into)); setMerge({ from: '', into: '' }); await load() })
  }

  async function addCenter(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await orgApi.createCostCenter(org!.id, {
        name: cc.name.trim(), code: cc.code.trim(), businessUnitId: cc.unit || null,
        quarterlyBudget: cc.amount ? { amountMinor: toMinor(cc.amount), currency: cc.currency } : null,
      })
      setCc({ name: '', code: '', unit: '', amount: '', currency: cc.currency })
      await load()
    } catch (err) {
      setError(err)
    }
  }

  const unitName_ = (id: string | null) => units.find((u) => u.id === id)?.name ?? '—'

  return (
    <>
      <div className="page-head"><div><h1>Organization structure</h1>
        <p className="muted" style={{ margin: 0 }}>{org.name} · Business units and cost centers used for spend control.</p></div></div>
      <ErrorAlert error={error} />
      {modal}
      <DefinePolicyPrompt org={org} onChanged={load} />
      <section className="card panel">
        <h2>Business units</h2>
        {units.length === 0 ? <p className="muted">No business units yet.</p> : (
          <div className="badges" style={{ marginBottom: 16 }}>{units.map((u) => <span key={u.id} className="badge">{u.name}</span>)}</div>
        )}
        {isAdmin && (
          <form className="row" onSubmit={addUnit}>
            <Field label="New business unit" id="bu-name">
              <input id="bu-name" className="input" value={unitName} onChange={(e) => setUnitName(e.target.value)} placeholder="e.g. Finance" />
            </Field>
            <button className="btn btn-primary" disabled={!unitName.trim()}>Add</button>
          </form>
        )}
        {isAdmin && units.length > 1 && (
          <form className="row" onSubmit={mergeUnits} style={{ marginTop: 12 }}>
            <Field label="Merge business unit" id="bu-from">
              <select id="bu-from" className="input" value={merge.from} onChange={(e) => setMerge({ ...merge, from: e.target.value })}>
                <option value="">Choose…</option>{units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>
            </Field>
            <Field label="into" id="bu-into">
              <select id="bu-into" className="input" value={merge.into} onChange={(e) => setMerge({ ...merge, into: e.target.value })}>
                <option value="">Choose…</option>{units.filter((u) => u.id !== merge.from).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>
            </Field>
            <button className="btn btn-secondary" disabled={!merge.from || !merge.into}>Merge</button>
          </form>
        )}
      </section>
      <section className="card panel">
        <h2>Cost centers</h2>
        {centers.length === 0 ? <p className="muted">No cost centers yet.</p> : (
          <table className="data" style={{ marginBottom: 16 }}>
            <thead><tr><th>Code</th><th>Name</th><th>Business unit</th><th>Quarterly budget</th></tr></thead>
            <tbody>{centers.map((c) => (
              <tr key={c.id}><td><code>{c.code}</code></td><td>{c.name}</td><td>{unitName_(c.businessUnitId)}</td><td>{formatMoney(c.quarterlyBudget)}</td></tr>
            ))}</tbody>
          </table>
        )}
        {canManageCostCenters && (
          <form onSubmit={addCenter}>
            <div className="row">
              <Field label="Name" id="cc-name"><input id="cc-name" className="input" value={cc.name} onChange={(e) => setCc({ ...cc, name: e.target.value })} /></Field>
              <Field label="Code" id="cc-code" hint="Letters, numbers, - . _"><input id="cc-code" className="input" value={cc.code} onChange={(e) => setCc({ ...cc, code: e.target.value })} /></Field>
              <Field label="Business unit" id="cc-unit">
                <select id="cc-unit" className="input" value={cc.unit} onChange={(e) => setCc({ ...cc, unit: e.target.value })}>
                  <option value="">None</option>
                  {units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                </select>
              </Field>
            </div>
            <div className="field" style={{ maxWidth: 360, marginTop: 12 }}>
              <label htmlFor="cost-center-budget">Quarterly budget (optional)</label>
              <SpendLimitInput id="cost-center-budget" amount={cc.amount} currency={cc.currency} onAmount={(v) => setCc({ ...cc, amount: v })} onCurrency={(v) => setCc({ ...cc, currency: v })} />
            </div>
            <button className="btn btn-primary" disabled={!cc.name.trim() || !cc.code.trim()}>Add cost center</button>
          </form>
        )}
      </section>
    </>
  )
}

const WIZARD_TEMPLATES: [string, string, string][] = [
  ['ENTERPRISE_STANDARD', 'Enterprise standard', 'Verified identity; an approver signs off each payment release.'],
  ['REGULATED', 'Regulated work', 'Green trust light only (fully verified), all checks complete; finance and a budget owner approve releases.'],
  ['CROSS_BORDER', 'Cross-border', 'Right to practise and screening verified; Legal approves engagements abroad.'],
  ['GROWTH_ADVISORY', 'Growth advisory', 'Verified identity; an approver only for engagements above 25,000.'],
]
const WIZARD_STEPS = ['Organisation basics', 'Policy template', 'Approvers', 'Budgets and cost centres', 'Review']
const WIZARD_TIME_ZONES = ['UTC', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Chicago', 'America/Los_Angeles',
  'Asia/Kolkata', 'Asia/Singapore', 'Asia/Dubai', 'Australia/Sydney', 'Africa/Johannesburg']
const APPROVER_ROLES: OrgRole[] = ['APPROVER', 'BUDGET_OWNER', 'LEGAL_REVIEWER', 'EXCEPTION_AUTHORITY']

/** Procurement setup wizard for enterprise admins (first run): organisation basics, a policy from a template,
    approvers, budgets and cost centres, then a review of what is in place. Each step saves on its own. */
export function ProcurementSetupWizard({ org, onClose, onChanged }: { org: Organization; onClose?: () => void; onChanged?: () => void }) {
  const [step, setStep] = useState(0)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [setup, setSetup] = useState<PolicySetup | null>(null)
  const [current, setCurrent] = useState(org)
  const [basics, setBasics] = useState({ industry: org.industry ?? '', timeZone: org.timeZone ?? 'UTC' })
  const [template, setTemplate] = useState('ENTERPRISE_STANDARD')
  const [policyName, setPolicyName] = useState('Procurement policy')
  const [invite, setInvite] = useState<{ email: string; roles: OrgRole[] }>({ email: '', roles: ['APPROVER'] })
  const [invited, setInvited] = useState<string[]>([])
  const [cc, setCc] = useState({ name: '', code: '', amount: '', currency: 'USD' })
  const [notice, setNotice] = useState<string | null>(null)
  const { run, modal } = useStepUp(setError)

  const refresh = useCallback(async () => { setSetup(await policyApi.setup(org.id)) }, [org.id])
  useEffect(() => { refresh().catch(setError) }, [refresh])

  async function save(work: () => Promise<unknown>, message: string, next = true) {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await work()
      await refresh()
      onChanged?.()
      setNotice(message)
      if (next) setStep((s) => Math.min(s + 1, WIZARD_STEPS.length - 1))
    } catch (err) {
      if (err instanceof ApiError && err.code === 'STEP_UP_REQUIRED') throw err
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const roles = setup?.facts.roles ?? {}

  function saveBasics(e: FormEvent) {
    e.preventDefault()
    save(async () => setCurrent(await orgApi.update(org.id, current.version, basics)), 'Organisation details saved.')
  }
  function createPolicy() {
    run(() => save(async () => {
      const created = await policyApi.create({ orgId: org.id, name: policyName.trim(), description: 'Created in procurement setup', template })
      await policyApi.activate(created.id)
    }, 'Policy created and active.'))
  }
  function sendInvite(e: FormEvent) {
    e.preventDefault()
    const email = invite.email.trim()
    save(async () => {
      await orgApi.invite(org.id, { email, roles: invite.roles })
      setInvited((list) => [...list, email])
      setInvite({ email: '', roles: ['APPROVER'] })
    }, 'Invitation sent.', false)
  }
  function addCentre(e: FormEvent) {
    e.preventDefault()
    save(async () => {
      await orgApi.createCostCenter(org.id, { name: cc.name.trim(), code: cc.code.trim(),
        quarterlyBudget: cc.amount ? { amountMinor: toMinor(cc.amount), currency: cc.currency } : null })
      setCc({ name: '', code: '', amount: '', currency: cc.currency })
    }, 'Cost centre added.', false)
  }

  return (
    <section className="card panel" aria-label="Procurement setup">
      <div className="panel-head"><h2>Set up procurement</h2>
        {onClose && <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>}</div>
      <ol className="badges" style={{ listStyle: 'none', padding: 0, margin: '0 0 12px' }}>
        {WIZARD_STEPS.map((label, i) => (
          <li key={label}><button type="button" className={`badge ${i === step ? 'green' : ''}`} aria-current={i === step ? 'step' : undefined}
            onClick={() => setStep(i)}>{i + 1}. {label}</button></li>))}
      </ol>
      <ErrorAlert error={error} />
      {modal}
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      {step === 0 && (
        <form onSubmit={saveBasics}>
          <p className="muted small">{current.name} · {current.country}. Approvers see these details when they decide.</p>
          <div className="row">
            <Field label="Industry" id="wiz-industry"><input id="wiz-industry" className="input" value={basics.industry} maxLength={80}
              onChange={(e) => setBasics({ ...basics, industry: e.target.value })} placeholder="e.g. Financial Services" /></Field>
            <Field label="Time zone" id="wiz-tz"><select id="wiz-tz" className="input" value={basics.timeZone}
              onChange={(e) => setBasics({ ...basics, timeZone: e.target.value })}>{WIZARD_TIME_ZONES.map((t) => <option key={t}>{t}</option>)}</select></Field>
          </div>
          <button className="btn btn-primary" disabled={busy || !basics.industry.trim()}>Save and continue</button>
        </form>
      )}

      {step === 1 && (setup?.hasActivePolicy ? (
        <div>
          <p className="small ok-text">A policy is active. You can refine it on the Policies page.</p>
          <button type="button" className="btn btn-secondary" onClick={() => setStep(2)}>Continue</button>
        </div>
      ) : (
        <div>
          <p className="muted small">Start from a template; you can adjust every rule later. It applies to new engagements only.</p>
          <div className="stat-row four" role="radiogroup" aria-label="Policy template">{WIZARD_TEMPLATES.map(([key, name, text]) => (
            <label key={key} className="card panel" style={{ cursor: 'pointer', borderColor: template === key ? 'var(--zk-green)' : undefined }}>
              <input type="radio" name="wiz-template" value={key} checked={template === key} onChange={() => setTemplate(key)} /> <strong>{name}</strong>
              <span className="small muted" style={{ display: 'block' }}>{text}</span></label>))}</div>
          <Field label="Policy name" id="wiz-policy-name"><input id="wiz-policy-name" className="input" value={policyName} maxLength={80}
            onChange={(e) => setPolicyName(e.target.value)} /></Field>
          <button type="button" className="btn btn-primary" disabled={busy || policyName.trim().length < 2} onClick={createPolicy}>Create and activate</button>
          <p className="small muted">Activating asks for two-step confirmation.</p>
        </div>
      ))}

      {step === 2 && (
        <form onSubmit={sendInvite}>
          <p className="muted small">Approvers sign off engagements and releases; an Exception Authority decides policy exceptions. Nobody approves their own request.</p>
          <ul className="checklist small">
            {APPROVER_ROLES.map((r) => (
              <li key={r}><span>{ORG_ROLE_INFO[r].label}</span><span className={`badge ${roles[r] ? 'green' : 'warn'}`}>{roles[r] ?? 0} people</span></li>))}
          </ul>
          <Field label="Invite by email" id="wiz-invite"><input id="wiz-invite" className="input" type="email" value={invite.email}
            onChange={(e) => setInvite({ ...invite, email: e.target.value })} placeholder="name@company.com" /></Field>
          <p id="wiz-roles" className="small" style={{ margin: '8px 0 4px' }}>Roles</p>
          <RolePicker value={invite.roles} onChange={(r) => setInvite({ ...invite, roles: r })} labelledBy="wiz-roles" />
          {invited.length > 0 && <p className="small muted">Invited: {invited.join(', ')}</p>}
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn-secondary" disabled={busy || !invite.email.includes('@') || invite.roles.length === 0}>Send invitation</button>
            <button type="button" className="btn btn-primary" onClick={() => setStep(3)}>Continue</button>
          </div>
        </form>
      )}

      {step === 3 && (
        <form onSubmit={addCentre}>
          <p className="muted small">Requests are charged to a cost centre; a quarterly budget sends anything above it to an Exception Authority.
            {setup ? ` ${setup.facts.costCenters ?? 0} cost centres so far.` : ''}</p>
          <div className="row">
            <Field label="Name" id="wiz-cc-name"><input id="wiz-cc-name" className="input" value={cc.name} onChange={(e) => setCc({ ...cc, name: e.target.value })} /></Field>
            <Field label="Code" id="wiz-cc-code" hint="Letters, numbers, - . _"><input id="wiz-cc-code" className="input" value={cc.code} onChange={(e) => setCc({ ...cc, code: e.target.value })} /></Field>
          </div>
          <div className="field" style={{ maxWidth: 360 }}>
            <label htmlFor="wiz-cc-budget">Quarterly budget (optional)</label>
            <SpendLimitInput id="wiz-cc-budget" amount={cc.amount} currency={cc.currency} onAmount={(v) => setCc({ ...cc, amount: v })} onCurrency={(v) => setCc({ ...cc, currency: v })} />
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn-secondary" disabled={busy || !cc.name.trim() || !cc.code.trim()}>Add cost centre</button>
            <button type="button" className="btn btn-primary" onClick={() => setStep(4)}>Continue</button>
          </div>
        </form>
      )}

      {step === 4 && (
        <div>
          {!setup ? <Loading /> : (
            <ul className="checklist">{setup.steps.map((s) => (
              <li key={s.key}><span>{s.label}</span><span className={`badge ${s.done ? 'green' : 'warn'}`}>{s.done ? 'done' : 'to do'}</span></li>))}</ul>)}
          <p className="small muted">{setup?.complete ? 'Procurement is set up. New engagements follow your policy.'
            : 'You can come back to any step. Until a policy is active, the platform baseline applies: escrow before work and verified professionals.'}</p>
          {onClose && <button type="button" className="btn btn-primary" onClick={onClose}>Finish</button>}
        </div>
      )}
    </section>
  )
}

/** "Define your policy": shown to enterprise admins while the organisation has no policy profile (needsPolicySetup). */
export function DefinePolicyPrompt({ org, onChanged }: { org: Organization; onChanged?: () => void }) {
  const [setup, setSetup] = useState<PolicySetup | null>(null)
  const [open, setOpen] = useState(false)
  const load = useCallback(() => { policyApi.setup(org.id).then(setSetup).catch(() => setSetup(null)) }, [org.id])
  useEffect(() => { load() }, [load])
  if (!setup?.needsPolicySetup || !org.myRoles.includes('ORG_ADMIN')) return null
  if (open) return <ProcurementSetupWizard org={org} onClose={() => { setOpen(false); load() }} onChanged={onChanged} />
  return (
    <div className="alert alert-info" role="status" style={{ marginBottom: 16 }}>
      <strong>Define your policy.</strong> {setup.firstEngagement ? 'Before your first engagement, decide' : 'Decide'} who can be
      engaged, who approves, and your budgets. Until then the platform baseline applies.{' '}
      <button type="button" className="btn btn-primary btn-sm" onClick={() => setOpen(true)}>Set up procurement</button>
    </div>
  )
}

/** Enterprise home: the organization, your roles, and team setup progress. */


/* ---------------------------------------------------------------------------------------------------------------
   Enterprise dashboard (Enterprise Policy doc, "Enterprise Admin Dashboard: Policy view"): active policies,
   engagements and exceptions per policy, spend exposure, approval bottlenecks, sortable table, drill-down, export.
   Reads the policy dashboard endpoints; engagement and payment widgets of the buyer home are linked, not repeated. */

const titleCase = (r: string) => r.toLowerCase().replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
const hoursText = (h: number | null | undefined) => (h == null ? '—' : h < 48 ? `${Math.round(h)} h` : `${(h / 24).toFixed(1)} days`)
const moneyText = (list: CurrencyAmount[]) => (list.length ? list.map((m) => formatMoney(m)).join(' + ') : '—')

/** Sums per currency, never converted. */
// eslint-disable-next-line react-refresh/only-export-components
export function sumMoney(lists: CurrencyAmount[][]): CurrencyAmount[] {
  const totals = new Map<string, number>()
  for (const list of lists) for (const m of list) totals.set(m.currency, (totals.get(m.currency) ?? 0) + m.amountMinor)
  return [...totals].sort(([a], [b]) => a.localeCompare(b)).map(([currency, amountMinor]) => ({ currency, amountMinor }))
}

type PolicySort = 'name' | 'engagements' | 'exceptions' | 'exposure' | 'pending' | 'wait'
const POLICY_SORT: Record<PolicySort, (p: ProfileInsight) => number | string> = {
  name: (p) => p.name.toLowerCase(), engagements: (p) => p.engagements, exceptions: (p) => p.exceptions.requested,
  exposure: (p) => p.spendExposure.reduce((a, m) => a + m.amountMinor, 0), pending: (p) => p.approvals.pending,
  wait: (p) => p.bottleneck?.medianHoursWait ?? -1,
}

export function EnterpriseDashboard() {
  const { user } = useAuth()
  const { org, loading, error: orgError, isAdmin } = useEnterpriseOrg()
  const [days, setDays] = useState(30)
  const [summary, setSummary] = useState<PolicyDashboard | null>(null)
  const [profiles, setProfiles] = useState<ProfileInsight[] | null>(null)
  const [dataError, setDataError] = useState<unknown>(null)
  const [error, setError] = useState<unknown>(null)
  const [sort, setSort] = useState<{ key: PolicySort; desc: boolean }>({ key: 'exposure', desc: true })
  const [admin, setAdmin] = useState<{ members: number; hasAuthority: boolean; units: number; invites: number } | null>(null)
  const [exporting, setExporting] = useState(false)
  const [reloads, setReloads] = useState(0)
  const orgId = org?.id

  useEffect(() => {
    if (!orgId) return
    let live = true
    setDataError(null); setSummary(null); setProfiles(null)
    Promise.all([policyApi.dashboard(orgId, days), policyApi.byProfile(orgId, days)])
      .then(([s, b]) => { if (live) { setSummary(s); setProfiles(b.profiles) } })
      .catch((e) => { if (live) setDataError(e) })
    return () => { live = false }
  }, [orgId, days, reloads])

  useEffect(() => {
    if (!orgId || !isAdmin) return
    let live = true
    Promise.all([orgApi.members(orgId), orgApi.businessUnits(orgId), orgApi.invitations(orgId)])
      .then(([ms, units, inv]) => { if (live) setAdmin({ members: ms.length, units: units.length, invites: inv.length,
        hasAuthority: ms.some((m) => m.roles.includes('EXCEPTION_AUTHORITY') && !m.roles.includes('ORG_ADMIN')) }) })
      .catch(() => { /* the admin to-do list is optional: the dashboard stays usable */ })
    return () => { live = false }
  }, [orgId, isAdmin])

  const rows = useMemo(() => [...(profiles ?? [])].sort((a, b) => {
    const x = POLICY_SORT[sort.key](a), y = POLICY_SORT[sort.key](b)
    const order = x < y ? -1 : x > y ? 1 : 0
    return sort.desc ? -order : order
  }), [profiles, sort])
  const bottlenecks = useMemo(() => (profiles ?? []).filter((p) => p.bottleneck && p.bottleneck.pending > 0)
    .sort((a, b) => (b.bottleneck?.medianHoursWait ?? 0) - (a.bottleneck?.medianHoursWait ?? 0)), [profiles])

  if (!user) return null
  const q = org ? `orgId=${org.id}` : ''
  const exposure = sumMoney((profiles ?? []).map((p) => p.spendExposure))
  const engagements = (profiles ?? []).reduce((a, p) => a + p.engagements, 0)
  const openExceptions = (profiles ?? []).reduce((a, p) => a + p.exceptions.pending, 0)
  const pending = summary?.approvals.pending ?? 0
  const figures = summary && profiles ? { summary, profiles } : null

  const actions: Action[] = []
  if (org && summary && summary.activeProfiles === 0) actions.push({ title: 'Activate a policy', detail: 'No policy is active: engagements are not governed yet', priority: 'High', to: `/app/policies?${q}`, icon: 'contract' })
  if (org && pending > 0) actions.push({ title: `${pending} approval${pending > 1 ? 's' : ''} pending`, detail: 'Work waits until the approvers decide', priority: 'Medium', to: `/app/policies?${q}&tab=approvals`, icon: 'shield' })
  if (org && openExceptions > 0) actions.push({ title: `${openExceptions} open exception${openExceptions > 1 ? 's' : ''}`, detail: 'Waiting for the Exception Authority', priority: 'Medium', to: `/app/policies?${q}&tab=exceptions`, icon: 'alert' })
  if (isAdmin && admin) {
    if (admin.members <= 1) actions.push({ title: 'Invite your team', detail: 'Add requesters, approvers and budget owners', priority: 'Medium', to: '/app/enterprise/team', icon: 'team' })
    if (!admin.hasAuthority) actions.push({ title: 'Name an Exception Authority', detail: 'Must be someone other than an Org Admin', priority: 'Medium', to: '/app/enterprise/team', icon: 'shield' })
    if (admin.units === 0) actions.push({ title: 'Add business units and cost centers', detail: 'Used for budgets and approval routing', priority: 'Low', to: '/app/enterprise/structure', icon: 'building' })
    if (admin.invites > 0) actions.push({ title: `${admin.invites} invitation${admin.invites > 1 ? 's' : ''} not yet accepted`, detail: 'Remind your colleagues or resend', priority: 'Low', to: '/app/enterprise/team', icon: 'mail' })
  }

  const header = (key: PolicySort, text: string) => (
    <th scope="col" aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className="link-button" onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'name' }))}>
        {text}{sort.key === key ? (sort.desc ? ' ↓' : ' ↑') : ''}</button>
    </th>
  )

  async function exportPolicyCsv() {
    if (!org) return
    setExporting(true)
    try { saveBlob(`zoikorum-policy-profiles-${days}d.csv`, await policyApi.byProfileCsv(org.id, days)) }
    catch (e) { setError(e) }
    finally { setExporting(false) }
  }

  const val = (v: () => string | number) => (figures ? v() : '…')
  const canAudit = !!org && (org.myRoles.includes('ORG_ADMIN') || org.myRoles.includes('LEGAL_REVIEWER'))
  return (
    <>
      <PortalHeader eyebrow="Enterprise admin" title={greeting(user.displayName)}
        subtitle={<>{org ? `${org.name} · ` : ''}Policy view: what your policies govern, who is holding approvals up, and where spend is exposed.</>}
        actions={<>
          <select className="input" aria-label="Period" style={{ maxWidth: 160 }} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90, 365].map((n) => <option key={n} value={n}>Last {n} days</option>)}</select>
          <button type="button" className="btn btn-secondary" disabled={!org || !profiles?.length || exporting} onClick={() => { exportPolicyCsv() }}>
            <Icon name="download" /> Export policy view (CSV)</button>
        </>} />
      <ErrorAlert error={orgError ?? dataError ?? error} />
      {dataError ? <p><button type="button" className="btn btn-secondary btn-sm" onClick={() => setReloads((n) => n + 1)}>Try again</button></p> : null}
      {loading && <Loading lines={4} />}
      {!loading && !org && !orgError && (
        <section className="card panel"><div className="panel-head"><h2><Icon name="gear" /> Enterprise controls</h2></div>
          <p className="muted small" style={{ margin: 0 }}>Your enterprise organisation is still being set up. Refresh in a moment.</p></section>)}

      {org && <>
        <div className="stat-row auto">
          <StatCard icon="contract" tone="blue" label="Active policies" value={val(() => figures!.summary.activeProfiles)}
            sub={figures ? `${figures.summary.draftProfiles} in draft` : 'Loading'} to={`/app/policies?${q}`} />
          <StatCard icon="briefcase" tone="green" label="Engagements under policy" value={val(() => engagements)} sub={`Accepted in the last ${days} days`} to="/app/engagements" />
          <StatCard icon="alert" tone="amber" label="Open exceptions" value={val(() => openExceptions)}
            sub={figures ? `${figures.summary.exceptions.requested} requested in period` : 'Loading'} to={`/app/policies?${q}&tab=exceptions`} />
          <StatCard icon="wallet" tone="teal" label="Spend exposure" value={val(() => moneyText(exposure))} sub="Per currency, never converted" />
          <StatCard icon="shield" tone="violet" label="Approvals pending" value={val(() => pending)} sub={pending ? 'Needs an approver' : 'None waiting'} to={`/app/policies?${q}&tab=approvals`} />
          <StatCard icon="lock" tone="red" label="Blocked by policy" value={val(() => figures!.summary.decisions.BLOCK ?? 0)} sub={`Last ${days} days`} to={`/app/policies?${q}&tab=dashboard`} />
          <StatCard icon="clock" tone="blue" label="Median approval time" value={val(() => hoursText(figures!.summary.approvals.medianHoursToDecide))} sub="From request to decision" />
        </div>

        <div className="home-grid wide">
          <div>
            <section className="card panel" id="policy-view">
              <div className="panel-head"><h2>Policy view</h2><Link className="small" to={`/app/policies?${q}&tab=dashboard`}>Full policy dashboard</Link></div>
              {dataError ? <p className="muted small">The policy figures could not be loaded.</p> : !profiles ? <Loading lines={4} />
                : rows.length === 0 ? (
                  <EmptyTable columns={['Policy', 'Engagements', 'Exceptions', 'Spend exposure', 'Approvals']}>
                    <strong>No policies yet.</strong> <Link to={`/app/policies?${q}`}>Define your policy</Link> to govern engagements.
                  </EmptyTable>
                ) : (
                  <div className="compare-scroll">
                    <table className="data">
                      <thead><tr>{header('name', 'Policy')}<th scope="col">Status</th>{header('engagements', 'Engagements')}{header('exceptions', 'Exceptions')}
                        {header('exposure', 'Spend exposure')}{header('pending', 'Approvals pending')}{header('wait', 'Bottleneck')}</tr></thead>
                      <tbody>{rows.map((p) => (
                        <tr key={p.profileId}>
                          <td><Link to={`/app/policies?${q}`}><strong>{p.name}</strong></Link>
                            <div className="muted small">{titleCase(p.riskLevel)} risk{p.activeVersion ? ` · v${p.activeVersion}` : ''}</div></td>
                          <td><span className={`badge ${p.status === 'ACTIVE' ? 'green' : ''}`}>{titleCase(p.status)}</span></td>
                          <td>{p.engagements.toLocaleString()}</td>
                          <td>{p.exceptions.requested ? <Link to={`/app/policies?${q}&tab=exceptions`}>{p.exceptions.requested}</Link> : 0}
                            <span className="muted small"> ({p.exceptions.granted} granted)</span></td>
                          <td>{moneyText(p.spendExposure)}</td>
                          <td>{p.approvals.pending ? <Link to={`/app/policies?${q}&tab=approvals`}>{p.approvals.pending}</Link> : 0}
                            <span className="muted small"> of {p.approvals.requested}</span></td>
                          <td>{p.bottleneck ? <>Step {p.bottleneck.step} · {titleCase(p.bottleneck.role)}<div className="muted small">median {hoursText(p.bottleneck.medianHoursWait)}</div></> : '—'}</td>
                        </tr>))}</tbody>
                    </table>
                  </div>
                )}
              <p className="muted small" style={{ marginTop: 8 }}>Spend exposure is the value of engagements accepted under each policy. Select a policy or a count to drill down.</p>
            </section>

            <section className="card panel" id="bottlenecks">
              <div className="panel-head"><h2>Approval bottlenecks</h2><Link className="small" to={`/app/policies?${q}&tab=approvals`}>All approvals</Link></div>
              {dataError ? <p className="muted small">The approval figures could not be loaded.</p> : !profiles ? <Loading lines={2} />
                : bottlenecks.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No approval is waiting on anyone. Nothing is held up.</p> : (
                  <ul className="pro-list">{bottlenecks.map((p) => (
                    <li key={p.profileId}><Icon name="clock" /><span><Link to={`/app/policies?${q}&tab=approvals`}><strong>{p.name}</strong></Link>
                      <br /><span className="muted small">Step {p.bottleneck!.step} · {titleCase(p.bottleneck!.role)} · median wait {hoursText(p.bottleneck!.medianHoursWait)}</span></span>
                      <span className="badge warn">{p.bottleneck!.pending} waiting</span></li>))}</ul>
                )}
            </section>
          </div>

          <aside>
            <section className="card panel attention" id="actions">
              <div className="panel-head"><h2>Pending Admin Actions</h2></div>
              {dataError ? <p className="muted small" style={{ margin: 0 }}>Unavailable until the policy figures load.</p> : !figures ? <Loading lines={2} /> : <ActionList actions={actions} empty="You're all caught up." />}
            </section>

            <section className="card panel" id="controls">
              <div className="panel-head"><h2><Icon name="gear" /> Enterprise controls</h2></div>
              <ul className="quick-actions">
                <li><Link to={`/app/policies?${q}`}><Icon name="contract" /><span>Policies, approvals and exceptions</span><span aria-hidden>›</span></Link></li>
                <li><Link to="/app/enterprise/team"><Icon name="team" /><span>Roles and team</span><span aria-hidden>›</span></Link></li>
                <li><Link to="/app/enterprise/structure"><Icon name="building" /><span>Structure and budgets</span><span aria-hidden>›</span></Link></li>
                <li><Link to="/app/organisation?tab=entities"><Icon name="contract" /><span>Legal entities</span><span aria-hidden>›</span></Link></li>
                {isAdmin && <li><Link to="/app/organisation?tab=security"><Icon name="lock" /><span>Single sign-on and API keys</span><span aria-hidden>›</span></Link></li>}
                {isAdmin && <li><Link to="/app/webhooks"><Icon name="gear" /><span>Webhooks</span><span aria-hidden>›</span></Link></li>}
              </ul>
            </section>

            <section className="card panel" id="exports">
              <div className="panel-head"><h2>Exports</h2></div>
              <p className="muted small">The policy view as CSV, and the hash-chained audit log as PDF, CSV or JSON.</p>
              <div className="row" style={{ gap: 6 }}>
                <button type="button" className="btn btn-secondary btn-sm" disabled={!profiles?.length || exporting} onClick={() => { exportPolicyCsv() }}>
                  <Icon name="download" /> Policy view CSV</button>
                {canAudit ? <AuditExportButtons orgId={org.id} fileStem={`ORG-${org.id.slice(0, 8).toUpperCase()}`} onError={setError} />
                  : <span className="muted small">The audit log export is for Org Admins and Legal Reviewers.</span>}
              </div>
            </section>

            <section className="card panel" id="engagement-links">
              <div className="panel-head"><h2>Engagements &amp; payments</h2></div>
              <ul className="quick-actions">
                <li><Link to="/app/engagements"><Icon name="briefcase" /><span>Engagements</span><span aria-hidden>›</span></Link></li>
                <li><Link to="/app/requests"><Icon name="request" /><span>Requests and proposals</span><span aria-hidden>›</span></Link></li>
                <li><Link to="/app/payments"><Icon name="wallet" /><span>Payments and protection</span><span aria-hidden>›</span></Link></li>
                <li><Link to="/app/find"><Icon name="search" /><span>Find professionals</span><span aria-hidden>›</span></Link></li>
              </ul>
            </section>
          </aside>
        </div>
      </>}
    </>
  )
}
