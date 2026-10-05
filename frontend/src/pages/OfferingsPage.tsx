import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  CURRENCIES, ENGAGEMENT_TYPES, LABEL, PRICING_MODELS, proApi, taxonomyApi, toMajor, toMinor,
  type EngagementType, type Offering, type OfferingInput, type PricingModel, type Profile, type TaxonomySpecialization,
} from '../api/professional'
import { ErrorAlert, Field } from '../components/ui'
import { priceText, useMyProfile } from './ProfessionalPages'

const STATUS_CLS: Record<string, string> = { ACTIVE: 'green', PAUSED: 'warn', DRAFT: '' }

function OfferingEditor({ profile, offering, onDone, onCancel }: {
  profile: Profile
  offering: Offering | null
  onDone: () => void
  onCancel: () => void
}) {
  const [f, setF] = useState({
    title: offering?.title ?? '',
    specialization: offering?.specialization ?? profile.specializations[0]?.slug ?? '',
    summary: offering?.summary ?? '',
    deliverables: offering?.deliverables.join('\n') ?? '',
    pricingModel: (offering?.pricingModel ?? 'FIXED') as PricingModel,
    price: toMajor(offering?.startingPrice ?? null),
    currency: offering?.startingPrice?.currency ?? profile.indicativeRate?.currency ?? 'USD',
    typicalDuration: offering?.typicalDuration ?? '',
  })
  const [types, setTypes] = useState<EngagementType[]>(offering?.engagementTypes ?? ['PROJECT'])
  const [templates, setTemplates] = useState<Record<string, TaxonomySpecialization>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  useEffect(() => {
    taxonomyApi.all().then((cats) => setTemplates(Object.fromEntries(
      cats.flatMap((c) => c.groups).flatMap((g) => g.specializations).map((s) => [s.slug, s])))).catch(() => {})
  }, [])
  const suggested = templates[f.specialization]?.deliverableTemplates ?? []

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const custom = f.pricingModel === 'CUSTOM'
    const body: OfferingInput = {
      title: f.title, specialization: f.specialization, summary: f.summary, typicalDuration: f.typicalDuration,
      deliverables: f.deliverables.split('\n').map((d) => d.trim()).filter(Boolean), engagementTypes: types,
      pricingModel: f.pricingModel,
      ...(!custom && f.price.trim() ? { startingPrice: { amountMinor: toMinor(f.price), currency: f.currency } }
        : offering?.startingPrice ? { clearStartingPrice: true } : {}),
    }
    try {
      if (offering) await proApi.updateOffering(offering.id, offering.version, body)
      else await proApi.createOffering(body)
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card panel" onSubmit={submit}>
      <h2>{offering ? 'Edit offering' : 'New offering'}</h2>
      <p className="muted small">A structured, contract-ready service. Deliverables become the starting point for proposals and milestones.</p>
      <ErrorAlert error={error} />
      <div className="row">
        <Field label="Title" id="o-title" hint="e.g. “13-week cash flow forecast”">
          <input id="o-title" className="input" value={f.title} onChange={set('title')} required minLength={3} maxLength={150} />
        </Field>
        <Field label="Specialization" id="o-spec">
          <select id="o-spec" className="input" value={f.specialization} onChange={set('specialization')}>
            {profile.specializations.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
          </select>
        </Field>
      </div>
      <div style={{ height: 16 }} />
      <Field label="Summary (optional)" id="o-sum">
        <textarea id="o-sum" className="input" rows={3} maxLength={1500} value={f.summary} onChange={set('summary')} />
      </Field>
      <Field label="Deliverables" id="o-del" hint="One per line. At least one is needed before the offering can go live.">
        <textarea id="o-del" className="input" rows={4} value={f.deliverables} onChange={set('deliverables')} />
      </Field>
      {suggested.length > 0 && !f.deliverables.trim() && (
        <p className="small" style={{ marginTop: -8 }}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setF({ ...f, deliverables: suggested.join('\n') })}>
            Use typical deliverables
          </button>{' '}<span className="muted">{suggested.join(' · ')}</span>
        </p>
      )}
      <h3>Engagement types</h3>
      <div className="role-grid" style={{ marginBottom: 16 }}>
        {ENGAGEMENT_TYPES.map((t) => (
          <label key={t} className="role-option">
            <input type="checkbox" checked={types.includes(t)}
              onChange={(e) => setTypes(e.target.checked ? [...types, t] : types.filter((x) => x !== t))} />
            <span>{LABEL[t]}</span>
          </label>
        ))}
      </div>
      <div className="row">
        <Field label="Pricing" id="o-pricing">
          <select id="o-pricing" className="input" value={f.pricingModel} onChange={set('pricingModel')}>
            {PRICING_MODELS.map((p) => <option key={p} value={p}>{LABEL[p]}</option>)}
          </select>
        </Field>
        {f.pricingModel !== 'CUSTOM' && <>
          <Field label="Starting price" id="o-price">
            <input id="o-price" className="input" type="number" min="0" step="0.01" value={f.price} onChange={set('price')} />
          </Field>
          <Field label="Currency" id="o-cur">
            <select id="o-cur" className="input" value={f.currency} onChange={set('currency')}>
              {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </Field>
        </>}
        <Field label="Typical duration (optional)" id="o-dur">
          <input id="o-dur" className="input" maxLength={50} value={f.typicalDuration} onChange={set('typicalDuration')} placeholder="e.g. 4–6 weeks" />
        </Field>
      </div>
      <div style={{ height: 16 }} />
      <div className="row">
        <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || types.length === 0}>{busy ? 'Saving…' : 'Save offering'}</button>
      </div>
    </form>
  )
}

export function OfferingsPage() {
  const { profile, loading } = useMyProfile()
  const [offerings, setOfferings] = useState<Offering[]>([])
  const [editing, setEditing] = useState<Offering | 'new' | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => proApi.offerings().then(setOfferings).catch(setError), [])
  useEffect(() => { if (profile) load() }, [profile, load])

  if (loading) return <p className="muted">Loading…</p>
  if (!profile) return <p className="muted">Create your <Link to="/app/professional">professional profile</Link> first.</p>

  async function setStatus(o: Offering, action: 'activate' | 'pause') {
    setError(null)
    try {
      await (action === 'activate' ? proApi.activateOffering(o.id) : proApi.pauseOffering(o.id))
      await load()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Service offerings</h1>
          <p className="muted" style={{ margin: 0 }}>Active offerings appear on your public profile. Paused ones are kept, not deleted.</p>
        </div>
        {profile.specializations.length > 0 && !editing && (
          <button className="btn btn-primary" onClick={() => setEditing('new')}>New offering</button>
        )}
      </div>
      <ErrorAlert error={error} />
      {profile.specializations.length === 0 && (
        <div className="alert alert-warn">
          Choose your specializations first: every offering belongs to one of them.{' '}
          <Link to="/app/professional/profile?step=specializations">Choose specializations</Link>
        </div>
      )}
      {editing && (
        <OfferingEditor profile={profile} offering={editing === 'new' ? null : editing}
          onCancel={() => setEditing(null)} onDone={async () => { setEditing(null); await load() }} />
      )}
      {offerings.length === 0 && !editing && profile.specializations.length > 0 && (
        <section className="card panel"><p className="muted" style={{ margin: 0 }}>No offerings yet. Add your first service to show buyers exactly what you deliver.</p></section>
      )}
      <div className="offering-grid">
        {offerings.map((o) => (
          <article key={o.id} className="card offering">
            <div className="offering-top">
              <h3>{o.title}</h3>
              <span className={`badge ${STATUS_CLS[o.status]}`}>{LABEL[o.status]}</span>
            </div>
            <div className="muted small">{o.specializationName ?? o.specialization} · {o.engagementTypes.map((t) => LABEL[t]).join(', ')}</div>
            <div className="price">{priceText(o)}{o.typicalDuration && <span className="muted small"> · {o.typicalDuration}</span>}</div>
            {o.deliverables.length > 0 && <ul className="deliverables">{o.deliverables.map((d) => <li key={d}>{d}</li>)}</ul>}
            <div className="row" style={{ marginTop: 'auto' }}>
              <button className="btn btn-secondary btn-sm" onClick={() => setEditing(o)}>Edit</button>
              {o.status === 'ACTIVE'
                ? <button className="btn btn-secondary btn-sm" onClick={() => setStatus(o, 'pause')}>Pause</button>
                : <button className="btn btn-primary btn-sm" onClick={() => setStatus(o, 'activate')}>Activate</button>}
            </div>
          </article>
        ))}
      </div>
    </>
  )
}
