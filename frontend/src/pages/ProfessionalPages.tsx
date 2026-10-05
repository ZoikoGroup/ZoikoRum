import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { firmApi, formatMoney, type Firm } from '../api/orgs'
import {
  AVAILABILITY, CREDENTIAL_TYPES, CURRENCIES, DELIVERY_MODES, ENGAGEMENT_TYPES, EXPERIENCE_BANDS, LABEL, PRICING_MODELS,
  RATE_UNIT_LABEL, RATE_UNITS, proApi, taxonomyApi, toMajor, toMinor,
  type Availability, type Credential, type Offering, type Profile, type Readiness, type TaxonomyCategory,
} from '../api/professional'
import { DIMENSION_VALUE, DIMENSIONS, trustApi, verificationApi, type Trust, type VerificationCase } from '../api/verification'
import { useAuth } from '../auth/AuthContext'
import { ActionList, Avatar, greeting, Icon, Kpi, type Action } from '../components/dashboard'
import { ErrorAlert, Field } from '../components/ui'
import { AccountAlerts } from './Dashboards'
import { COUNTRIES } from './Join'

// eslint-disable-next-line react-refresh/only-export-components
export function useMyProfile() {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const reload = useCallback(async () => {
    try {
      setProfile(await proApi.me())
    } catch (err) {
      if (err instanceof ApiError && err.code === 'PROFILE_NOT_FOUND') setProfile(null)
      else setError(err)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { reload() }, [reload])
  return { profile, setProfile, loading, error }
}

const COUNTRY_NAME = Object.fromEntries(COUNTRIES)
// eslint-disable-next-line react-refresh/only-export-components
export const countryName = (code: string) => COUNTRY_NAME[code] ?? code

export function ProfileStatusBadge({ status }: { status: string }) {
  const cls = status === 'PUBLISHED' ? 'green' : status === 'SUSPENDED' ? 'warn' : ''
  return <span className={`badge ${cls}`}>{LABEL[status] ?? status}</span>
}

/** Multi-select as a grid of checkbox tiles. */
function Choices<T extends string>({ name, options, value, onChange, label = (o) => LABEL[o] ?? o, disabled }: {
  name: string
  options: readonly T[]
  value: T[]
  onChange: (v: T[]) => void
  label?: (o: T) => ReactNode
  disabled?: (o: T) => boolean
}) {
  return (
    <div className="role-grid" role="group" aria-label={name}>
      {options.map((o) => (
        <label key={o} className="role-option">
          <input type="checkbox" checked={value.includes(o)} disabled={!value.includes(o) && disabled?.(o)}
            onChange={(e) => onChange(e.target.checked ? [...value, o] : value.filter((v) => v !== o))} />
          <span>{label(o)}</span>
        </label>
      ))}
    </div>
  )
}

// ---- Create ------------------------------------------------------------------

function CreateProfile({ onCreated }: { onCreated: (p: Profile) => void }) {
  const [firms, setFirms] = useState<Firm[]>([])
  const [firmId, setFirmId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { firmApi.mine().then(setFirms).catch(() => {}) }, [])

  async function create() {
    setBusy(true)
    setError(null)
    try {
      onCreated(await proApi.create({ firmId: firmId || null }))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card panel" style={{ maxWidth: 640 }}>
      <h2>Create your professional profile</h2>
      <p className="muted">
        Your profile is how buyers find you. It stays private until you publish it, and you can publish as soon as the
        basics are in place. Verification comes next and unlocks proposals and contracts.
      </p>
      <ErrorAlert error={error} />
      {firms.length > 0 && (
        <Field label="Practise as" id="pro-firm" hint="Firm members can offer services under their firm.">
          <select id="pro-firm" className="input" value={firmId} onChange={(e) => setFirmId(e.target.value)}>
            <option value="">An independent professional</option>
            {firms.map((f) => <option key={f.id} value={f.id}>A member of {f.tradingName || f.legalName}</option>)}
          </select>
        </Field>
      )}
      <button className="btn btn-primary" disabled={busy} onClick={create}>{busy ? 'Creating…' : 'Start my profile'}</button>
    </section>
  )
}

// ---- Dashboard ---------------------------------------------------------------

// Where each readiness item is fixed.
const FIX_AT: Record<string, string> = {
  email: '/app/account', basics: '/app/professional/profile?step=basics', photo: '/app/professional/profile?step=basics', bio: '/app/professional/profile?step=basics', copy: '/app/professional/profile?step=basics',
  specializations: '/app/professional/profile?step=specializations', engagement: '/app/professional/profile?step=engagement',
  pricing: '/app/professional/profile?step=engagement', jurisdictions: '/app/professional/profile?step=jurisdictions',
  availability: '/app/professional/profile?step=availability', credentials: '/app/professional/profile?step=credentials',
  offering: '/app/professional/offerings',
}

function ReadinessList({ readiness }: { readiness: Readiness }) {
  return (
    <ul className="checklist">
      {readiness.items.map((i) => (
        <li key={i.key}>
          <span>{i.done ? i.label : <Link to={FIX_AT[i.key]}>{i.label}</Link>}</span>
          {i.done ? <span className="badge green">Done</span>
            : i.required ? <span className="badge warn">Required</span> : <span className="badge">Recommended</span>}
        </li>
      ))}
    </ul>
  )
}

export function ProfessionalDashboard() {
  const { profile, setProfile, loading, error } = useMyProfile()
  const { user } = useAuth()
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [offerings, setOfferings] = useState<Offering[]>([])
  const [trust, setTrust] = useState<Trust | null>(null)
  const [cases, setCases] = useState<VerificationCase[]>([])
  const [actionError, setActionError] = useState<unknown>(null)

  const load = useCallback(async () => {
    if (!profile) return
    const [r, o, t, v] = await Promise.all([proApi.readiness(), proApi.offerings(), trustApi.get(profile.id),
      verificationApi.forSubject('PROFESSIONAL', profile.id)])
    setReadiness(r); setOfferings(o); setTrust(t); setCases(v)
  }, [profile])
  useEffect(() => { load().catch(() => {}) }, [load])

  if (loading || !user) return <p className="muted">Loading…</p>

  async function run(action: () => Promise<unknown>) {
    setActionError(null)
    try { await action(); await load() } catch (err) { setActionError(err) }
  }
  const duplicate = (o: Offering) => run(() => proApi.createOffering({
    title: `${o.title} (copy)`.slice(0, 150), specialization: o.specialization, summary: o.summary ?? undefined,
    deliverables: o.deliverables, engagementTypes: o.engagementTypes, pricingModel: o.pricingModel,
    startingPrice: o.startingPrice, typicalDuration: o.typicalDuration ?? undefined,
  }))

  const soon = Date.now() + 30 * 86400_000
  const expiring = cases.filter((c) => c.status === 'VERIFIED' && c.expiresAt && new Date(c.expiresAt).getTime() < soon)
  const actions: Action[] = []
  for (const c of cases.filter((c) => c.status === 'NEEDS_INFO')) {
    actions.push({ title: `More information needed: ${c.label}`, detail: c.publicReason ?? 'See the reviewer\'s note',
      priority: 'High', to: '/app/professional/verification', icon: 'shield' })
  }
  for (const c of expiring) {
    actions.push({ title: `${c.label} expires soon`, detail: `Valid until ${new Date(c.expiresAt!).toLocaleDateString()}: renew to keep your tier`,
      priority: 'High', to: '/app/professional/verification', icon: 'clock' })
  }
  for (const i of readiness?.items.filter((i) => i.required && !i.done) ?? []) {
    actions.push({ title: i.label, detail: 'Required before you can publish', priority: 'High', to: FIX_AT[i.key], icon: 'user' })
  }
  if (profile && readiness?.canPublish && profile.status !== 'PUBLISHED' && profile.status !== 'SUSPENDED') {
    actions.push({ title: 'Publish your profile', detail: 'Everything required is done', priority: 'Medium',
      to: '/app/professional/profile?step=publish', icon: 'check' })
  }
  if (trust?.dimensions.identity === 'NONE') {
    actions.push({ title: 'Verify your identity', detail: 'Reach Tier B to respond to requests', priority: 'Medium',
      to: '/app/professional/verification', icon: 'shield' })
  }
  for (const i of readiness?.items.filter((i) => !i.required && !i.done) ?? []) {
    actions.push({ title: i.label, detail: 'Recommended: makes your profile stronger', priority: 'Low', to: FIX_AT[i.key], icon: 'star' })
  }

  return (
    <>
      <div className="home-head">
        <div>
          <h1>{greeting(user.displayName)}</h1>
          <p className="muted" style={{ margin: 0 }}>What do you need to act on right now?</p>
        </div>
        {profile && (
          <div className="row">
            <Link className="btn btn-secondary" to={`/professionals/${profile.id}`}><Icon name="user" /> View public profile</Link>
            <Link className="btn btn-primary" to="/app/professional/offerings">+ New offering</Link>
          </div>
        )}
      </div>
      <AccountAlerts />
      <ErrorAlert error={error ?? actionError} />
      {!profile ? <CreateProfile onCreated={setProfile} /> : (
        <>
          {/* Summary cards (max 6) */}
          <div className="kpi-row six">
            <a href="#engagements"><Kpi icon="contract" tone="blue" label="Active Engagements" value={0} note="Contracts in progress" /></a>
            <a href="#requests"><Kpi icon="proposal" tone="violet" label="New Requests" value={0} note="From buyers" /></a>
            <a href="#actions"><Kpi icon="bell" tone="amber" label="Pending Actions" value={actions.length} note={actions.length ? 'Needs your attention' : 'All caught up'} /></a>
            <a href="#engagements"><Kpi icon="clock" tone="teal" label="Upcoming Milestones" value={0} note="Next 14 days" /></a>
            <a href="#earnings"><Kpi icon="check" tone="green" label="Earnings This Month" value="—" note="Live when payments launch" /></a>
            <a href="#verification"><Kpi icon="shield" tone={trust?.tier === 'C' ? 'amber' : 'green'} label="Verification Status"
              value={trust ? `Tier ${trust.tier}` : '—'} note={trust?.tierLabel ?? 'Loading…'} /></a>
          </div>

          <div className="home-grid">
            <div>
              <section className="card panel">
                <div className="panel-head"><h2>Service Offerings</h2><Link className="small" to="/app/professional/offerings">Manage</Link></div>
                {offerings.length === 0 ? (
                  <p className="muted small" style={{ margin: 0 }}>No offerings yet. <Link to="/app/professional/offerings">Create a structured service</Link> buyers can request.</p>
                ) : (
                  <div className="offering-grid compact">
                    {offerings.map((o) => (
                      <article key={o.id} className="offering card">
                        <div className="offering-top"><h3>{o.title}</h3>
                          <span className={`badge ${o.status === 'ACTIVE' ? 'green' : o.status === 'PAUSED' ? 'warn' : ''}`}>{LABEL[o.status]}</span></div>
                        <div className="muted small">{o.specializationName ?? o.specialization} · {o.engagementTypes.map((t) => LABEL[t]).join(', ')}</div>
                        <div className="price">{priceText(o)}{o.typicalDuration && <span className="muted small"> · {o.typicalDuration}</span>}</div>
                        <div className="muted small">Availability: {LABEL[profile.availability] ?? profile.availability}</div>
                        <div className="row" style={{ marginTop: 'auto' }}>
                          <Link className="btn btn-secondary btn-sm" to="/app/professional/offerings">View / Edit</Link>
                          {o.status === 'ACTIVE'
                            ? <button className="btn btn-ghost btn-sm" onClick={() => run(() => proApi.pauseOffering(o.id))}>Pause</button>
                            : <button className="btn btn-ghost btn-sm" onClick={() => run(() => proApi.activateOffering(o.id))}>Activate</button>}
                          <button className="btn btn-ghost btn-sm" onClick={() => duplicate(o)}>Duplicate</button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="card panel" id="requests">
                <div className="panel-head"><h2>Incoming Requests &amp; Proposals</h2></div>
                <table className="data">
                  <thead><tr><th>Buyer</th><th>Service</th><th>Type</th><th>Budget</th><th>Deadline</th><th>Actions</th></tr></thead>
                  <tbody><tr><td colSpan={6} className="empty-row">
                    <strong>No requests yet.</strong> Proposal requests from buyers appear here, ready to respond to.
                    Requests open in the next release; Tier B (verified identity) is needed to reply.
                  </td></tr></tbody>
                </table>
              </section>

              <section className="card panel" id="engagements">
                <div className="panel-head"><h2>Active Engagements</h2></div>
                <table className="data">
                  <thead><tr><th>Buyer</th><th>Service</th><th>Status</th><th>Milestone</th><th>Payment</th><th>Actions</th></tr></thead>
                  <tbody><tr><td colSpan={6} className="empty-row">
                    <strong>No active engagements.</strong> Signed contracts, milestones and submissions appear here.
                  </td></tr></tbody>
                </table>
              </section>
            </div>

            <aside>
              <section className="card panel attention" id="actions">
                <div className="panel-head"><h2>Pending Actions</h2></div>
                <ActionList actions={actions} empty="You're all set. New requests from buyers will appear here." />
              </section>
              <section className="card panel" id="earnings">
                <div className="panel-head"><h2>Earnings &amp; Payouts</h2></div>
                <ul className="checklist">
                  <li><span>Earnings this month</span><strong>—</strong></li>
                  <li><span>Pending release</span><strong>—</strong></li>
                  <li><span>Lifetime earnings</span><strong>—</strong></li>
                </ul>
                <p className="muted small" style={{ margin: '8px 0 0' }}>Live when payments launch: money is released from escrow when buyers accept milestones.</p>
              </section>
              {trust && (
                <section className="card panel" id="verification">
                  <div className="panel-head"><h2>Verification &amp; Trust</h2>
                    <span className={`badge ${trust.tier === 'C' ? 'warn' : 'green'}`}>Tier {trust.tier}</span></div>
                  <ul className="checklist">
                    {DIMENSIONS.map((d) => {
                      const v = DIMENSION_VALUE[trust.dimensions[d.key]] ?? { label: 'Not verified', good: false }
                      return <li key={d.key}><span>{d.label}</span><span className={`badge ${v.good ? 'green' : ''}`}>{v.label}</span></li>
                    })}
                  </ul>
                  {expiring.length > 0 && (
                    <div className="alert alert-warn" style={{ margin: '10px 0 0' }}>
                      {expiring.map((c) => <div key={c.id}>{c.label} expires {new Date(c.expiresAt!).toLocaleDateString()}</div>)}
                    </div>
                  )}
                  <Link className="btn btn-secondary btn-sm" style={{ marginTop: 12 }} to="/app/professional/verification">Complete verification →</Link>
                </section>
              )}
            </aside>
          </div>
        </>
      )}
    </>
  )
}

// ---- Profile setup (step by step) ----------------------------------------------

const STEPS = [
  { key: 'basics', label: 'Basics' },
  { key: 'specializations', label: 'Services' },
  { key: 'engagement', label: 'Pricing & engagement' },
  { key: 'availability', label: 'Availability' },
  { key: 'verification', label: 'Verification' },
  { key: 'credentials', label: 'Credentials' },
  { key: 'jurisdictions', label: 'Jurisdictions' },
  { key: 'publish', label: 'Review & publish' },
] as const
type StepKey = (typeof STEPS)[number]['key']

interface StepProps {
  profile: Profile
  onSaved: (p: Profile) => void
  next: () => void
}

/** Shared save wiring for each step's form. */
function useSave(onError: (e: unknown) => void) {
  const [busy, setBusy] = useState(false)
  async function save(action: () => Promise<void>) {
    setBusy(true)
    onError(null)
    try {
      await action()
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }
  return { busy, save }
}

function StepActions({ busy, label = 'Save and continue' }: { busy: boolean; label?: string }) {
  return <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : label}</button>
}

/** Profile photo (Onboarding s.7, required to publish): JPEG, PNG or WebP under 2 MB. */
function PhotoUploader({ profile, onSaved }: { profile: Profile; onSaved: (p: Profile) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  async function upload(file: File | undefined) {
    if (!file) return
    setError(null)
    if (file.size > 2 * 1024 * 1024) { setError(new Error('Use a photo under 2 MB.')); return }
    setBusy(true)
    try {
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
        reader.onerror = () => reject(new Error('The photo could not be read.'))
        reader.readAsDataURL(file)
      })
      onSaved(await proApi.setPhoto(file.type, base64))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="photo-row">
      <Avatar name={profile.displayName} photoUrl={profile.photoUrl} size={72} />
      <div>
        <label className="btn btn-secondary btn-sm" style={{ cursor: busy ? 'wait' : 'pointer' }}>
          {busy ? 'Uploading…' : profile.photoUrl ? 'Change photo' : 'Upload photo *'}
          <input type="file" accept="image/jpeg,image/png,image/webp" hidden disabled={busy}
            onChange={(e) => upload(e.target.files?.[0])} />
        </label>
        {profile.photoUrl && (
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
            onClick={async () => { try { onSaved(await proApi.removePhoto()) } catch (err) { setError(err) } }}>Remove</button>
        )}
        <p className="muted small" style={{ margin: '6px 0 0' }}>A clear, professional head-and-shoulders photo. JPEG, PNG or WebP, under 2 MB.</p>
        <ErrorAlert error={error} />
      </div>
    </div>
  )
}

function BasicsStep({ profile, onSaved, next }: StepProps) {
  const [f, setF] = useState({
    displayName: profile.displayName, legalName: profile.legalName ?? '', headline: profile.headline ?? '',
    yearsExperienceBand: profile.yearsExperienceBand ?? '', bio: profile.bio ?? '', languages: profile.languages.join(', '),
    city: profile.city ?? '', country: profile.country, website: profile.website ?? '',
  })
  const [error, setError] = useState<unknown>(null)
  const { busy, save } = useSave(setError)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  function submit(e: FormEvent) {
    e.preventDefault()
    save(async () => {
      const { languages, yearsExperienceBand, ...rest } = f
      onSaved(await proApi.update(profile.version, {
        ...rest, languages: languages.split(',').map((l) => l.trim()).filter(Boolean),
        ...(yearsExperienceBand ? { yearsExperienceBand } : {}),
      }))
      next()
    })
  }

  return (
    <form onSubmit={submit}>
      <PhotoUploader profile={profile} onSaved={onSaved} />
      <ErrorAlert error={error} />
      <div className="row">
        <Field label="Display name" id="b-name" hint="Shown to buyers.">
          <input id="b-name" className="input" value={f.displayName} onChange={set('displayName')} required />
        </Field>
        <Field label="Legal name (private) *" id="b-legal" hint="As on your ID. Used for verification, never shown publicly.">
          <input id="b-legal" className="input" value={f.legalName} onChange={set('legalName')} required />
        </Field>
      </div>
      <div style={{ height: 16 }} />
      <Field label="Primary role title *" id="b-headline" hint="e.g. “Fractional CFO for SaaS companies”.">
        <input id="b-headline" className="input" maxLength={120} value={f.headline} onChange={set('headline')} required />
      </Field>
      <Field label="Bio (optional)" id="b-bio" hint={`What you do and for whom, in plain words: 150–250 words reads best, 300 at most ` +
        `(${f.bio.trim() ? f.bio.trim().split(/\s+/).length : 0} words). Avoid superlatives and guarantees such as “best”, “top-rated” or “#1”.`}>
        <textarea id="b-bio" className="input" rows={6} maxLength={3000} value={f.bio} onChange={set('bio')} />
      </Field>
      <div className="row">
        <Field label="Years of experience *" id="b-exp">
          <select id="b-exp" className="input" value={f.yearsExperienceBand} onChange={set('yearsExperienceBand')} required>
            <option value="">Select…</option>
            {EXPERIENCE_BANDS.map((b) => <option key={b} value={b}>{b} years</option>)}
          </select>
        </Field>
        <Field label="Languages" id="b-lang" hint="Separate with commas.">
          <input id="b-lang" className="input" value={f.languages} onChange={set('languages')} placeholder="English, Spanish" />
        </Field>
      </div>
      <div style={{ height: 16 }} />
      <div className="row">
        <Field label="City" id="b-city">
          <input id="b-city" className="input" value={f.city} onChange={set('city')} />
        </Field>
        <Field label="Country" id="b-country">
          <select id="b-country" className="input" value={f.country} onChange={set('country')}>
            {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
        </Field>
      </div>
      <div style={{ height: 16 }} />
      <Field label="Website (optional)" id="b-web" hint="Must start with https://">
        <input id="b-web" className="input" value={f.website} onChange={set('website')} placeholder="https://" />
      </Field>
      <StepActions busy={busy} />
    </form>
  )
}

function SpecializationsStep({ profile, onSaved, next }: StepProps) {
  const [taxonomy, setTaxonomy] = useState<TaxonomyCategory[]>([])
  const [primary, setPrimary] = useState(profile.specializations.find((s) => s.primary)?.slug ?? '')
  const [secondary, setSecondary] = useState(profile.specializations.filter((s) => !s.primary).map((s) => s.slug))
  const [error, setError] = useState<unknown>(null)
  const { busy, save } = useSave(setError)
  useEffect(() => { taxonomyApi.all().then(setTaxonomy).catch(setError) }, [])

  function submit(e: FormEvent) {
    e.preventDefault()
    save(async () => {
      onSaved(await proApi.setSpecializations(primary, secondary.filter((s) => s !== primary)))
      next()
    })
  }

  const flags = (s: { requiresCredential: boolean; regulated: boolean }) => (
    <>{s.requiresCredential && <span className="badge warn">Credential required</span>}{' '}
      {s.regulated && <span className="badge">Regulated</span>}</>
  )

  return (
    <form onSubmit={submit}>
      <ErrorAlert error={error} />
      <p className="muted small">
        Choose from the Zoikorum taxonomy so buyers can find you: one primary specialization and up to five more.
        Specializations marked “Credential required” need a verified credential before you reach Tier A for them.
      </p>
      <Field label="Primary specialization" id="s-primary">
        <select id="s-primary" className="input" value={primary} onChange={(e) => setPrimary(e.target.value)} required>
          <option value="">Select…</option>
          {taxonomy.flatMap((c) => c.groups).map((g) => (
            <optgroup key={g.slug} label={g.name}>
              {g.specializations.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
            </optgroup>
          ))}
        </select>
      </Field>
      <h3>Other specializations <span className="muted small">({secondary.filter((s) => s !== primary).length}/5)</span></h3>
      {taxonomy.flatMap((c) => c.groups).map((g) => (
        <fieldset key={g.slug} className="group-set">
          <legend>{g.name}</legend>
          <Choices name={g.name} options={g.specializations.filter((s) => s.slug !== primary).map((s) => s.slug)}
            value={secondary} onChange={setSecondary}
            disabled={() => secondary.filter((s) => s !== primary).length >= 5}
            label={(slug) => {
              const s = g.specializations.find((x) => x.slug === slug)!
              return <>{s.name} <span>{flags(s)}</span></>
            }} />
        </fieldset>
      ))}
      <StepActions busy={busy || !primary} />
    </form>
  )
}

function EngagementStep({ profile, onSaved, next }: StepProps) {
  const [types, setTypes] = useState(profile.engagementTypes)
  const [modes, setModes] = useState(profile.deliveryModes)
  const [pricing, setPricing] = useState(profile.pricingModels)
  const [rate, setRate] = useState(toMajor(profile.indicativeRate))
  const [currency, setCurrency] = useState(profile.indicativeRate?.currency ?? 'USD')
  const [unit, setUnit] = useState(profile.rateUnit ?? 'HOUR')
  const [error, setError] = useState<unknown>(null)
  const { busy, save } = useSave(setError)

  function submit(e: FormEvent) {
    e.preventDefault()
    save(async () => {
      const rateBody = rate.trim()
        ? { indicativeRate: { amountMinor: toMinor(rate), currency }, rateUnit: unit }
        : profile.indicativeRate ? { clearRate: true } : {}
      onSaved(await proApi.update(profile.version, { engagementTypes: types, deliveryModes: modes, pricingModels: pricing, ...rateBody }))
      next()
    })
  }

  return (
    <form onSubmit={submit}>
      <ErrorAlert error={error} />
      <h3>How you engage</h3>
      <Choices name="Engagement types" options={ENGAGEMENT_TYPES} value={types} onChange={setTypes} />
      <h3 style={{ marginTop: 20 }}>How you deliver</h3>
      <Choices name="Delivery modes" options={DELIVERY_MODES} value={modes} onChange={setModes} />
      <h3 style={{ marginTop: 20 }}>How you price</h3>
      <Choices name="Pricing models" options={PRICING_MODELS} value={pricing} onChange={setPricing} />
      <h3 style={{ marginTop: 20 }}>Indicative rate (optional)</h3>
      <p className="muted small">A guide for buyers only. It is never binding: the price is agreed in each proposal.</p>
      <div className="row">
        <Field label="Amount" id="e-rate">
          <input id="e-rate" className="input" type="number" min="0" step="0.01" value={rate} onChange={(e) => setRate(e.target.value)} />
        </Field>
        <Field label="Currency" id="e-cur">
          <select id="e-cur" className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </Field>
        <Field label="Per" id="e-unit">
          <select id="e-unit" className="input" value={unit} onChange={(e) => setUnit(e.target.value)}>
            {RATE_UNITS.map((u) => <option key={u} value={u}>{RATE_UNIT_LABEL[u].replace('per ', '')}</option>)}
          </select>
        </Field>
      </div>
      <div style={{ height: 16 }} />
      <StepActions busy={busy} />
    </form>
  )
}

function AvailabilityStep({ profile, onSaved, next }: StepProps) {
  const [availability, setAvailability] = useState<Availability>(profile.availability)
  const [max, setMax] = useState(profile.maxConcurrentEngagements?.toString() ?? '')
  const [paused, setPaused] = useState(profile.temporarilyUnavailable)
  const [error, setError] = useState<unknown>(null)
  const { busy, save } = useSave(setError)

  function submit(e: FormEvent) {
    e.preventDefault()
    save(async () => {
      onSaved(await proApi.setAvailability({ availability, maxConcurrentEngagements: max ? Number(max) : null, temporarilyUnavailable: paused }))
      next()
    })
  }

  return (
    <form onSubmit={submit}>
      <ErrorAlert error={error} />
      <div className="row">
        <Field label="When can you start new work?" id="a-when">
          <select id="a-when" className="input" value={availability} onChange={(e) => setAvailability(e.target.value as Availability)}>
            {AVAILABILITY.map((a) => <option key={a} value={a}>{LABEL[a]}</option>)}
          </select>
        </Field>
        <Field label="Most engagements at once (optional)" id="a-max" hint="When you reach it, buyers see “At capacity”.">
          <input id="a-max" className="input" type="number" min={1} max={50} value={max} onChange={(e) => setMax(e.target.value)} />
        </Field>
      </div>
      <div style={{ height: 16 }} />
      <label className="checkbox">
        <input type="checkbox" checked={paused} onChange={(e) => setPaused(e.target.checked)} />
        <span>I'm temporarily not taking new work (buyers see “At capacity”)</span>
      </label>
      <StepActions busy={busy} />
    </form>
  )
}

/** Known countries as tiles, plus free-text ISO codes for the rest. */
function CountryPicker({ id, value, onChange }: { id: string; value: string[]; onChange: (v: string[]) => void }) {
  const known = COUNTRIES.map(([c]) => c)
  const [other, setOther] = useState(value.filter((c) => !known.includes(c)).join(', '))
  const update = (tiles: string[], text: string) =>
    onChange([...new Set([...tiles, ...text.split(',').map((c) => c.trim().toUpperCase()).filter(Boolean)])])
  const tiles = value.filter((c) => known.includes(c))
  return (
    <>
      <Choices name={id} options={known} value={tiles} onChange={(t) => update(t, other)} label={(c) => countryName(c)} />
      <div style={{ height: 12 }} />
      <Field label="Other countries (two-letter codes)" id={`${id}-other`} hint="For example: JP, BR, MX">
        <input id={`${id}-other`} className="input" value={other} onChange={(e) => { setOther(e.target.value); update(tiles, e.target.value) }} />
      </Field>
    </>
  )
}

function JurisdictionsStep({ profile, onSaved, next }: StepProps) {
  const [served, setServed] = useState(profile.servedJurisdictions)
  const [licensed, setLicensed] = useState(profile.licensedJurisdictions)
  const [ack, setAck] = useState(profile.crossBorderAcknowledged)
  const [error, setError] = useState<unknown>(null)
  const { busy, save } = useSave(setError)
  const crossBorder = served.filter((c) => c !== profile.country)

  function submit(e: FormEvent) {
    e.preventDefault()
    save(async () => {
      onSaved(await proApi.setJurisdictions({ served, licensed, crossBorderAcknowledged: ack }))
      next()
    })
  }

  return (
    <form onSubmit={submit}>
      <ErrorAlert error={error} />
      <h3>Where you serve clients</h3>
      <CountryPicker id="served" value={served} onChange={setServed} />
      <h3 style={{ marginTop: 8 }}>Where you hold a licence (if any)</h3>
      <p className="muted small">Licensed jurisdictions are checked during verification. They decide where you are eligible for regulated work.</p>
      <CountryPicker id="licensed" value={licensed} onChange={setLicensed} />
      {crossBorder.length > 0 && !profile.crossBorderAcknowledged && (
        <label className="checkbox">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>
            I understand that serving clients outside {countryName(profile.country)} ({crossBorder.map(countryName).join(', ')}) may
            be subject to local rules, licensing and tax, and I am responsible for complying with them.
          </span>
        </label>
      )}
      <StepActions busy={busy} />
    </form>
  )
}

function CredentialsStep({ profile, next }: StepProps) {
  const [items, setItems] = useState<Credential[]>([])
  const empty = { credentialType: 'CERTIFICATION', name: '', issuingBody: '', registrationNumber: '', jurisdiction: '', issuedOn: '', expiresOn: '', specialization: '' }
  const [f, setF] = useState(empty)
  const [error, setError] = useState<unknown>(null)
  const { busy, save } = useSave(setError)
  const load = useCallback(() => proApi.credentials().then(setItems).catch(setError), [])
  useEffect(() => { load() }, [load])
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  function add(e: FormEvent) {
    e.preventDefault()
    save(async () => {
      const body = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== '')) as unknown as Parameters<typeof proApi.addCredential>[0]
      await proApi.addCredential(body)
      setF(empty)
      await load()
    })
  }

  function withdraw(c: Credential) {
    if (!confirm(`Remove ${c.name} from your profile?`)) return
    save(async () => { await proApi.withdrawCredential(c.id); await load() })
  }

  return (
    <>
      <ErrorAlert error={error} />
      <p className="muted small">
        Credentials appear on your profile as <strong>Self-reported</strong> until they are verified with the issuing body.
        Registration numbers are only used for verification and are never shown to buyers.
      </p>
      {items.length > 0 && (
        <table className="data" style={{ marginBottom: 24 }}>
          <thead><tr><th>Credential</th><th>Issued by</th><th>Expires</th><th>Status</th><th /></tr></thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id}>
                <td><strong>{c.name}</strong><div className="muted small">{LABEL[c.credentialType]}{c.jurisdiction && ` · ${c.jurisdiction}`}</div></td>
                <td>{c.issuingBody}</td>
                <td>{c.expiresOn ?? '—'}</td>
                <td><span className={`badge ${c.status === 'VERIFIED' ? 'green' : ''}`}>{c.displayLabel}</span></td>
                <td style={{ textAlign: 'right' }}><button className="btn btn-danger btn-sm" disabled={busy} onClick={() => withdraw(c)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form className="card panel" style={{ boxShadow: 'none' }} onSubmit={add}>
        <h3>Add a credential</h3>
        <div className="row">
          <Field label="Type" id="c-type">
            <select id="c-type" className="input" value={f.credentialType} onChange={set('credentialType')}>
              {CREDENTIAL_TYPES.map((t) => <option key={t} value={t}>{LABEL[t]}</option>)}
            </select>
          </Field>
          <Field label="Name" id="c-name" hint="e.g. Certified Public Accountant (CPA)">
            <input id="c-name" className="input" value={f.name} onChange={set('name')} required minLength={2} />
          </Field>
        </div>
        <div style={{ height: 16 }} />
        <div className="row">
          <Field label="Issuing body" id="c-issuer" hint="e.g. Texas State Board of Public Accountancy">
            <input id="c-issuer" className="input" value={f.issuingBody} onChange={set('issuingBody')} required minLength={2} />
          </Field>
          <Field label="Registration number (private)" id="c-reg">
            <input id="c-reg" className="input" value={f.registrationNumber} onChange={set('registrationNumber')} />
          </Field>
        </div>
        <div style={{ height: 16 }} />
        <div className="row">
          <Field label="Jurisdiction" id="c-jur" hint="Country code, e.g. US">
            <input id="c-jur" className="input" maxLength={10} value={f.jurisdiction} onChange={set('jurisdiction')} />
          </Field>
          <Field label="Issued on" id="c-issued">
            <input id="c-issued" className="input" type="date" value={f.issuedOn} onChange={set('issuedOn')} />
          </Field>
          <Field label="Expires on" id="c-exp">
            <input id="c-exp" className="input" type="date" value={f.expiresOn} onChange={set('expiresOn')} />
          </Field>
        </div>
        <div style={{ height: 16 }} />
        {profile.specializations.length > 0 && (
          <Field label="Supports specialization (optional)" id="c-spec">
            <select id="c-spec" className="input" value={f.specialization} onChange={set('specialization')}>
              <option value="">None in particular</option>
              {profile.specializations.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
            </select>
          </Field>
        )}
        <div className="row">
          <button className="btn btn-secondary" disabled={busy}>{busy ? 'Adding…' : 'Add credential'}</button>
          <button type="button" className="btn btn-primary" onClick={next}>Continue</button>
        </div>
      </form>
    </>
  )
}

function PublishStep({ profile, onSaved }: StepProps) {
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [attest, setAttest] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const { busy, save } = useSave(setError)
  const load = useCallback(() => proApi.readiness().then(setReadiness).catch(setError), [])
  useEffect(() => { load() }, [load, profile])

  const published = profile.status === 'PUBLISHED'
  return (
    <>
      <ErrorAlert error={error} />
      {published && (
        <div className="alert alert-success" role="status">
          Your profile is live. <Link to={`/professionals/${profile.id}`}>See it as buyers do</Link>.
        </div>
      )}
      {profile.status === 'SUSPENDED' && (
        <div className="alert alert-warn">Your profile is suspended. You will have received a notice explaining why and what you can do.</div>
      )}
      {readiness && <ReadinessList readiness={readiness} />}
      <div style={{ height: 20 }} />
      {published ? (
        <button className="btn btn-secondary" disabled={busy}
          onClick={() => save(async () => { onSaved(await proApi.unpublish()) })}>
          Unpublish profile
        </button>
      ) : profile.status !== 'SUSPENDED' && (
        <>
          <label className="checkbox">
            <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
            <span>I confirm that the information on my profile is accurate and that I hold the credentials I list.</span>
          </label>
          <div className="row">
            <Link className="btn btn-secondary" to={`/professionals/${profile.id}`}>Preview</Link>
            <button className="btn btn-primary" disabled={busy || !attest || !readiness?.canPublish}
              onClick={() => save(async () => { onSaved(await proApi.publish()); await load() })}>
              {busy ? 'Publishing…' : 'Publish profile'}
            </button>
          </div>
          <p className="muted small" style={{ marginTop: 12 }}>
            New profiles appear as <strong>Tier C · Unverified (Discovery Only)</strong> until identity is verified.{' '}
            <Link to="/app/professional/verification">Start verification</Link>
          </p>
        </>
      )}
    </>
  )
}

/** Verification checklist step (Onboarding s.10-11): what is verified, what each tier unlocks, where to start. */
function VerificationStep({ profile, next }: StepProps) {
  const [trust, setTrust] = useState<Trust | null>(null)
  useEffect(() => { trustApi.get(profile.id).then(setTrust).catch(() => {}) }, [profile.id])
  return (
    <>
      <p className="muted small">Verification raises your Trust Tier. You can publish now as Tier C and verify at any time.</p>
      {trust && (
        <ul className="checklist">
          <li><span><strong>Your tier</strong></span><span className={`badge ${trust.tier === 'C' ? 'warn' : 'green'}`}>Tier {trust.tier} · {trust.tierLabel}</span></li>
          {DIMENSIONS.map((d) => {
            const v = DIMENSION_VALUE[trust.dimensions[d.key]] ?? { label: 'Not verified', good: false }
            return <li key={d.key}><span>{d.label}</span><span className={`badge ${v.good ? 'green' : ''}`}>{v.label}</span></li>
          })}
        </ul>
      )}
      <div className="row" style={{ marginTop: 16 }}>
        <Link className="btn btn-secondary" to="/app/professional/verification">Verify identity and more</Link>
        <button type="button" className="btn btn-primary" onClick={next}>Continue</button>
      </div>
    </>
  )
}

const STEP_VIEW: Record<StepKey, (p: StepProps) => ReactNode> = {
  basics: BasicsStep, specializations: SpecializationsStep, engagement: EngagementStep, availability: AvailabilityStep,
  verification: VerificationStep, credentials: CredentialsStep, jurisdictions: JurisdictionsStep, publish: PublishStep,
}

export function ProfileSetupPage() {
  const { profile, setProfile, loading, error } = useMyProfile()
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const [saved, setSaved] = useState(false)
  const step = (STEPS.find((s) => s.key === params.get('step'))?.key ?? 'basics') as StepKey
  const index = STEPS.findIndex((s) => s.key === step)
  const go = (key: StepKey) => { setParams({ step: key }); window.scrollTo(0, 0) }

  if (loading) return <p className="muted">Loading…</p>
  const View = STEP_VIEW[step]
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Your professional profile</h1>
          <p className="muted" style={{ margin: 0 }}>
            {profile ? <><ProfileStatusBadge status={profile.status} /> · Step {index + 1} of {STEPS.length}</> : 'Set up how buyers see you.'}
          </p>
        </div>
      </div>
      <ErrorAlert error={error} />
      {!profile ? <CreateProfile onCreated={setProfile} /> : (
        <>
          <nav className="steps" aria-label="Profile setup steps">
            {STEPS.map((s, i) => (
              <button key={s.key} type="button" aria-current={s.key === step ? 'step' : undefined} onClick={() => { setSaved(false); go(s.key) }}>
                <span className="n">{i + 1}</span>{s.label}
              </button>
            ))}
          </nav>
          {saved && <div className="alert alert-success" role="status">Saved.</div>}
          {!user?.emailConfirmed && step === 'publish' && (
            <div className="alert alert-warn">Confirm your email address before publishing. <Link to="/app/account">Account settings</Link></div>
          )}
          <section className="card panel">
            <h2>{STEPS[index].label}</h2>
            {/* key: remount the form with fresh values when the profile changes elsewhere */}
            <View key={`${step}-${profile.version}`} profile={profile}
              onSaved={(p) => { setProfile(p); setSaved(true) }}
              next={() => { if (index < STEPS.length - 1) go(STEPS[index + 1].key) }} />
          </section>
        </>
      )}
    </>
  )
}

/** Price shown on cards and the public profile. */
// eslint-disable-next-line react-refresh/only-export-components
export function priceText(o: { pricingModel: string; startingPrice: { amountMinor: number; currency: string } | null }) {
  if (o.pricingModel === 'CUSTOM' || !o.startingPrice) return LABEL.CUSTOM
  return `From ${formatMoney(o.startingPrice)}${o.pricingModel === 'HOURLY' ? ' per hour' : ''}`
}
