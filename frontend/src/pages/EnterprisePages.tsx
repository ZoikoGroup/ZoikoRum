import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  formatMoney, ORG_ROLE_INFO, ORG_ROLES, orgApi,
  type BusinessUnit, type CostCenter, type Invitation, type Organization, type OrgMember, type OrgRole,
} from '../api/orgs'
import { ErrorAlert, Field, useStepUp } from '../components/ui'

const CURRENCIES = ['USD', 'GBP', 'EUR', 'INR', 'CAD', 'AUD', 'SGD', 'AED']

/** The enterprise organization the signed-in user works in (first non-individual one). */
// eslint-disable-next-line react-refresh/only-export-components
export function useEnterpriseOrg() {
  const [org, setOrg] = useState<Organization | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const reload = useCallback(async () => {
    try {
      // Right after sign-up the organization is created by the background worker,
      // usually within a second: retry briefly instead of showing an empty page.
      for (let attempt = 0; attempt < 10; attempt++) {
        const found = (await orgApi.mine()).find((o) => o.orgType !== 'INDIVIDUAL') ?? null
        setOrg(found)
        if (found) break
        await new Promise((r) => setTimeout(r, 800))
      }
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { reload() }, [reload])
  return { org, loading, error, reload, isAdmin: !!org?.myRoles.includes('ORG_ADMIN') }
}

export function RoleBadges({ roles }: { roles: string[] }) {
  return (
    <div className="badges">
      {roles.map((r) => <span key={r} className="badge">{ORG_ROLE_INFO[r as OrgRole]?.label ?? r}</span>)}
    </div>
  )
}

function RolePicker({ value, onChange }: { value: OrgRole[]; onChange: (roles: OrgRole[]) => void }) {
  const toggle = (r: OrgRole) => onChange(value.includes(r) ? value.filter((x) => x !== r) : [...value, r])
  return (
    <div className="role-grid" role="group" aria-label="Roles">
      {ORG_ROLES.map((r) => (
        <label key={r} className="role-option">
          <input type="checkbox" checked={value.includes(r)} onChange={() => toggle(r)} />
          <span><strong>{ORG_ROLE_INFO[r].label}</strong><span className="muted small">{ORG_ROLE_INFO[r].desc}</span></span>
        </label>
      ))}
    </div>
  )
}

function SpendLimitInput({ amount, currency, onAmount, onCurrency }: {
  amount: string; currency: string; onAmount: (v: string) => void; onCurrency: (v: string) => void
}) {
  return (
    <div className="row" style={{ alignItems: 'stretch' }}>
      <input className="input" style={{ flex: 1 }} inputMode="decimal" placeholder="e.g. 50000" aria-label="Spend limit amount"
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

  if (loading) return <p className="muted">Loading…</p>
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
              <label>Roles</label>
              <RolePicker value={roles} onChange={setRoles} />
            </div>
            <div className="field" style={{ maxWidth: 360 }}>
              <label>Approval spend limit (optional)</label>
              <SpendLimitInput amount={amount} currency={currency} onAmount={setAmount} onCurrency={setCurrency} />
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
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="edit-title">
      <form className="card modal" style={{ maxWidth: 620 }} onSubmit={save}>
        <h2 id="edit-title">Edit {member.displayName}</h2>
        <p className="muted small">{member.email}</p>
        <div className="field"><label>Roles</label><RolePicker value={roles} onChange={setRoles} /></div>
        <div className="field">
          <label>Approval spend limit</label>
          <SpendLimitInput amount={amount} currency={currency} onAmount={setAmount} onCurrency={setCurrency} />
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
  const { org, loading, isAdmin } = useEnterpriseOrg()
  const [units, setUnits] = useState<BusinessUnit[]>([])
  const [centers, setCenters] = useState<CostCenter[]>([])
  const [error, setError] = useState<unknown>(null)
  const [unitName, setUnitName] = useState('')
  const [cc, setCc] = useState({ name: '', code: '', unit: '', amount: '', currency: 'USD' })
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
  if (loading || !org) return <p className="muted">Loading…</p>

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
              <label>Quarterly budget (optional)</label>
              <SpendLimitInput amount={cc.amount} currency={cc.currency} onAmount={(v) => setCc({ ...cc, amount: v })} onCurrency={(v) => setCc({ ...cc, currency: v })} />
            </div>
            <button className="btn btn-primary" disabled={!cc.name.trim() || !cc.code.trim()}>Add cost center</button>
          </form>
        )}
      </section>
    </>
  )
}

/** Enterprise home: the organization, your roles, and team setup progress. */
