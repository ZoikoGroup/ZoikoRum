import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { FIRM_ROLE_INFO, firmApi, formatMoney, type Firm, type FirmMember, type FirmMoney, type FirmOffering, type FirmOverview, type FirmRole,
  type Invitation } from '../api/orgs'
import { messagingApi } from '../api/messaging'
import { notificationApi } from '../api/notifications'
import { taxonomyApi, type TaxonomySpecialization } from '../api/professional'
import { verificationApi, type VerificationCase } from '../api/verification'
import { ChecksPanel } from './VerificationPages'
import { useAuth } from '../auth/AuthContext'
import { ActionList, greeting, Icon, Kpi, type Action } from '../components/dashboard'
import { ErrorAlert, Field, useStepUp, Loading } from '../components/ui'
import { COUNTRIES } from './Join'
import { TrustLight } from '../components/TrustLight'
import { lightName } from '../lib/trustLight'
import { keepRegistration, keepText, registrationError, textError, websiteError } from '../lib/validation'

// eslint-disable-next-line react-refresh/only-export-components
export function useMyFirm() {
  const [firm, setFirm] = useState<Firm | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const alive = useRef(true)
  const reload = useCallback(async () => {
    try {
      setError(null)
      for (let attempt = 0; attempt < 10 && alive.current; attempt++) {  // see useEnterpriseOrg: firm is created by the worker
        const found = (await firmApi.mine())[0] ?? null
        if (alive.current) setFirm(found)
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
  return { firm, setFirm, loading, error, reload, isAdmin: !!firm?.myRoles.includes('FIRM_ADMIN') }
}

/** Shown when the account has no firm to display: the load failed (show why) or the firm is still being created. */
export function NoFirm({ error }: { error: unknown }) {
  return <><ErrorAlert error={error} />{!error && <p className="muted">Your firm is still being set up. Refresh in a moment.</p>}</>
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
  const { firm, loading, error: firmError, isAdmin, reload: reloadFirm } = useMyFirm()
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
  if (!firm) return <NoFirm error={firmError} />
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
  const { firm, setFirm, loading, error: firmError, isAdmin } = useMyFirm()
  const [form, setForm] = useState<Record<string, string>>({})
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [shown, setShown] = useState<Set<string>>(new Set())  // fields whose error may show (after blur or submit)

  // Fill the form from each new version of the firm while rendering (no extra effect pass).
  const [formVersion, setFormVersion] = useState<number | null>(null)
  if (firm && formVersion !== firm.version) {
    setFormVersion(firm.version)
    setForm({
      legalName: firm.legalName, tradingName: firm.tradingName ?? '', registrationNumber: firm.registrationNumber ?? '',
      hqCountry: firm.hqCountry, sizeBand: firm.sizeBand ?? '', website: firm.website ?? '',
    })
  }
  if (loading) return <Loading />
  if (!firm) return <NoFirm error={firmError} />
  const clean: Record<string, (v: string) => string> = { legalName: (v) => keepText('org', v), tradingName: (v) => keepText('org', v),
    registrationNumber: keepRegistration, website: (v) => v.replace(/\s/g, '') }
  const set = (k: string) => (e: { target: { value: string } }) => { setSaved(false); setForm({ ...form, [k]: (clean[k] ?? ((v: string) => v))(e.target.value) }) }
  const errs: Record<string, string> = {
    legalName: textError('org', form.legalName ?? ''), tradingName: textError('org', form.tradingName ?? '', false),
    registrationNumber: registrationError(form.registrationNumber ?? ''), website: websiteError(form.website ?? ''),
    hqCountry: COUNTRIES.some(([c]) => c === form.hqCountry) ? '' : 'Choose a country from the list.',
  }
  const errOf = (k: string) => (shown.has(k) ? errs[k] : '') || undefined
  const blur = (k: string) => () => setShown((s0) => new Set(s0).add(k))

  async function save(e: FormEvent) {
    e.preventDefault()
    setShown(new Set(Object.keys(errs)))
    if (Object.values(errs).some(Boolean)) { setSaved(false); return }  // show the field errors instead of saving
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
      <form className="card panel" style={{ maxWidth: 680 }} onSubmit={save} noValidate>
        <fieldset disabled={!isAdmin} style={{ border: 0, padding: 0, margin: 0 }}>
          <Field label="Registered legal name" id="f-legal" hint="Changing this restarts firm verification." error={errOf('legalName')}>
            <input id="f-legal" className="input" value={form.legalName ?? ''} onChange={set('legalName')} onBlur={blur('legalName')} maxLength={200} aria-invalid={!!errOf('legalName')} />
          </Field>
          <Field label="Trading name (optional)" id="f-trading" error={errOf('tradingName')}>
            <input id="f-trading" className="input" value={form.tradingName ?? ''} onChange={set('tradingName')} onBlur={blur('tradingName')} maxLength={200} aria-invalid={!!errOf('tradingName')} />
          </Field>
          <Field label="Company registration number" id="f-reg" hint="Letters, digits, hyphen and slash, e.g. SC123456." error={errOf('registrationNumber')}>
            <input id="f-reg" className="input" value={form.registrationNumber ?? ''} onChange={set('registrationNumber')} onBlur={blur('registrationNumber')} maxLength={30} aria-invalid={!!errOf('registrationNumber')} />
          </Field>
          <div className="row">
            <Field label="Headquarters country" id="f-country" error={errOf('hqCountry')}>
              <select id="f-country" className="input" value={form.hqCountry ?? ''} onChange={set('hqCountry')} onBlur={blur('hqCountry')}>
                {!COUNTRIES.some(([c]) => c === form.hqCountry) && <option value="">Select…</option>}
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
          <Field label="Website (optional)" id="f-web" hint="Must start with http:// or https://" error={errOf('website')}>
            <input id="f-web" className="input" value={form.website ?? ''} onChange={set('website')} onBlur={blur('website')} maxLength={300} placeholder="https://" aria-invalid={!!errOf('website')} />
          </Field>
          {isAdmin && <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save profile'}</button>}
        </fieldset>
        {!isAdmin && <p className="muted small">Only Firm Admins can edit the firm profile.</p>}
      </form>
      <FirmOfferingsPanel firm={firm} isAdmin={isAdmin} />
    </>
  )
}

const OFFERING_TYPES: [string, string][] = [['ADVISORY', 'Advisory'], ['PROJECT', 'Project'], ['RETAINER', 'Retainer'], ['FRACTIONAL', 'Fractional']]
const OFFERING_STATUS: Record<string, string> = { DRAFT: 'Draft', PUBLISHED: 'Published', UNPUBLISHED: 'Unpublished' }
const NO_OFFERING = { title: '', summary: '', specialization: '', engagementTypes: ['PROJECT'], pricingModel: 'FIXED', price: '', currency: 'USD', deliveredBy: [] as string[] }

/** Firm-level offerings: services the firm publishes, delivered by its members. A regulated specialization needs a
    verified firm, a verified representative and a verified, licensed delivering member before it can be published. */
export function FirmOfferingsPanel({ firm, isAdmin }: { firm: Firm; isAdmin: boolean }) {
  const [items, setItems] = useState<FirmOffering[]>([])
  const [pros, setPros] = useState<{ professionalId: string; displayName: string; tier: string }[]>([])
  const [specs, setSpecs] = useState<TaxonomySpecialization[]>([])
  const [form, setForm] = useState(NO_OFFERING)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [createError, setCreateError] = useState<unknown>(null)  // shown beside the Save as draft button, not at the top
  const [titleShown, setTitleShown] = useState(false)
  const load = useCallback(async () => { setItems(await firmApi.offerings(firm.id)) }, [firm.id])
  useEffect(() => {
    load().catch(setError)
    if (isAdmin) firmApi.overview(firm.id).then((o) => setPros(o.professionals)).catch(setError)
    taxonomyApi.all().then((cats) => setSpecs(cats.flatMap((c) => c.groups.flatMap((g) => g.specializations)))).catch(() => setSpecs([]))
  }, [load, firm.id, isAdmin])

  async function act(work: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await work()
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }
  const chosen = specs.find((s) => s.slug === form.specialization)
  const priceNum = form.price ? Number(form.price) : null
  const priceError = priceNum !== null && (!Number.isFinite(priceNum) || priceNum < 0 || priceNum > 1e9) ? 'Enter a valid amount, for example 2500 or 99.50.' : ''
  const titleError = form.title.trim().length < 3 ? 'Title must be at least 3 characters.' : ''
  async function create(e: FormEvent) {
    e.preventDefault()
    setTitleShown(true)
    if (titleError || priceError) return
    setCreateError(null)
    setBusy(true)
    try {
      await firmApi.createOffering(firm.id, { title: form.title.trim(), summary: form.summary.trim(), specialization: form.specialization,
        engagementTypes: form.engagementTypes, pricingModel: form.pricingModel,
        startingPriceMinor: priceNum !== null ? Math.round(priceNum * 100) : null, currency: priceNum !== null ? form.currency : null,
        deliveredBy: form.deliveredBy })
      setForm(NO_OFFERING)
      setTitleShown(false)
      await load()
    } catch (err) {
      setCreateError(err)  // the real message from the server, next to the button
    } finally {
      setBusy(false)
    }
  }
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v])

  return (
    <section className="card panel" style={{ maxWidth: 880 }} aria-label="Firm offerings">
      <h2>Firm offerings</h2>
      <p className="muted small">Services your firm offers, delivered by named members. Regulated work needs a verified firm, a verified
        authorized representative, and at least one verified, licensed member delivering it.</p>
      <ErrorAlert error={error} />
      {items.length === 0 ? <p className="muted">No offerings yet.</p> : (
        <table className="data small"><thead><tr><th>Offering</th><th>Delivered by</th><th>Status</th><th /></tr></thead>
          <tbody>{items.map((o) => (
            <tr key={o.id}>
              <td><strong>{o.title}</strong>{o.regulated && <span className="badge warn" style={{ marginLeft: 6 }}>regulated</span>}
                <div className="muted">{o.specializationName ?? o.specialization}
                  {o.startingPriceMinor != null && o.currency ? ` · from ${formatMoney({ amountMinor: o.startingPriceMinor, currency: o.currency })}` : ''}</div></td>
              <td>{o.deliveredBy.map((d) => <div key={d.professionalId}>{d.displayName} <TrustLight tier={d.tier} compact />
                {o.regulated && <span className={`badge ${d.licensed ? 'green' : ''}`} style={{ marginLeft: 4 }}>{d.licensed ? 'licensed' : 'not licensed'}</span>}</div>)}</td>
              <td><span className={`badge ${o.status === 'PUBLISHED' ? 'green' : 'warn'}`}>{OFFERING_STATUS[o.status] ?? o.status}</span>
                {o.unpublishedReason && <div className="muted">{o.unpublishedReason}</div>}</td>
              <td>{isAdmin && (o.status === 'PUBLISHED'
                ? <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => act(() => firmApi.unpublishOffering(firm.id, o.id))}>Unpublish</button>
                : <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => act(() => firmApi.publishOffering(firm.id, o.id))}>Publish</button>)}</td>
            </tr>))}</tbody></table>)}
      {isAdmin && (
        <details style={{ marginTop: 12 }}><summary><strong>Add an offering</strong></summary>
          <form onSubmit={create} style={{ marginTop: 8 }}>
            <Field label="Title" id="fo-title" error={titleShown ? titleError || undefined : undefined}><input id="fo-title" className="input" value={form.title} maxLength={200}
              onBlur={() => setTitleShown(true)} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
            <Field label="Summary" id="fo-summary"><textarea id="fo-summary" className="input" rows={3} maxLength={2000} value={form.summary}
              onChange={(e) => setForm({ ...form, summary: e.target.value })} /></Field>
            <Field label="Specialization" id="fo-spec" hint={chosen?.regulated ? 'Regulated: a verified, licensed member must deliver it.' : undefined}>
              <select id="fo-spec" className="input" value={form.specialization} onChange={(e) => setForm({ ...form, specialization: e.target.value })}>
                <option value="">Choose…</option>
                {specs.map((s) => <option key={s.slug} value={s.slug}>{s.name}{s.regulated ? ' (regulated)' : ''}</option>)}
              </select></Field>
            <p id="fo-types" className="small" style={{ margin: '8px 0 4px' }}>Engagement types</p>
            <div role="group" aria-labelledby="fo-types">{OFFERING_TYPES.map(([k, l]) => <label key={k} className="checkbox small" style={{ display: 'inline-flex', marginRight: 12 }}>
              <input type="checkbox" checked={form.engagementTypes.includes(k)} onChange={() => setForm({ ...form, engagementTypes: toggle(form.engagementTypes, k) })} /> <span>{l}</span></label>)}</div>
            <div className="row">
              <Field label="Pricing" id="fo-pricing"><select id="fo-pricing" className="input" value={form.pricingModel} onChange={(e) => setForm({ ...form, pricingModel: e.target.value })}>
                {['FIXED', 'HOURLY', 'RETAINER', 'CUSTOM'].map((p) => <option key={p} value={p}>{p.toLowerCase()}</option>)}</select></Field>
              <Field label="Starting price (optional)" id="fo-price" error={priceError || undefined}><input id="fo-price" className="input" inputMode="decimal" value={form.price}
                onChange={(e) => setForm({ ...form, price: e.target.value.replace(/[^\d.]/g, '') })} /></Field>
              <Field label="Currency" id="fo-currency"><select id="fo-currency" className="input" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
                {['USD', 'GBP', 'EUR', 'INR', 'CAD', 'AUD', 'SGD', 'AED'].map((c) => <option key={c}>{c}</option>)}</select></Field>
            </div>
            <p id="fo-people" className="small" style={{ margin: '8px 0 4px' }}>Delivered by</p>
            {pros.length === 0 ? <p className="muted small">No professionals practise under the firm yet.</p> : (
              <div role="group" aria-labelledby="fo-people">{pros.map((p) => <label key={p.professionalId} className="checkbox small" style={{ display: 'inline-flex', marginRight: 12 }}>
                <input type="checkbox" checked={form.deliveredBy.includes(p.professionalId)}
                  onChange={() => setForm({ ...form, deliveredBy: toggle(form.deliveredBy, p.professionalId) })} /> <span>{p.displayName} ({lightName(p.tier)} light)</span></label>)}</div>)}
            <div style={{ marginTop: 8 }}><ErrorAlert error={createError} /></div>
            <button className="btn btn-primary" style={{ marginTop: 8 }}
              disabled={busy || !form.specialization || form.engagementTypes.length === 0 || form.deliveredBy.length === 0}>Save as draft</button>
          </form>
        </details>
      )}
    </section>
  )
}

const moneyList = (money: FirmMoney[], key: 'heldMinor' | 'releasedMinor') =>
  money.filter((m) => m[key]).map((m) => formatMoney({ amountMinor: m[key], currency: m.currency })).join(' · ') || '—'

const AVAILABILITY: Record<string, string> = { NOW: 'Available now', TWO_WEEKS: 'In 2 weeks', ONE_MONTH: 'In 1 month', AT_CAPACITY: 'At capacity', NOT_SPECIFIED: 'Not set' }

/** The firm's work across its professionals: counts and money totals only, never buyers, terms or documents. */
function FirmWork({ firmId }: { firmId: string }) {
  const [work, setWork] = useState<FirmOverview | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => { setError(null); firmApi.overview(firmId).then(setWork).catch(setError) }, [firmId])
  useEffect(() => { load() }, [load])
  return (
    <section className="card panel" aria-label="Firm work">
      <div className="panel-head"><h2>Your firm's work</h2></div>
      <ErrorAlert error={error} />
      {!!error && !work && <button className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}
      {!work ? (!error && <Loading />) : (<>
        <div className="kpi-row">
          <Kpi icon="request" tone="blue" label="Open requests" value={work.openRequests} note="Waiting for or holding a proposal" />
          <Kpi icon="contract" tone="violet" label="Active engagements" value={work.activeContracts}
            note={`${work.awaitingSignature} awaiting signature · ${work.completedContracts} completed`} />
          <Kpi icon="wallet" tone="teal" label="Held in escrow" value={moneyList(work.money, 'heldMinor')}
            note={`Earned (released) to date: ${moneyList(work.money, 'releasedMinor')}`} />
          <Kpi icon="shield" tone={work.professionals.some((p) => p.tier === 'C') ? 'amber' : 'green'} label="Verified professionals"
            value={`${work.professionals.filter((p) => p.tier !== 'C').length} of ${work.professionals.length}`}
            note="Green or Amber light: can send proposals" />
        </div>
        {work.professionals.length === 0 ? (
          <p className="muted small" style={{ margin: 0 }}>No professionals practise under the firm yet. Invite them from the team panel;
            they choose the firm in their own profile.</p>
        ) : (
          <table className="data">
            <thead><tr><th>Professional</th><th>Trust light</th><th>Capacity</th><th>Open requests</th><th>Engagements</th><th>Held in escrow</th><th>Earned</th></tr></thead>
            <tbody>{work.professionals.map((p) => (
              <tr key={p.professionalId}>
                <td><strong>{p.displayName}</strong>{!p.published && <span className="badge" style={{ marginLeft: 6 }}>Not published</span>}
                  {p.headline && <div className="muted small">{p.headline}</div>}</td>
                <td><TrustLight tier={p.tier} />
                  {p.tier === 'C' && <div className="muted small">Identity not verified</div>}</td>
                <td><span className={`badge ${p.availability === 'AT_CAPACITY' ? 'warn' : p.availability === 'NOW' ? 'green' : ''}`}>
                  {AVAILABILITY[p.availability ?? 'NOT_SPECIFIED'] ?? p.availability}</span></td>
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

interface Check { label: string; done: boolean; required: boolean; to: string }

/** Verification state, authorized representative and profile completeness. */
function FirmStatusPanel({ firm, registration }: { firm: Firm; registration: VerificationCase | undefined }) {
  const checks: Check[] = [
    { label: 'Registered legal name', done: !!firm.legalName, required: true, to: '/app/firm/profile' },
    { label: 'Company registration number', done: !!firm.registrationNumber, required: true, to: '/app/firm/profile' },
    { label: 'Headquarters country', done: !!firm.hqCountry, required: true, to: '/app/firm/profile' },
    { label: 'Firm size', done: !!firm.sizeBand, required: true, to: '/app/firm/profile' },
    { label: 'Firm registration verified', done: firm.status === 'VERIFIED', required: true, to: '/app/firm/verification' },
    { label: 'Authorized representative named', done: firm.hasAuthorizedRepresentative, required: true, to: '/app/firm/team' },
    { label: 'Representative identity verified', done: firm.hasVerifiedRepresentative, required: true, to: '/app/firm/team' },
    { label: 'Primary category', done: !!firm.primaryCategory, required: false, to: '/app/firm/profile' },
    { label: 'Website', done: !!firm.website, required: false, to: '/app/firm/profile' },
  ]
  const done = checks.filter((c) => c.done).length
  return (
    <section className="card panel" aria-label="Firm status">
      <div className="panel-head"><h2>Setup and verification</h2><span className="muted small">{done} of {checks.length} complete</span></div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {checks.map((c) => (
          <li key={c.label} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0' }}>
            <span className={`badge ${c.done ? 'green' : 'warn'}`}>{c.done ? 'Done' : 'To do'}</span>
            <span>{c.label}</span>
            {c.required && <span className="muted small">Required</span>}
            {!c.done && <Link className="small" style={{ marginLeft: 'auto' }} to={c.to}>Fix</Link>}
          </li>
        ))}
      </ul>
      {registration?.status === 'NEEDS_INFO' && <p className="alert alert-warn" style={{ marginTop: 8 }}>
        Firm verification needs more information{registration.publicReason ? `: ${registration.publicReason}` : '.'}</p>}
      <p className="muted small" style={{ margin: '8px 0 0' }}>Regulated firm offerings need a verified firm and at least one verified authorized representative.</p>
    </section>
  )
}

/** Members, roles and pending invitations with a quick invite. */
function FirmTeamPanel({ firm }: { firm: Firm }) {
  const [members, setMembers] = useState<FirmMember[] | null>(null)
  const [invites, setInvites] = useState<Invitation[]>([])
  const [error, setError] = useState<unknown>(null)
  const [email, setEmail] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(async () => {
    try {
      setError(null)
      setMembers(await firmApi.members(firm.id))
      setInvites(await firmApi.invitations(firm.id))
    } catch (err) { setError(err) }
  }, [firm.id])
  useEffect(() => { load() }, [load])
  function invite(e: FormEvent) {
    e.preventDefault()
    setNotice(null)
    run(async () => {
      const inv = await firmApi.invite(firm.id, email.trim(), ['FIRM_MEMBER'])
      setNotice(`Invitation sent to ${inv.email}.`)
      setEmail('')
      await load()
    })
  }
  return (
    <section className="card panel" aria-label="Firm team">
      <div className="panel-head"><h2>Team</h2><Link className="small" to="/app/firm/team">Manage team</Link></div>
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {!members ? (!error && <Loading />) : (
        <table className="data small"><tbody>{members.map((m) => (
          <tr key={m.identityId}><td><strong>{m.displayName}</strong></td><td><FirmRoleBadges roles={m.roles} /></td></tr>
        ))}</tbody></table>
      )}
      {invites.length > 0 && <>
        <p className="small" style={{ margin: '10px 0 4px' }}><strong>Pending invitations ({invites.length})</strong></p>
        <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{invites.map((i) => (
          <li key={i.id}>{i.email} <span className="muted">expires {new Date(i.expiresAt).toLocaleDateString()}</span></li>))}</ul>
      </>}
      <form onSubmit={invite} style={{ marginTop: 10 }}>
        <Field label="Quick invite (email)" id="fd-invite"><input id="fd-invite" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <button className="btn btn-secondary btn-sm" disabled={!email}>Send invitation</button>
      </form>
      {modal}
    </section>
  )
}

/** Published and draft offering counts with a link to manage them. */
function FirmOfferingsSummary({ firm }: { firm: Firm }) {
  const [items, setItems] = useState<FirmOffering[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { firmApi.offerings(firm.id).then(setItems).catch(setError) }, [firm.id])
  const count = (s: string) => items?.filter((o) => o.status === s).length ?? 0
  return (
    <section className="card panel" aria-label="Firm offerings summary">
      <div className="panel-head"><h2>Firm offerings</h2><Link className="small" to="/app/firm/profile">Manage offerings</Link></div>
      <ErrorAlert error={error} />
      {!items ? (!error && <Loading />) : items.length === 0 ? (
        <p className="muted small" style={{ margin: 0 }}>No firm offerings yet. Add one on the firm profile page; regulated offerings need a verified authorized representative.</p>
      ) : (
        <div className="badges">
          <span className="badge green">{count('PUBLISHED')} published</span>
          <span className="badge warn">{count('DRAFT')} draft</span>
          <span className="badge">{count('UNPUBLISHED')} unpublished</span>
          {items.some((o) => o.regulated) && <span className="badge warn">{items.filter((o) => o.regulated).length} regulated</span>}
        </div>
      )}
    </section>
  )
}

/** Unread messages and notifications (links to the shared inboxes). */
function FirmInboxSummary() {
  const [unread, setUnread] = useState<{ messages: number; notifications: number } | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    Promise.all([messagingApi.summary(), notificationApi.count()])
      .then(([m, n]) => setUnread({ messages: m.unreadMessages, notifications: n.unread })).catch(() => setFailed(true))
  }, [])
  return (
    <section className="card panel" aria-label="Messages and notifications">
      <div className="panel-head"><h2>Inbox</h2></div>
      {failed ? <p className="muted small" style={{ margin: 0 }}>Could not load your unread counts.</p>
        : !unread ? <Loading /> : (
          <p style={{ margin: 0 }}>
            <Link to="/app/messages">{unread.messages} unread message{unread.messages === 1 ? '' : 's'}</Link>{' · '}
            <Link to="/app/notifications">{unread.notifications} unread notification{unread.notifications === 1 ? '' : 's'}</Link>
          </p>)}
    </section>
  )
}

/** What a non-admin firm member may see: the firm summary, the colleagues' names and roles, their own role. */
function FirmMemberView({ firm }: { firm: Firm }) {
  const [members, setMembers] = useState<FirmMember[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { firmApi.members(firm.id).then(setMembers).catch(setError) }, [firm.id])
  return (
    <div className="home-grid">
      <div>
        <section className="card panel" aria-label="Firm summary">
          <div className="panel-head"><h2>Firm profile</h2></div>
          <dl className="small" style={{ margin: 0 }}>
            <dt className="muted">Legal name</dt><dd>{firm.legalName}</dd>
            <dt className="muted">Headquarters</dt><dd>{firm.hqCountry}</dd>
            <dt className="muted">Size</dt><dd>{firm.sizeBand ? `${firm.sizeBand} people` : 'Not set'}</dd>
            {firm.website && <><dt className="muted">Website</dt><dd>{firm.website}</dd></>}
            <dt className="muted">Authorized representative</dt>
            <dd>{firm.hasVerifiedRepresentative ? 'Verified' : firm.hasAuthorizedRepresentative ? 'Named, identity not yet verified' : 'Not named'}</dd>
          </dl>
        </section>
        <section className="card panel" aria-label="Firm members">
          <div className="panel-head"><h2>Members{members ? ` (${members.length})` : ''}</h2></div>
          <ErrorAlert error={error} />
          {!members ? (!error && <Loading />) : (
            <table className="data small"><tbody>{members.map((m) => (
              <tr key={m.identityId}><td><strong>{m.displayName}</strong></td><td><FirmRoleBadges roles={m.roles} /></td></tr>
            ))}</tbody></table>)}
        </section>
      </div>
      <aside>
        <section className="card panel">
          <div className="panel-head"><h2>Your role</h2></div>
          <FirmRoleBadges roles={firm.myRoles} />
          <p className="muted small">Your requests, engagements and earnings are on your professional dashboard. Firm Admins see totals
            across the firm, never your clients, terms or documents. Only Firm Admins can change the firm.</p>
          <Link className="btn btn-secondary btn-sm" to="/app/professional">Open my dashboard</Link>
        </section>
        <FirmInboxSummary />
      </aside>
    </div>
  )
}

/** Firm home. Admins: status, work, team, offerings and pending actions. Members: a read-only firm overview. */
export function FirmDashboard() {
  const { firm, loading, error: firmError, isAdmin, reload } = useMyFirm()
  const { user } = useAuth()
  const [cases, setCases] = useState<VerificationCase[]>([])
  const [invites, setInvites] = useState(0)
  useEffect(() => {
    if (!firm || !isAdmin) return
    verificationApi.forSubject('FIRM', firm.id).then(setCases).catch(() => {})
    firmApi.invitations(firm.id).then((i) => setInvites(i.length)).catch(() => {})
  }, [firm, isAdmin])
  if (loading || !user) return <Loading />
  if (!firm) return <><NoFirm error={firmError} />{!!firmError && <button className="btn btn-secondary btn-sm" onClick={reload}>Try again</button>}</>

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
      <div className="kpi-row three">
        <Kpi icon="shield" tone={firm.status === 'VERIFIED' ? 'green' : 'amber'} label="Firm verification"
          value={STATUS_LABEL[firm.status] ?? firm.status}
          note={isAdmin ? (registration ? `Check: ${registration.status.replace('_', ' ').toLowerCase()}` : 'Not started') : 'Managed by Firm Admins'} />
        <Kpi icon="team" tone="blue" label="Firm members" value={firm.memberCount} note={invites ? `${invites} invited` : 'Including you'} />
        <Kpi icon="user" tone={firm.hasVerifiedRepresentative ? 'green' : 'amber'} label="Authorized representative"
          value={firm.hasVerifiedRepresentative ? 'Verified' : firm.hasAuthorizedRepresentative ? 'Not verified' : 'Missing'}
          note="Needed for regulated work" />
      </div>
      {!isAdmin ? <FirmMemberView firm={firm} /> : (
        <div className="home-grid">
          <div>
            <FirmWork firmId={firm.id} />
            <FirmTeamPanel firm={firm} />
            <FirmOfferingsSummary firm={firm} />
          </div>
          <aside>
            <section className="card panel">
              <div className="panel-head"><h2>Pending actions</h2></div>
              <ActionList actions={actions} empty="Your firm is set up." />
            </section>
            <FirmStatusPanel firm={firm} registration={registration} />
            <FirmInboxSummary />
            <section className="card panel">
              <div className="panel-head"><h2>Your roles</h2></div>
              <FirmRoleBadges roles={firm.myRoles} />
            </section>
          </aside>
        </div>
      )}
    </>
  )
}
