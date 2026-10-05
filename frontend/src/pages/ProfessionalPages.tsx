import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { firmApi, formatMoney, type Firm } from '../api/orgs'
import {
  AVAILABILITY, CREDENTIAL_TYPES, CURRENCIES, DELIVERY_MODES, ENGAGEMENT_TYPES, EXPERIENCE_BANDS, LABEL, PRICING_MODELS,
  RATE_UNIT_LABEL, RATE_UNITS, proApi, taxonomyApi, toMajor, toMinor,
  type Availability, type Credential, type Offering, type Profile, type Readiness, type TaxonomyCategory,
} from '../api/professional'
import { trustApi, type Trust } from '../api/verification'
import { useAuth } from '../auth/AuthContext'
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
  email: '/app/account', basics: '/app/professional/profile?step=basics', copy: '/app/professional/profile?step=basics',
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
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [offerings, setOfferings] = useState<Offering[]>([])
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [trust, setTrust] = useState<Trust | null>(null)

  useEffect(() => {
    if (!profile) return
    Promise.all([proApi.readiness(), proApi.offerings(), proApi.credentials(), trustApi.get(profile.id)])
      .then(([r, o, c, t]) => { setReadiness(r); setOfferings(o); setCredentials(c); setTrust(t) })
      .catch(() => {})
  }, [profile])

  if (loading) return <p className="muted">Loading…</p>
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Professional dashboard</h1>
          <p className="muted" style={{ margin: 0 }}>What you need to act on right now.</p>
        </div>
        {profile && (
          <div className="row">
            <Link className="btn btn-secondary" to={`/professionals/${profile.id}`}>View public profile</Link>
            <Link className="btn btn-primary" to="/app/professional/profile">Edit profile</Link>
          </div>
        )}
      </div>
      <AccountAlerts />
      <ErrorAlert error={error} />
      {!profile ? <CreateProfile onCreated={setProfile} /> : (
        <>
          <div className="grid-cards">
            <div className="card stat"><div className="label">Profile</div>
              <div style={{ marginTop: 10 }}><ProfileStatusBadge status={profile.status} /></div>
              <div className="note">{profile.status === 'PUBLISHED' ? 'Visible to buyers' : 'Only you can see it'}</div></div>
            <div className="card stat"><div className="label">Trust tier</div><div className="value">{trust?.tier ?? '—'}</div>
              <div className="note">{trust ? `${trust.tierLabel} · score ${trust.score}` : 'Loading…'}</div></div>
            <div className="card stat"><div className="label">Active offerings</div>
              <div className="value">{offerings.filter((o) => o.status === 'ACTIVE').length}</div>
              <div className="note">{offerings.length} in total</div></div>
            <div className="card stat"><div className="label">Credentials</div><div className="value">{credentials.length}</div>
              <div className="note">{credentials.filter((c) => c.status === 'VERIFIED').length} verified</div></div>
            <div className="card stat"><div className="label">Active engagements</div><div className="value">—</div>
              <div className="note">Arrives with proposals &amp; contracts</div></div>
          </div>
          {readiness && (
            <section className="card panel">
              <h2>{profile.status === 'PUBLISHED' ? 'Profile strength' : 'Get ready to publish'}</h2>
              {profile.status !== 'PUBLISHED' && (
                <p className="muted small">
                  {readiness.canPublish
                    ? <>Everything required is done. <Link to="/app/professional/profile?step=publish">Review and publish</Link>.</>
                    : 'Finish the required items to publish your profile.'}
                </p>
              )}
              <ReadinessList readiness={readiness} />
            </section>
          )}
          {trust && trust.tier !== 'A' && (
            <section className="card panel">
              <h2>Reach Tier {trust.tier === 'C' ? 'B' : 'A'}</h2>
              <ul className="why">{trust.explanation.filter((e) => e.startsWith('For Tier')).map((e) => <li key={e}>{e}</li>)}</ul>
              <Link className="btn btn-primary" to="/app/professional/verification">Go to verification</Link>
            </section>
          )}
        </>
      )}
    </>
  )
}

// ---- Profile setup (step by step) ----------------------------------------------

const STEPS = [
  { key: 'basics', label: 'Basics' },
  { key: 'specializations', label: 'Specializations' },
  { key: 'engagement', label: 'Engagement & pricing' },
  { key: 'availability', label: 'Availability' },
  { key: 'jurisdictions', label: 'Jurisdictions' },
  { key: 'credentials', label: 'Credentials' },
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
      <ErrorAlert error={error} />
      <div className="row">
        <Field label="Display name" id="b-name" hint="Shown to buyers.">
          <input id="b-name" className="input" value={f.displayName} onChange={set('displayName')} required />
        </Field>
        <Field label="Legal name (private)" id="b-legal" hint="As on your ID. Used for verification, never shown publicly.">
          <input id="b-legal" className="input" value={f.legalName} onChange={set('legalName')} />
        </Field>
      </div>
      <div style={{ height: 16 }} />
      <Field label="Headline" id="b-headline" hint="Your primary role, e.g. “Fractional CFO for SaaS companies”.">
        <input id="b-headline" className="input" maxLength={120} value={f.headline} onChange={set('headline')} />
      </Field>
      <Field label="Bio" id="b-bio" hint={`What you do and for whom, in plain words (at least 80 characters; ${f.bio.length}/3000). ` +
        'Avoid superlatives and guarantees such as “best”, “leading”, “top” or “#1”.'}>
        <textarea id="b-bio" className="input" rows={6} maxLength={3000} value={f.bio} onChange={set('bio')} />
      </Field>
      <div className="row">
        <Field label="Years of experience" id="b-exp">
          <select id="b-exp" className="input" value={f.yearsExperienceBand} onChange={set('yearsExperienceBand')}>
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

const STEP_VIEW: Record<StepKey, (p: StepProps) => ReactNode> = {
  basics: BasicsStep, specializations: SpecializationsStep, engagement: EngagementStep, availability: AvailabilityStep,
  jurisdictions: JurisdictionsStep, credentials: CredentialsStep, publish: PublishStep,
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
