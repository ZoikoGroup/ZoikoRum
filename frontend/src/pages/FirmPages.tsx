import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { FIRM_ROLE_INFO, firmApi, formatMoney, type Firm, type FirmMember, type FirmMoney, type FirmOverview, type FirmRole,
  type Invitation } from '../api/orgs'
import { verificationApi, type VerificationCase } from '../api/verification'
import { ChecksPanel } from './VerificationPages'
import { useAuth } from '../auth/AuthContext'
import { ActionList, greeting, Icon, Kpi, type Action } from '../components/dashboard'
import { ErrorAlert, Field, useStepUp, Loading } from '../components/ui'
import { COUNTRIES } from './Join'

// eslint-disable-next-line react-refresh/only-export-components
export function useMyFirm() {
  const [firm, setFirm] = useState<Firm | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const reload = useCallback(async () => {
    try {
      for (let attempt = 0; attempt < 10; attempt++) {  // see useEnterpriseOrg: firm is created by the worker
        const found = (await firmApi.mine())[0] ?? null
        setFirm(found)
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
  return { firm, setFirm, loading, error, reload, isAdmin: !!firm?.myRoles.includes('FIRM_ADMIN') }
}

const STATUS_LABEL: Record<string, string> = {
  PENDING_VERIFICATION: 'Verification pending',
  VERIFIED: 'Verified',
  SUSPENDED: 'Suspended',
}

export function FirmStatusBadge({ status }: { status: string }) {
  return <span className={`badge ${status === 'VERIFIED' ? 'green' : 'warn'}`}>{STATUS_LABEL[status] ?? status}</span>
}

function FirmRoleBadges({ roles }: { roles: string[] }) {
  return <div className="badges">{roles.map((r) => <span key={r} className="badge">{FIRM_ROLE_INFO[r as FirmRole]?.label ?? r}</span>)}</div>
}

export function FirmTeamPage() {
  const { firm, loading, isAdmin, reload: reloadFirm } = useMyFirm()
  const { user } = useAuth()
  const [members, setMembers] = useState<FirmMember[]>([])
  const [invites, setInvites] = useState<Invitation[]>([])
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<{ text: string; link?: string | null } | null>(null)
  const [email, setEmail] = useState('')
  const [asAdmin, setAsAdmin] = useState(false)
  const { run, modal } = useStepUp(setError)

  const load = useCallback(async () => {
    if (!firm) return
    try {
      setMembers(await firmApi.members(firm.id))
      if (firm.myRoles.includes('FIRM_ADMIN')) setInvites(await firmApi.invitations(firm.id))
    } catch (err) {
      setError(err)
    }
  }, [firm])
  useEffect(() => { load() }, [load])
  if (loading) return <Loading />
  if (!firm) return <p className="muted">Your firm is still being set up. Refresh in a moment.</p>
  const rep = (identityId: string) => firm.representatives.find((r) => r.identityId === identityId)
  const myRep = user ? rep(user.id) : undefined

  function invite(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setNotice(null)
    run(async () => {
      const inv = await firmApi.invite(firm!.id, email.trim(), asAdmin ? ['FIRM_ADMIN'] : ['FIRM_MEMBER'])
      setNotice({ text: `Invitation sent to ${inv.email}.`, link: inv.devInviteUrl })
      setEmail('')
      setAsAdmin(false)
      await load()
    })
  }

  function setRoles(m: FirmMember, roles: FirmRole[], message: string) {
    setError(null)
    run(async () => {
      await firmApi.updateMember(firm!.id, m.identityId, roles)
      setNotice({ text: message })
      await load()
      await reloadFirm()
    })
  }

  const toggleRep = (m: FirmMember) => {
    const isRep = m.roles.includes('AUTHORIZED_REPRESENTATIVE')
    const roles = isRep ? m.roles.filter((r) => r !== 'AUTHORIZED_REPRESENTATIVE') : [...m.roles, 'AUTHORIZED_REPRESENTATIVE' as FirmRole]
    setRoles(m, roles, isRep ? `${m.displayName} is no longer an authorized representative.` : `${m.displayName} is now an authorized representative.`)
  }
  const toggleAdmin = (m: FirmMember) => {
    const isAdmin_ = m.roles.includes('FIRM_ADMIN')
    const roles = isAdmin_ ? [...m.roles.filter((r) => r !== 'FIRM_ADMIN'), 'FIRM_MEMBER' as FirmRole] : [...m.roles.filter((r) => r !== 'FIRM_MEMBER'), 'FIRM_ADMIN' as FirmRole]
    setRoles(m, [...new Set(roles)], isAdmin_ ? `${m.displayName} is now a Firm Member.` : `${m.displayName} is now a Firm Admin.`)
  }

  function remove(m: FirmMember) {
    if (!confirm(`Remove ${m.displayName} from ${firm!.legalName}?`)) return
    run(async () => {
      await firmApi.removeMember(firm!.id, m.identityId)
      setNotice({ text: `${m.displayName} was removed.` })
      await load()
    })
  }

  return (
    <>
      <div className="page-head"><div><h1>Firm team</h1>
        <p className="muted" style={{ margin: 0 }}>{firm.legalName} · <FirmStatusBadge status={firm.status} /></p></div></div>
      <ErrorAlert error={error} />
      {notice && (
        <div className="alert alert-success" role="status">{notice.text}
          {notice.link && <span className="ref">Development mode (no email provider yet). Share this link: <a href={notice.link}>{notice.link}</a></span>}
        </div>
      )}
      {!firm.hasAuthorizedRepresentative ? (
        <div className="alert alert-warn">
          Name an <strong>authorized representative</strong>: the person who legally acts for the firm. Their identity
          is verified before the firm can offer regulated services.
        </div>
      ) : !firm.hasVerifiedRepresentative && (
        <div className="alert alert-warn">
          No authorized representative has a verified identity yet. Each representative verifies their own identity on
          this page; if they cannot, name another representative.
        </div>
      )}
      {myRep && !myRep.identityVerified && (
        <ChecksPanel subjectType="IDENTITY" subjectId={myRep.identityId} allowed={['IDENTITY']} onChanged={() => setTimeout(reloadFirm, 1500)} />
      )}

      {isAdmin && (
        <section className="card panel">
          <h2>Invite a professional</h2>
          <form onSubmit={invite}>
            <Field label="Email" id="firm-inv-email">
              <input id="firm-inv-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <label className="checkbox">
              <input type="checkbox" checked={asAdmin} onChange={(e) => setAsAdmin(e.target.checked)} />
              <span>Make them a Firm Admin (can manage the firm profile and team)</span>
            </label>
            <button className="btn btn-primary" disabled={!email}>Send invitation</button>
          </form>
        </section>
      )}

      <section className="card panel">
        <h2>Members ({members.length})</h2>
        <table className="data">
          <thead><tr><th>Name</th><th>Roles</th>{isAdmin && <th aria-label="Actions" />}</tr></thead>
          <tbody>{members.map((m) => (
            <tr key={m.identityId}>
              <td><strong>{m.displayName}</strong><div className="muted small">{m.email}</div></td>
              <td><FirmRoleBadges roles={m.roles} />
                {rep(m.identityId) && <div className="small" style={{ marginTop: 4 }}>
                  {rep(m.identityId)!.identityVerified ? <span className="badge green">Identity verified</span>
                    : <span className="badge warn">Identity not verified</span>}</div>}</td>
              {isAdmin && (
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                  <button className="btn btn-secondary btn-sm" onClick={() => toggleRep(m)}>
                    {m.roles.includes('AUTHORIZED_REPRESENTATIVE') ? 'Remove representative' : 'Make representative'}
                  </button>{' '}
                  <button className="btn btn-secondary btn-sm" onClick={() => toggleAdmin(m)}>
                    {m.roles.includes('FIRM_ADMIN') ? 'Make member' : 'Make admin'}
                  </button>{' '}
                  <button className="btn btn-danger btn-sm" onClick={() => remove(m)}>Remove</button>
                </td>
              )}
            </tr>
          ))}</tbody>
        </table>
      </section>

      {isAdmin && invites.length > 0 && (
        <section className="card panel">
          <h2>Pending invitations</h2>
          <table className="data">
            <thead><tr><th>Email</th><th>Role</th><th>Expires</th><th aria-label="Actions" /></tr></thead>
            <tbody>{invites.map((i) => (
              <tr key={i.id}><td>{i.email}</td><td><FirmRoleBadges roles={i.roles} /></td>
                <td>{new Date(i.expiresAt).toLocaleDateString()}</td>
                <td style={{ textAlign: 'right' }}>
                  <button className="btn btn-danger btn-sm" onClick={() => run(async () => { await firmApi.revokeInvitation(firm.id, i.id); await load() })}>Revoke</button>
                </td></tr>
            ))}</tbody>
          </table>
        </section>
      )}
      {modal}
    </>
  )
}

export function FirmProfilePage() {
  const { firm, setFirm, loading, isAdmin } = useMyFirm()
  const [form, setForm] = useState<Record<string, string>>({})
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  // Fill the form from each new version of the firm while rendering (no extra effect pass).
  const [formVersion, setFormVersion] = useState<number | null>(null)
  if (firm && formVersion !== firm.version) {
    setFormVersion(firm.version)
    setForm({
      legalName: firm.legalName, tradingName: firm.tradingName ?? '', registrationNumber: firm.registrationNumber ?? '',
      hqCountry: firm.hqCountry, sizeBand: firm.sizeBand ?? '', website: firm.website ?? '',
    })
  }
  if (loading || !firm) return <Loading />
  const set = (k: string) => (e: { target: { value: string } }) => { setSaved(false); setForm({ ...form, [k]: e.target.value }) }

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body: Record<string, string> = {}
      for (const [k, v] of Object.entries(form)) if (v !== '' || k === 'tradingName') body[k] = v
      setFirm(await firmApi.update(firm!.id, firm!.version, body))
      setSaved(true)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-head"><div><h1>Firm profile</h1>
        <p className="muted" style={{ margin: 0 }}>Registration details used for firm verification. <FirmStatusBadge status={firm.status} /></p></div></div>
      <ErrorAlert error={error} />
      {saved && <div className="alert alert-success" role="status">Firm profile saved.</div>}
      <form className="card panel" style={{ maxWidth: 680 }} onSubmit={save}>
        <fieldset disabled={!isAdmin} style={{ border: 0, padding: 0, margin: 0 }}>
          <Field label="Registered legal name" id="f-legal" hint="Changing this restarts firm verification.">
            <input id="f-legal" className="input" value={form.legalName ?? ''} onChange={set('legalName')} />
          </Field>
          <Field label="Trading name (optional)" id="f-trading">
            <input id="f-trading" className="input" value={form.tradingName ?? ''} onChange={set('tradingName')} />
          </Field>
          <Field label="Company registration number" id="f-reg" hint="As shown on your incorporation documents.">
            <input id="f-reg" className="input" value={form.registrationNumber ?? ''} onChange={set('registrationNumber')} />
          </Field>
          <div className="row">
            <Field label="Headquarters country" id="f-country">
              <select id="f-country" className="input" value={form.hqCountry ?? ''} onChange={set('hqCountry')}>
                {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
              </select>
            </Field>
            <Field label="Firm size" id="f-size">
              <select id="f-size" className="input" value={form.sizeBand ?? ''} onChange={set('sizeBand')}>
                <option value="">Select…</option>
                {['1-5', '6-20', '21-100', '100+'].map((b) => <option key={b} value={b}>{b} people</option>)}
              </select>
            </Field>
          </div>
          <div style={{ height: 16 }} />
          <Field label="Website (optional)" id="f-web" hint="Must start with https://">
            <input id="f-web" className="input" value={form.website ?? ''} onChange={set('website')} placeholder="https://" />
          </Field>
          {isAdmin && <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save profile'}</button>}
        </fieldset>
        {!isAdmin && <p className="muted small">Only Firm Admins can edit the firm profile.</p>}
      </form>
    </>
  )
}

const moneyList = (money: FirmMoney[], key: 'heldMinor' | 'releasedMinor') =>
  money.filter((m) => m[key]).map((m) => formatMoney({ amountMinor: m[key], currency: m.currency })).join(' · ') || '—'

/** The firm's work across its professionals: counts and money totals only, never buyers, terms or documents. */
function FirmWork({ firmId }: { firmId: string }) {
  const [work, setWork] = useState<FirmOverview | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { firmApi.overview(firmId).then(setWork).catch(setError) }, [firmId])
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Your firm's work</h2></div>
      <ErrorAlert error={error} />
      {!work ? (!error && <Loading />) : (<>
        <div className="kpi-row">
          <Kpi icon="request" tone="blue" label="Open requests" value={work.openRequests} note="Waiting for or holding a proposal" />
          <Kpi icon="contract" tone="violet" label="Contracts" value={work.activeContracts}
            note={`${work.awaitingSignature} awaiting signature · ${work.completedContracts} completed`} />
          <Kpi icon="wallet" tone="teal" label="Held in escrow" value={moneyList(work.money, 'heldMinor')}
            note={`Released to date: ${moneyList(work.money, 'releasedMinor')}`} />
        </div>
        {work.professionals.length === 0 ? (
          <p className="muted small" style={{ margin: 0 }}>No professionals practise under the firm yet. Invite them from the team page;
            they choose the firm in their own profile.</p>
        ) : (
          <table className="data">
            <thead><tr><th>Professional</th><th>Open requests</th><th>Contracts</th><th>Held in escrow</th><th>Released</th></tr></thead>
            <tbody>{work.professionals.map((p) => (
              <tr key={p.professionalId}>
                <td><strong>{p.displayName}</strong>{!p.published && <span className="badge" style={{ marginLeft: 6 }}>Not published</span>}
                  {p.headline && <div className="muted small">{p.headline}</div>}</td>
                <td>{p.openRequests}</td>
                <td>{p.activeContracts} active<div className="muted small">{p.awaitingSignature} to sign · {p.completedContracts} completed</div></td>
                <td>{moneyList(p.money, 'heldMinor')}</td>
                <td>{moneyList(p.money, 'releasedMinor')}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
        <p className="muted small" style={{ margin: '12px 0 0' }}>
          Totals only. Clients, contract terms and documents stay between each professional and their client.
          Amounts are shown per currency and never converted.
        </p>
      </>)}
    </section>
  )
}

/** Firm home: verification status, team and representative. */
export function FirmDashboard() {
  const { firm, loading, isAdmin } = useMyFirm()
  const { user } = useAuth()
  const [cases, setCases] = useState<VerificationCase[]>([])
  const [invites, setInvites] = useState(0)
  useEffect(() => {
    if (!firm || !isAdmin) return
    verificationApi.forSubject('FIRM', firm.id).then(setCases).catch(() => {})
    firmApi.invitations(firm.id).then((i) => setInvites(i.length)).catch(() => {})
  }, [firm, isAdmin])
  if (loading || !user) return <Loading />
  if (!firm) return <p className="muted">Your firm is still being set up. Refresh in a moment.</p>

  const registration = cases.find((c) => c.verificationType === 'FIRM_REGISTRATION')
  const actions: Action[] = []
  if (isAdmin) {
    if (registration?.status === 'NEEDS_INFO') actions.push({ title: 'More information needed for firm verification',
      detail: registration.publicReason ?? 'See the reviewer\'s note', priority: 'High', to: '/app/firm/verification', icon: 'shield' })
    if (!registration && firm.status !== 'VERIFIED') actions.push({ title: 'Verify the firm registration',
      detail: 'Confirms the firm is a registered legal entity', priority: 'High', to: '/app/firm/verification', icon: 'shield' })
    if (!firm.registrationNumber || !firm.sizeBand) actions.push({ title: 'Complete the firm profile',
      detail: 'Registration number and firm size', priority: 'Medium', to: '/app/firm/profile', icon: 'building' })
    if (!firm.hasAuthorizedRepresentative) actions.push({ title: 'Name an authorized representative',
      detail: 'The person who legally acts for the firm', priority: 'Medium', to: '/app/firm/team', icon: 'user' })
    else if (!firm.hasVerifiedRepresentative) actions.push({ title: 'Representative identity not verified',
      detail: 'A representative verifies their identity on the team page, or name another representative', priority: 'High',
      to: '/app/firm/team', icon: 'user' })
    if (firm.memberCount <= 1) actions.push({ title: 'Invite your professionals', detail: 'They offer services under the firm',
      priority: 'Low', to: '/app/firm/team', icon: 'team' })
    if (invites > 0) actions.push({ title: `${invites} invitation${invites > 1 ? 's' : ''} not yet accepted`,
      detail: 'Remind your colleagues or resend', priority: 'Low', to: '/app/firm/team', icon: 'mail' })
  }

  return (
    <>
      <div className="home-head">
        <div>
          <h1>{greeting(user.displayName)}</h1>
          <p className="muted" style={{ margin: 0 }}>{firm.tradingName || firm.legalName} · <FirmStatusBadge status={firm.status} /></p>
        </div>
        <div className="row">
          <Link className="btn btn-secondary" to={`/firms/${firm.id}`}><Icon name="globe" /> View public page</Link>
          {isAdmin && <Link className="btn btn-primary" to="/app/firm/team"><Icon name="team" /> Manage team</Link>}
        </div>
      </div>
      <div className="kpi-row">
        <Kpi icon="shield" tone={firm.status === 'VERIFIED' ? 'green' : 'amber'} label="Firm verification"
          value={STATUS_LABEL[firm.status] ?? firm.status} note={registration ? `Check: ${registration.status.replace('_', ' ').toLowerCase()}` : 'Not started'} />
        <Kpi icon="team" tone="blue" label="Firm members" value={firm.memberCount} note={invites ? `${invites} invited` : 'Including you'} />
        <Kpi icon="user" tone={firm.hasVerifiedRepresentative ? 'green' : 'amber'} label="Authorized representative"
          value={firm.hasVerifiedRepresentative ? 'Verified' : firm.hasAuthorizedRepresentative ? 'Not verified' : 'Missing'}
          note="Needed for regulated work" />
      </div>
      <div className="home-grid">
        <div>
          {isAdmin && <FirmWork firmId={firm.id} />}
          <section className="card panel">
            <div className="panel-head"><h2>Your roles</h2></div>
            <FirmRoleBadges roles={firm.myRoles} />
          </section>
        </div>
        <aside>
          <section className="card panel">
            <div className="panel-head"><h2>Pending actions</h2></div>
            <ActionList actions={actions} empty={isAdmin ? 'Your firm is set up.' : 'Firm Admins manage firm setup.'} />
          </section>
        </aside>
      </div>
    </>
  )
}
