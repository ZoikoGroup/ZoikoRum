import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { formatMoney } from '../api/orgs'
import { LABEL, RATE_UNIT_LABEL, proApi, type PublicProfile } from '../api/professional'
import { DIMENSION_VALUE, DIMENSIONS } from '../api/verification'
import { useAuth } from '../auth/AuthContext'
import { Avatar } from '../components/dashboard'
import { ErrorAlert, SiteFooter, SiteHeader } from '../components/ui'
import { countryName, priceText } from './ProfessionalPages'
import { SaveButton, useSavedIds } from './SavedPage'

const TIER_LABEL = { A: 'Fully Verified Professional', B: 'Verified Identity', C: 'Unverified (Discovery Only)' }
const AVAILABILITY_CLASS: Record<string, string> = { NOW: 'green', TWO_WEEKS: 'green', ONE_MONTH: 'green', AT_CAPACITY: 'warn' }

/** Public professional profile (Professional Profile doc). Works signed in or out; unpublished profiles are
    visible only to their owner. Never shows private data, the raw trust score or screening outcomes. */
export default function PublicProfilePage() {
  const { id = '' } = useParams()
  const [p, setP] = useState<PublicProfile | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { proApi.publicProfile(id).then(setP).catch(setError) }, [id])
  const savedIds = useSavedIds()
  const { user } = useAuth()

  const keyCredentials = p?.credentials.filter((c) => c.status === 'VERIFIED').slice(0, 2) ?? []
  return (
    <>
      <SiteHeader />
      <main className="profile-wrap">
        <nav className="breadcrumb small" aria-label="Breadcrumb">
          <Link to="/professionals">Find professionals</Link>
          {p?.primaryCategory && <> › <Link to={`/professionals?category=${p.primaryCategory}`}>{p.primaryCategoryName}</Link></>}
          {p && <> › <span>{p.displayName}</span></>}
        </nav>
        <ErrorAlert error={error} />
        {!p && !error && <p className="muted">Loading…</p>}
        {p && (
          <>
            {p.isOwnProfile && (
              <div className="alert alert-info">
                This is how buyers see your profile. If it isn't published yet, only you can see it.{' '}
                <Link to="/app/professional/profile">Edit profile</Link>
              </div>
            )}
            <section className="card panel profile-head">
              <div>
                <div className="name-row"><Avatar name={p.displayName} photoUrl={p.photoUrl} size={72} /><h1>{p.displayName}</h1></div>
                {p.headline && <p className="headline">{p.headline}</p>}
                {p.firm && <p className="small" style={{ margin: '0 0 6px' }}>Practises with <strong>{p.firm.name}</strong>
                  {p.firm.verified ? <span className="badge green" style={{ marginLeft: 8 }}>Firm verified</span> : null}</p>}
                <p className="muted small" style={{ margin: 0 }}>
                  {[p.city, countryName(p.country)].filter(Boolean).join(', ')}
                  {p.primaryCategoryName && ` · ${p.primaryCategoryName}`}
                  {p.yearsExperienceBand && ` · ${p.yearsExperienceBand} years’ experience`}
                  {p.deliveryModes.length > 0 && ` · ${p.deliveryModes.map((d) => LABEL[d]).join(' / ')}`}
                </p>
                <div className="badges" style={{ marginTop: 12 }}>
                  <span className={`badge ${p.trust.tier === 'C' ? 'warn' : 'green'}`}>Tier {p.trust.tier} · {TIER_LABEL[p.trust.tier]}</span>
                  <span className={`badge ${AVAILABILITY_CLASS[p.availability] ?? ''}`}>{LABEL[p.availability]}</span>
                  {keyCredentials.map((c) => <span key={c.name} className="badge green">✓ {c.name}</span>)}
                </div>
                {p.trust.updatedAt && <p className="muted small" style={{ margin: '8px 0 0' }}>Last verified {new Date(p.trust.updatedAt).toLocaleDateString()}</p>}
              </div>
              <div className="cta">
                {savedIds.canSave && savedIds.ids && !p.isOwnProfile && (
                  <SaveButton id={p.id} saved={savedIds.ids.has(p.id)} onToggle={(pid) => { savedIds.toggle(pid).catch(setError) }} />
                )}
                {savedIds.canSave && !p.isOwnProfile && (
                  <Link className="btn btn-primary" to={`/app/requests/new?pro=${p.id}`}>Request proposal</Link>
                )}
                {!user && <Link className="btn btn-primary" to="/login">Sign in to request a proposal</Link>}
                <span className="muted small" style={{ maxWidth: 220, textAlign: 'right' }}>
                  No payment until you accept a proposal and sign the contract.
                </span>
              </div>
            </section>

            <div className="profile-cols">
              <div>
                {p.bio && (
                  <section className="card panel"><h2>About</h2>
                    {p.bio.split(/\n+/).map((para, i) => <p key={i}>{para}</p>)}
                    {p.languages.length > 0 && <p className="muted small" style={{ margin: 0 }}>Languages: {p.languages.join(', ')}</p>}
                  </section>
                )}
                <section className="card panel"><h2>Specializations</h2>
                  <div className="badges">
                    {p.specializations.map((s) => <span key={s.slug} className={`badge ${s.primary ? 'green' : ''}`}>{s.name}{s.primary && ' · Primary'}</span>)}
                  </div>
                </section>
                {p.offerings.length > 0 && (
                  <section className="card panel"><h2>Services</h2>
                    {p.offerings.map((o) => (
                      <article key={o.id} className="service">
                        <div className="offering-top"><h3>{o.title}</h3><strong>{priceText(o)}</strong></div>
                        <div className="muted small">{o.specializationName} · {o.engagementTypes.map((t) => LABEL[t]).join(', ')}
                          {o.typicalDuration && ` · ${o.typicalDuration}`}</div>
                        {o.summary && <p style={{ marginTop: 8 }}>{o.summary}</p>}
                        {o.deliverables.length > 0 && <ul className="deliverables">{o.deliverables.map((d) => <li key={d}>{d}</li>)}</ul>}
                        {savedIds.canSave && !p.isOwnProfile && (
                          <Link className="btn btn-secondary btn-sm" to={`/app/requests/new?pro=${p.id}&offering=${o.id}`}>Request this service</Link>
                        )}
                      </article>
                    ))}
                  </section>
                )}
                <section className="card panel"><h2>Contracts &amp; payment protection</h2>
                  <ul className="why" style={{ margin: 0 }}>
                    <li>Every engagement runs under a signed contract with agreed scope and milestones.</li>
                    <li>Payments are held in escrow and released only when you accept the work.</li>
                    <li>If something goes wrong, a structured dispute process holds the funds while it is resolved.</li>
                  </ul>
                </section>
              </div>
              <aside>
                <section className="card panel"><h2>Verification</h2>
                  <ul className="checklist">
                    {DIMENSIONS.map((d) => {
                      const v = DIMENSION_VALUE[p.trust.dimensions[d.key]] ?? { label: 'Not verified', good: false }
                      return <li key={d.key}><span>{d.label}</span><span className={`badge ${v.good ? 'green' : ''}`}>{v.label}</span></li>
                    })}
                    <li><span>Engagement integrity</span><span className="muted small">No engagements yet</span></li>
                  </ul>
                  <p className="muted small" style={{ margin: '8px 0 0' }}>Checks are made by a verification provider or a compliance reviewer — never by AI.</p>
                </section>
                <section className="card panel"><h2>How they work</h2>
                  <ul className="checklist">
                    <li><span>Engagements</span><span>{p.engagementTypes.map((t) => LABEL[t]).join(', ') || '—'}</span></li>
                    <li><span>Delivery</span><span>{p.deliveryModes.map((t) => LABEL[t]).join(', ') || '—'}</span></li>
                    <li><span>Pricing</span><span>{p.pricingModels.map((t) => LABEL[t]).join(', ') || '—'}</span></li>
                    {p.indicativeRate && <li><span>Indicative rate</span><span>{formatMoney(p.indicativeRate)} {RATE_UNIT_LABEL[p.rateUnit ?? ''] ?? ''}</span></li>}
                  </ul>
                  {p.indicativeRate && <p className="muted small" style={{ margin: '8px 0 0' }}>Indicative only. The price is agreed in each proposal.</p>}
                </section>
                <section className="card panel"><h2>Credentials</h2>
                  {p.credentials.length === 0 ? <p className="muted small" style={{ margin: 0 }}>None listed.</p> : (
                    <ul className="checklist">
                      {p.credentials.map((c, i) => (
                        <li key={i}><span><strong>{c.name}</strong><br /><span className="muted small">{c.issuingBody}{c.jurisdiction && ` · ${c.jurisdiction}`}</span></span>
                          <span className={`badge ${c.status === 'VERIFIED' ? 'green' : ''}`}>{c.displayLabel}</span></li>
                      ))}
                    </ul>
                  )}
                </section>
                <section className="card panel"><h2>Jurisdictions</h2>
                  <p className="small" style={{ margin: 0 }}>Serves: {p.servedJurisdictions.map(countryName).join(', ') || '—'}</p>
                  {p.licensedJurisdictions.length > 0 && (
                    <p className="small" style={{ margin: '6px 0 0' }}>Licensed in: {p.licensedJurisdictions.map((j) =>
                      `${countryName(j)} (${p.verifiedJurisdictions.includes(j) ? 'verified' : 'self-reported'})`).join(', ')}</p>
                  )}
                </section>
              </aside>
            </div>
            <p className="muted small disclosure">
              {p.displayName} is an independent professional. Zoikorum provides marketplace infrastructure, verification,
              contracting facilitation and payment protection; it does not employ professionals or provide regulated professional services.
            </p>
          </>
        )}
      </main>
      <SiteFooter />
    </>
  )
}
