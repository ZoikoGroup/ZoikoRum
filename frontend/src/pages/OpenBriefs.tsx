import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { briefApi, briefBudget, type OpenBrief } from '../api/briefs'
import { formatMoney, orgApi, type Organization } from '../api/orgs'
import { taxonomyApi, type TaxonomySpecialization } from '../api/professional'
import { DURATION_LABEL, DURATIONS, MAX_REQUEST_PROFESSIONALS, type Duration } from '../api/proposals'
import { Avatar, Icon } from '../components/dashboard'
import { PortalHeader } from '../components/portal'
import { TrustLight } from '../components/TrustLight'
import { ErrorAlert, Loading } from '../components/ui'
import { countryName } from './ProfessionalPages'

/* Open briefs: the buyer describes a need once, professionals in that specialization who serve the buyer's country say
   they are interested, and the buyer sends the normal request to the ones they pick. */

const fmtDate = (d: string) => new Date(d).toLocaleDateString()

/** Buyer: post a brief and see who is interested. */
export function BuyerBriefsPage() {
  const [org, setOrg] = useState<Organization | null>(null)
  const [briefs, setBriefs] = useState<OpenBrief[] | null>(null)
  const [specs, setSpecs] = useState<TaxonomySpecialization[]>([])
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ service: '', specialization: '', objective: '', details: '', duration: '' as Duration | '', budget: '', currency: 'USD' })

  const load = useCallback(async (o: Organization) => setBriefs(await briefApi.mine(o.id)), [])
  useEffect(() => {
    let live = true
    orgApi.mine().then((orgs) => {
      const o = orgs.find((x) => x.myRoles.includes('REQUESTER') || x.myRoles.includes('ORG_ADMIN')) ?? null
      if (!live) return
      setOrg(o)
      if (o) load(o).catch(setError)
      else setBriefs([])
    }).catch(setError)
    taxonomyApi.all().then((cats) => { if (live) setSpecs(cats.flatMap((c) => c.groups.flatMap((g) => g.specializations))) }).catch(() => {})
    return () => { live = false }
  }, [load])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!org) return
    setBusy(true); setError(null); setNotice(null)
    try {
      const max = Math.round(Number(form.budget || 0) * 100)
      await briefApi.post({ organizationId: org.id, service: form.service.trim(), specialization: form.specialization,
        objective: form.objective.trim(), details: form.details.trim(), estimatedDuration: form.duration || null,
        budget: max > 0 ? { maxMinor: max, currency: form.currency } : null })
      setForm({ ...form, service: '', objective: '', details: '', budget: '' })
      setNotice('Brief posted. Professionals in that specialization who serve your country can now say they are interested.')
      await load(org)
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  if (briefs === null) return error ? <ErrorAlert error={error} /> : <Loading />
  return (
    <>
      <PortalHeader eyebrow={<Link to="/app/requests">Requests</Link>} title="Open briefs"
        subtitle="Describe what you need once. Matching professionals say they are interested, and you choose whom to ask for a proposal." />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />
      {!org ? <section className="card panel"><p style={{ margin: 0 }}>Posting a brief needs the Requester role in your organisation.</p></section> : <>
        <section className="card panel">
          <h2 style={{ marginTop: 0 }}>Post a brief</h2>
          <p className="muted small">Professionals see the brief, your country and industry, but not your organisation's name.
            It stays open for 14 days. Nothing is agreed until you send a request and accept a proposal.</p>
          <form onSubmit={submit} className="stack">
            <div className="row">
              <label className="filter-box grow"><span>What do you need?</span>
                <input required minLength={2} maxLength={200} value={form.service} onChange={(e) => setForm({ ...form, service: e.target.value })} placeholder="e.g. Month-end close support" /></label>
              <label className="filter-box grow"><span>Specialization</span>
                <select required value={form.specialization} onChange={(e) => setForm({ ...form, specialization: e.target.value })}>
                  <option value="">Choose…</option>{specs.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}</select></label>
            </div>
            <label className="filter-box grow"><span>Objective ({form.objective.length}/300)</span>
              <input required minLength={5} maxLength={300} value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} placeholder="What a good result looks like" /></label>
            <label className="filter-box grow"><span>Details (optional)</span>
              <textarea rows={3} maxLength={1200} value={form.details} onChange={(e) => setForm({ ...form, details: e.target.value })} /></label>
            <div className="row">
              <label className="filter-box"><span>Expected duration</span>
                <select value={form.duration} onChange={(e) => setForm({ ...form, duration: e.target.value as Duration | '' })}>
                  <option value="">Not sure yet</option>{DURATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
              <label className="filter-box"><span>Budget up to (optional)</span>
                <input inputMode="decimal" value={form.budget} onChange={(e) => setForm({ ...form, budget: e.target.value.replace(/[^0-9.]/g, '') })} /></label>
              <label className="filter-box"><span>Currency</span>
                <input maxLength={3} value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} /></label>
            </div>
            <div className="row"><button className="btn btn-primary" disabled={busy}>Post brief</button></div>
          </form>
        </section>
        {briefs.length === 0 ? <p className="muted">No briefs yet.</p> : briefs.map((b) => <BuyerBrief key={b.id} b={b}
          onClose={() => briefApi.close(b.id).then(() => load(org)).then(() => setNotice('Brief closed.')).catch(setError)} />)}
      </>}
    </>
  )
}

function BuyerBrief({ b, onClose }: { b: OpenBrief; onClose: () => void }) {
  const [picked, setPicked] = useState<string[]>([])
  const interests = b.interests ?? []
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= MAX_REQUEST_PROFESSIONALS ? p : [...p, id]))
  return (
    <section className="card panel">
      <div className="panel-head">
        <h2 style={{ margin: 0 }}>{b.service}</h2>
        <span className={`badge ${b.status === 'OPEN' ? 'green' : ''}`}>{b.status === 'OPEN' ? `Open until ${fmtDate(b.closesAt)}` : 'Closed'}</span>
      </div>
      <p className="muted small" style={{ marginTop: 4 }}>{b.specializationName} · {b.objective}{b.budget ? ` · up to ${formatMoney(briefBudget(b)!)}` : ''}</p>
      {interests.length === 0 ? <p className="muted small">No one has said they are interested yet.</p> : <>
        <p className="small"><strong>{interests.length} interested.</strong> Pick up to {MAX_REQUEST_PROFESSIONALS} to send the request to.</p>
        <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 12px' }}>{interests.map((i) => (
          <li key={i.professional.id} className="name-row" style={{ marginBottom: 10 }}>
            <input type="checkbox" aria-label={`Choose ${i.professional.displayName}`} checked={picked.includes(i.professional.id)}
              disabled={!picked.includes(i.professional.id) && picked.length >= MAX_REQUEST_PROFESSIONALS} onChange={() => toggle(i.professional.id)} />
            <Avatar name={i.professional.displayName} photoUrl={i.professional.photoUrl} size={36} />
            <span><Link to={`/professionals/${i.professional.id}`}><strong>{i.professional.displayName}</strong></Link> <TrustLight tier={i.professional.tier} /><br />
              <span className="muted small">{i.professional.headline}</span>
              {i.note && <><br /><span className="small">“{i.note}”</span></>}</span>
          </li>))}</ul>
      </>}
      <div className="row card-actions" style={{ justifyContent: 'flex-start' }}>
        {picked.length > 0 && <Link className="btn btn-primary" to={`/app/requests/new?${picked.map((id) => `pro=${id}`).join('&')}&brief=${b.id}`}>
          <Icon name="request" /> Request proposal{picked.length > 1 ? 's' : ''} ({picked.length})</Link>}
        {b.status === 'OPEN' && <button className="btn btn-ghost btn-sm" onClick={onClose}>Close brief</button>}
      </div>
    </section>
  )
}

/** Professional: open briefs in your specializations and served countries. */
export function ProfessionalBriefsPage() {
  const [briefs, setBriefs] = useState<OpenBrief[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  useEffect(() => { briefApi.matching().then(setBriefs).catch((e) => { setError(e); setBriefs([]) }) }, [])

  async function interested(b: OpenBrief) {
    setBusy(b.id); setError(null)
    try {
      const updated = await briefApi.interest(b.id, (notes[b.id] ?? '').trim())
      setBriefs((list) => (list ?? []).map((x) => (x.id === b.id ? updated : x)))
    } catch (err) { setError(err) } finally { setBusy(null) }
  }

  if (briefs === null) return <Loading />
  return (
    <>
      <PortalHeader eyebrow={<Link to="/app/professional/requests">Requests</Link>} title="Open briefs"
        subtitle="Needs posted by buyers in your specializations and countries. Say you are interested; the buyer decides whom to ask for a proposal." />
      <ErrorAlert error={error} />
      {briefs.length === 0 && !error && <p className="muted">No open briefs match your specializations and countries right now.</p>}
      {briefs.map((b) => (
        <section key={b.id} className="card panel">
          <div className="panel-head">
            <h2 style={{ margin: 0 }}>{b.service}</h2>
            <span className="muted small">Buyer in {countryName(b.country)}{b.industry ? ` · ${b.industry}` : ''}</span>
          </div>
          <p style={{ margin: '6px 0' }}>{b.objective}</p>
          {b.details && <p className="muted small" style={{ whiteSpace: 'pre-wrap' }}>{b.details}</p>}
          <p className="muted small">{b.specializationName}
            {b.estimatedDuration && ` · ${DURATION_LABEL[b.estimatedDuration as Duration] ?? b.estimatedDuration}`}
            {b.budget && ` · up to ${formatMoney(briefBudget(b)!)}`} · open until {fmtDate(b.closesAt)}</p>
          {b.myInterest
            ? <p className="ok-text small" style={{ margin: 0 }}>✓ You said you are interested. If the buyer picks you, the request arrives in Requests.</p>
            : <div className="row">
              <input className="input" style={{ flex: 1 }} maxLength={500} placeholder="A short note for the buyer (optional): relevant experience, availability"
                value={notes[b.id] ?? ''} onChange={(e) => setNotes({ ...notes, [b.id]: e.target.value })} />
              <button className="btn btn-primary btn-sm" disabled={busy === b.id} onClick={() => interested(b)}>I'm interested</button>
            </div>}
        </section>
      ))}
    </>
  )
}
