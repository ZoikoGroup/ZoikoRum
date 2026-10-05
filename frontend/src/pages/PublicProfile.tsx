import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { formatMoney } from '../api/orgs'
import { LABEL, RATE_UNIT_LABEL, proApi, type PublicProfile } from '../api/professional'
import { DIMENSION_VALUE, DIMENSIONS } from '../api/verification'
import { ErrorAlert, SiteHeader } from '../components/ui'
import { countryName, priceText } from './ProfessionalPages'

const TIER_LABEL = { A: 'Fully Verified Professional', B: 'Verified Identity', C: 'Unverified (Discovery Only)' }

/** Public professional profile. Works signed in or out; unpublished profiles are visible only to their owner. */
export default function PublicProfilePage() {
  const { id = '' } = useParams()
  const [p, setP] = useState<PublicProfile | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { proApi.publicProfile(id).then(setP).catch(setError) }, [id])

  return (
    <>
      <SiteHeader />
      <main className="profile-wrap">
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
                <h1>{p.displayName}</h1>
                {p.headline && <p className="headline">{p.headline}</p>}
                <p className="muted small" style={{ margin: 0 }}>
                  {[p.city, countryName(p.country)].filter(Boolean).join(', ')}
                  {p.primaryCategoryName && ` · ${p.primaryCategoryName}`}
                  {p.yearsExperienceBand && ` · ${p.yearsExperienceBand} years’ experience`}
                </p>
                <div className="badges" style={{ marginTop: 12 }}>
                  <span className={`badge ${p.trust.tier === 'C' ? 'warn' : 'green'}`}>Tier {p.trust.tier} · {TIER_LABEL[p.trust.tier]}</span>
                  <span className={`badge ${p.availability === 'AT_CAPACITY' ? 'warn' : 'green'}`}>{LABEL[p.availability]}</span>
                </div>
              </div>
              <div className="cta">
                <button className="btn btn-primary" disabled title="Proposal requests arrive in an upcoming release">Request a proposal</button>
                <span className="muted small">Coming soon</span>
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
                      </article>
                    ))}
                  </section>
                )}
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
                  <p className="muted small" style={{ margin: '8px 0 0' }}>Trust score {p.trust.score} / 100. Every check is decided by a person.</p>
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
                  {p.licensedJurisdictions.length > 0 && <p className="small" style={{ margin: '6px 0 0' }}>Licensed in: {p.licensedJurisdictions.map(countryName).join(', ')}</p>}
                </section>
              </aside>
            </div>
          </>
        )}
      </main>
    </>
  )
}
