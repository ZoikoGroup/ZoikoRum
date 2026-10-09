import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  AVAILABILITY, CURRENCIES, ENGAGEMENT_TYPES, LABEL, PRICING_MODELS, proApi, taxonomyApi, toMajor, toMinor,
  type Availability, type EngagementType, type Offering, type PricingModel, type Profile, type TaxonomySpecialization,
} from '../api/professional'
import { HoursSlider } from '../components/HoursSlider'
import { ErrorAlert, Field } from '../components/ui'
import { priceText, useMyProfile } from './ProfessionalPages'

const STATUS_CLS: Record<string, string> = { ACTIVE: 'green', PAUSED: 'warn', DRAFT: '' }

// Service creation & edit flow (Professional Dashboard wireframe s.6): five steps, each saved as you go.
const WIZARD = ['Service overview', 'Scope & deliverables', 'Pricing & engagement model', 'Availability & capacity', 'Review & publish']

function OfferingWizard({ profile: initialProfile, offering: initial, onDone, onCancel }: {
  profile: Profile
  offering: Offering | null
  onDone: () => void
  onCancel: () => void
}) {
  const [offering, setOffering] = useState<Offering | null>(initial)
  const [profile, setProfile] = useState(initialProfile)
  const [step, setStep] = useState(0)
  const [f, setF] = useState({
    title: initial?.title ?? '',
    specialization: initial?.specialization ?? initialProfile.specializations[0]?.slug ?? '',
    summary: initial?.summary ?? '',
    deliverables: initial?.deliverables.join('\n') ?? '',
    pricingModel: (initial?.pricingModel ?? 'FIXED') as PricingModel,
    price: toMajor(initial?.startingPrice ?? null),
    currency: initial?.startingPrice?.currency ?? initialProfile.indicativeRate?.currency ?? 'USD',
    typicalDuration: initial?.typicalDuration ?? '',
  })
  const [types, setTypes] = useState<EngagementType[]>(initial?.engagementTypes ?? ['PROJECT'])
  const [avail, setAvail] = useState({
    availability: initialProfile.availability as Availability,
    max: initialProfile.maxConcurrentEngagements?.toString() ?? '',
    paused: initialProfile.temporarilyUnavailable,
    hours: initialProfile.weeklyHours ?? null,
  })
  const [templates, setTemplates] = useState<Record<string, TaxonomySpecialization>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  useEffect(() => {
    taxonomyApi.all().then((cats) => setTemplates(Object.fromEntries(
      cats.flatMap((c) => c.groups).flatMap((g) => g.specializations).map((s) => [s.slug, s])))).catch(() => {})
  }, [])
  const suggested = templates[f.specialization]?.deliverableTemplates ?? []
  const deliverables = f.deliverables.split('\n').map((d) => d.trim()).filter(Boolean)
  const done = [
    !!offering,
    !!offering && offering.deliverables.length > 0,
    !!offering && (offering.pricingModel === 'CUSTOM' || offering.startingPrice !== null),
    profile.availability !== 'NOT_SPECIFIED',
    offering?.status === 'ACTIVE',
  ]

  async function save(e?: FormEvent) {
    e?.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (step === 0) {
        const body = { title: f.title, specialization: f.specialization, summary: f.summary }
        setOffering(offering ? await proApi.updateOffering(offering.id, offering.version, body)
          : await proApi.createOffering({ ...body, deliverables: [], engagementTypes: types, pricingModel: f.pricingModel }))
      } else if (step === 1 && offering) {
        setOffering(await proApi.updateOffering(offering.id, offering.version, { deliverables }))
      } else if (step === 2 && offering) {
        const custom = f.pricingModel === 'CUSTOM'
        setOffering(await proApi.updateOffering(offering.id, offering.version, {
          engagementTypes: types, pricingModel: f.pricingModel, typicalDuration: f.typicalDuration,
          ...(!custom && f.price.trim() ? { startingPrice: { amountMinor: toMinor(f.price), currency: f.currency } }
            : offering.startingPrice ? { clearStartingPrice: true } : {}),
        }))
      } else if (step === 3) {
        setProfile(await proApi.setAvailability({ availability: avail.availability,
          maxConcurrentEngagements: avail.max ? Number(avail.max) : null, temporarilyUnavailable: avail.paused, weeklyHours: avail.hours }))
      }
      setStep((s) => Math.min(s + 1, WIZARD.length - 1))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function publish() {
    if (!offering) return
    setBusy(true)
    setError(null)
    try {
      if (offering.status !== 'ACTIVE') await proApi.activateOffering(offering.id)
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card panel">
      <div className="panel-head"><h2>{initial ? 'Edit service' : 'New service'}</h2>
        <button type="button" className="btn btn-ghost btn-sm" onClick={offering ? onDone : onCancel}>{offering ? 'Save & close' : 'Cancel'}</button></div>
      <nav className="steps" aria-label="Service steps">
        {WIZARD.map((label, i) => (
          <button key={label} type="button" aria-current={i === step ? 'step' : undefined} disabled={i > 0 && !offering}
            onClick={() => setStep(i)} className={done[i] ? 'done' : ''}>
            <span className="n">{done[i] ? '✓' : i + 1}</span>{label}
          </button>
        ))}
      </nav>
      <ErrorAlert error={error} />
      <form onSubmit={save}>
        {step === 0 && <>
          <div className="row">
            <Field label="Service name" id="o-title" hint="A clear, professional title, e.g. “13-week cash flow forecast”">
              <input id="o-title" className="input" value={f.title} onChange={set('title')} required minLength={3} maxLength={150} />
            </Field>
            <Field label="Specialization" id="o-spec" hint="From the Zoikorum taxonomy">
              <select id="o-spec" className="input" value={f.specialization} onChange={set('specialization')}>
                {profile.specializations.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
              </select>
            </Field>
          </div>
          <div style={{ height: 16 }} />
          <Field label="Summary (optional)" id="o-sum" hint="What the buyer gets and who it is for.">
            <textarea id="o-sum" className="input" rows={3} maxLength={1500} value={f.summary} onChange={set('summary')} />
          </Field>
        </>}

        {step === 1 && <>
          <Field label="Deliverables" id="o-del" hint="One per line. At least one is needed before the service can go live.">
            <textarea id="o-del" className="input" rows={5} value={f.deliverables} onChange={set('deliverables')} />
          </Field>
          {suggested.length > 0 && !f.deliverables.trim() && (
            <p className="small" style={{ marginTop: -8 }}>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setF({ ...f, deliverables: suggested.join('\n') })}>
                Use typical deliverables</button>{' '}<span className="muted">{suggested.join(' · ')}</span>
            </p>
          )}
        </>}

        {step === 2 && <>
          <h3>Engagement type</h3>
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
            <Field label="Pricing model" id="o-pricing">
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
            <Field label="Typical duration" id="o-dur">
              <input id="o-dur" className="input" maxLength={50} value={f.typicalDuration} onChange={set('typicalDuration')} placeholder="e.g. 4–6 weeks" />
            </Field>
          </div>
          <p className="muted small">Prices are indicative; the final price is agreed in each proposal.</p>
        </>}

        {step === 3 && <>
          <p className="muted small">Availability and capacity apply to all your services. Reaching your limit shows buyers “At capacity”.</p>
          <div className="row">
            <Field label="Availability" id="o-avail">
              <select id="o-avail" className="input" value={avail.availability}
                onChange={(e) => setAvail({ ...avail, availability: e.target.value as Availability })}>
                {AVAILABILITY.map((a) => <option key={a} value={a}>{LABEL[a]}</option>)}
              </select>
            </Field>
            <Field label="Most engagements at once" id="o-max">
              <input id="o-max" className="input" type="number" min={1} max={50} value={avail.max}
                onChange={(e) => setAvail({ ...avail, max: e.target.value })} />
            </Field>
          </div>
          <HoursSlider value={avail.hours} onChange={(hours) => setAvail({ ...avail, hours })} />
          <label className="checkbox" style={{ marginTop: 12 }}>
            <input type="checkbox" checked={avail.paused} onChange={(e) => setAvail({ ...avail, paused: e.target.checked })} />
            <span>I'm temporarily not taking new work</span>
          </label>
        </>}

        {step === 4 && offering && <>
          <ul className="checklist">
            <li><span>Service</span><strong>{offering.title}</strong></li>
            <li><span>Specialization</span><span>{offering.specializationName ?? offering.specialization}</span></li>
            <li><span>Deliverables</span><span>{offering.deliverables.length ? offering.deliverables.join(' · ') : <span className="badge warn">Add at least one</span>}</span></li>
            <li><span>Engagement · pricing</span><span>{offering.engagementTypes.map((t) => LABEL[t]).join(', ')} · {priceText(offering)}</span></li>
            <li><span>Availability</span><span>{LABEL[profile.availability]}</span></li>
            <li><span>Status</span><span className={`badge ${STATUS_CLS[offering.status]}`}>{LABEL[offering.status]}</span></li>
          </ul>
          <div className="row" style={{ marginTop: 16 }}>
            <button type="button" className="btn btn-secondary" onClick={onDone}>Keep as draft</button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={publish}>
              {offering.status === 'ACTIVE' ? 'Done' : 'Publish service'}</button>
          </div>
        </>}

        {step < 4 && (
          <div className="row" style={{ marginTop: 16 }}>
            {step > 0 && <button type="button" className="btn btn-secondary" onClick={() => setStep(step - 1)}>Back</button>}
            <button className="btn btn-primary" disabled={busy || (step === 2 && types.length === 0)}>{busy ? 'Saving…' : 'Save and continue'}</button>
          </div>
        )}
      </form>
    </section>
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

  async function duplicate(o: Offering) {
    setError(null)
    try {
      await proApi.createOffering({
        title: `${o.title} (copy)`.slice(0, 150), specialization: o.specialization, summary: o.summary ?? undefined,
        deliverables: o.deliverables, engagementTypes: o.engagementTypes, pricingModel: o.pricingModel,
        startingPrice: o.startingPrice, typicalDuration: o.typicalDuration ?? undefined,
      })
      await load()
    } catch (err) {
      setError(err)
    }
  }

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
        <OfferingWizard profile={profile} offering={editing === 'new' ? null : editing}
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
            <div className="muted small">Availability: {LABEL[profile.availability] ?? profile.availability}</div>
            {o.deliverables.length > 0 && <ul className="deliverables">{o.deliverables.map((d) => <li key={d}>{d}</li>)}</ul>}
            <div className="row" style={{ marginTop: 'auto' }}>
              <button className="btn btn-secondary btn-sm" onClick={() => setEditing(o)}>Edit</button>
              {o.status === 'ACTIVE'
                ? <button className="btn btn-secondary btn-sm" onClick={() => setStatus(o, 'pause')}>Pause</button>
                : <button className="btn btn-primary btn-sm" onClick={() => setStatus(o, 'activate')}>Activate</button>}
              <button className="btn btn-ghost btn-sm" onClick={() => duplicate(o)}>Duplicate</button>
            </div>
          </article>
        ))}
      </div>
    </>
  )
}
