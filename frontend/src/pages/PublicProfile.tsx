import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { messagingApi } from '../api/messaging'
import { formatMoney, orgApi } from '../api/orgs'
import { LABEL, RATE_UNIT_LABEL, proApi, type PublicProfile } from '../api/professional'
import { DIMENSION_VALUE, DIMENSIONS } from '../api/verification'
import { useAuth } from '../auth/AuthContext'
import { ReportButton } from '../components/ReportButton'
import { Avatar } from '../components/dashboard'
import { ErrorAlert, SiteFooter, SiteHeader, Loading } from '../components/ui'
import { equivalency } from '../lib/equivalency'
import { countryName, priceText } from './ProfessionalPages'
import { SaveButton, useSavedIds } from './SavedPage'
import { PublicReviews } from '../components/PublicReviews'

const TIER_LABEL = { A: 'Fully Verified Professional', B: 'Verified Identity', C: 'Unverified (Discovery Only)' }
const TIER_MEANING: Record<string, string> = {
  A: 'Tier A: identity, credentials, right to practise and screening are all verified. Can take regulated work.',
  B: 'Tier B: identity is verified. Can be engaged; regulated work needs Tier A.',
  C: 'Tier C: not verified yet. Can be found, but cannot send or have a proposal accepted.',
}

/** Search engines read the profile and breadcrumb from structured data (schema.org), added while the page is open. */
function useStructuredData(p: PublicProfile | null) {
  useEffect(() => {
    if (!p) return
    const origin = window.location.origin
    const crumbs = [{ name: 'Find professionals', url: `${origin}/professionals` },
      ...(p.primaryCategory ? [{ name: p.primaryCategoryName ?? p.primaryCategory, url: `${origin}/categories/${p.primaryCategory}` }] : []),
      { name: p.displayName, url: `${origin}/professionals/${p.id}` }]
    const data = [
      { '@context': 'https://schema.org', '@type': 'Person', name: p.displayName, jobTitle: p.headline ?? undefined,
        url: `${origin}/professionals/${p.id}`, image: p.photoUrl ?? undefined, knowsLanguage: p.languages,
        address: { '@type': 'PostalAddress', addressLocality: p.city ?? undefined, addressCountry: p.country },
        hasCredential: p.credentials.filter((c) => c.status === 'VERIFIED').map((c) => ({ '@type': 'EducationalOccupationalCredential', name: c.name, recognizedBy: { '@type': 'Organization', name: c.issuingBody } })) },
      { '@context': 'https://schema.org', '@type': 'BreadcrumbList',
        itemListElement: crumbs.map((c, i) => ({ '@type': 'ListItem', position: i + 1, name: c.name, item: c.url })) },
    ]
    const tag = document.createElement('script')
    tag.type = 'application/ld+json'
    tag.text = JSON.stringify(data)
    document.head.appendChild(tag)
    const title = document.title
    document.title = `${p.displayName}${p.headline ? ` · ${p.headline}` : ''} | Zoikorum`
    return () => { tag.remove(); document.title = title }
  }, [p])
}
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
  // Buyer location vs eligibility (Profile doc s.15, Onboarding s.13): surfaced on the profile, before any request.
  const [buyerCountry, setBuyerCountry] = useState<string | null>(null)
  useEffect(() => { if (savedIds.canSave) orgApi.mine().then((o) => setBuyerCountry(o[0]?.country ?? null)).catch(() => {}) }, [savedIds.canSave])
  const outOfArea = !!(p && buyerCountry && p.servedJurisdictions.length > 0 && !p.servedJurisdictions.includes(buyerCountry))

  const keyCredentials = p?.credentials.filter((c) => c.status === 'VERIFIED').slice(0, 2) ?? []
  useStructuredData(p)
  const primary = p?.specializations.find((s) => s.primary)
  return (
    <>
      <SiteHeader />
      <main className="profile-wrap">
        <nav className="breadcrumb small" aria-label="Breadcrumb">
          <Link to="/professionals">Find professionals</Link>
          {p?.primaryCategory && <> › <Link to={`/categories/${p.primaryCategory}`}>{p.primaryCategoryName}</Link></>}
          {primary && <> › <Link to={`/professionals?spec=${primary.slug}`}>{primary.name}</Link></>}
          {p && <> › <span>{p.displayName}</span></>}
        </nav>
        <ErrorAlert error={error} />
        {!p && !error && <Loading />}
        {p && (
          <>
            {p.isOwnProfile && (
              <div className="alert alert-info">
                This is how buyers see your profile. If it isn't published yet, only you can see it.{' '}
                <Link to="/app/professional/profile">Edit profile</Link>
              </div>
            )}
            {outOfArea && <div className="alert alert-warn" role="status">{p.displayName} does not list {countryName(buyerCountry ?? "")} among the places they serve. You can still ask, but an engagement cannot be agreed. <Link to={`/app/find?jurisdiction=${buyerCountry}`}>Show professionals who serve {countryName(buyerCountry ?? "")}</Link></div>}
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
                  <a href="#verification-report" className={`badge ${p.trust.tier === 'C' ? 'warn' : 'green'}`} title={TIER_MEANING[p.trust.tier]}
                    aria-describedby="tier-meaning">Tier {p.trust.tier} · {TIER_LABEL[p.trust.tier]} ⓘ</a>
                  <span id="tier-meaning" className="sr-only">{TIER_MEANING[p.trust.tier]}</span>
                  {(p.verificationInProgress ?? []).length > 0 && <span className="badge" title={`Under review: ${p.verificationInProgress!.join(', ')}`}>
                    Verification in progress</span>}
                  <span className={`badge ${AVAILABILITY_CLASS[p.availability] ?? ''}`}>{LABEL[p.availability]}</span>
                  {!!p.weeklyHours && <span className="badge">{p.weeklyHours} h / week</span>}
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
                {savedIds.canSave && !p.isOwnProfile && <AskButton professionalId={p.id} onError={setError} />}
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
                    {(p.pendingSpecializations ?? []).map((n) => <span key={n} className="badge" title="Suggested by the professional; not yet reviewed">{n} · Custom (under review)</span>)}
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
                <section className="card panel" id="verification-report"><h2>Verification report</h2>
                  <p className="small" style={{ marginTop: 0 }}>{TIER_MEANING[p.trust.tier]}</p>
                  <ul className="checklist">
                    {DIMENSIONS.map((d) => {
                      const v = DIMENSION_VALUE[p.trust.dimensions[d.key]] ?? { label: 'Not verified', good: false }
                      return <li key={d.key}><span>{d.label}</span><span className={`badge ${v.good ? 'green' : ''}`}>{v.label}</span></li>
                    })}
                  </ul>
                  {(p.verificationReport ?? []).length > 0 && <table className="data small" style={{ marginTop: 8 }}>
                    <thead><tr><th>Check</th><th>Verified</th><th>Valid until</th></tr></thead>
                    <tbody>{p.verificationReport!.map((r) => <tr key={r.check}>
                      <td>{r.check}</td>
                      <td>{r.status === 'EXPIRED' ? <span className="badge warn">Expired</span> : r.verifiedAt ? new Date(r.verifiedAt).toLocaleDateString() : '✓'}</td>
                      <td>{r.expiresAt ? new Date(r.expiresAt).toLocaleDateString() : '—'}</td></tr>)}</tbody></table>}
                  {(p.verificationInProgress ?? []).length > 0 && <p className="small" style={{ margin: '8px 0 0' }}>
                    Under review now: {p.verificationInProgress!.join(', ')}.</p>}
                  <p className="muted small" style={{ margin: '8px 0 0' }}>Checks are made by a verification provider or a compliance reviewer — never by AI.
                    Screening results are not shown publicly.</p>
                </section>
                {p.history && <section className="card panel"><h2>Engagement history</h2>
                  {p.history.newToPlatform && <p style={{ margin: '0 0 8px' }}><span className="badge">New to Zoikorum</span>
                    <span className="muted small"> · limited platform history</span></p>}
                  <ul className="checklist">
                    <li><span>Completed engagements</span><strong>{p.history.completedEngagements}</strong></li>
                    <li><span>On-time milestone delivery</span><strong>{p.history.onTimeRate === null ? '—' : `${p.history.onTimeRate}%`}</strong></li>
                    <li><span>Typical response to requests</span><strong>{p.history.medianResponseHours === null ? '—'
                      : p.history.medianResponseHours < 1 ? 'Under 1 hour' : `About ${Math.round(p.history.medianResponseHours)} h`}</strong></li>
                  </ul>
                  <p className="muted small" style={{ margin: '8px 0 0' }}>Measured on Zoikorum only. Reviews appear once verified engagements are rated.</p>
                </section>}
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
                      {p.credentials.map((c, i) => {
                        const eq = equivalency(c, buyerCountry, countryName)
                        return (
                          <li key={i}><span><strong>{c.name}</strong><br /><span className="muted small">{c.issuingBody}{c.jurisdiction && ` · ${c.jurisdiction}`}</span>
                            {eq.explanation && <><br /><span className="muted small" title={eq.explanation}>ⓘ {eq.explanation}</span></>}</span>
                            <span className="row" style={{ gap: 6 }}>{eq.recognisedHere && <span className="badge green">Recognised in your region</span>}
                              <span className={`badge ${c.status === 'VERIFIED' ? 'green' : ''}`}>{c.displayLabel}</span></span></li>
                        )
                      })}
                    </ul>
                  )}
                </section>
                <section className="card panel"><h2>Jurisdictions</h2>
                  <p className="small" style={{ margin: 0 }}>Serves: {p.servedJurisdictions.map(countryName).join(', ') || '—'}</p>
                  {p.licensedJurisdictions.length > 0 && (
                    <p className="small" style={{ margin: '6px 0 0' }}>Licensed in: {p.licensedJurisdictions.map((j) =>
                      `${countryName(j)} (${p.verifiedJurisdictions.includes(j) ? 'verified' : 'self-reported'})`).join(', ')}</p>
                  )}
                  {p.handlesRegulatedData && <p className="small" style={{ margin: '6px 0 0' }}><span className="badge">Handles regulated data</span>
                    <span className="muted"> (self-attested controls)</span></p>}
                </section>
              </aside>
            </div>
            {!p.isOwnProfile && <PublicReviews professionalId={p.id} />}
            {!p.isOwnProfile && <section className="card panel conversion-zone">
              <div><h2 style={{ margin: 0 }}>Ready to engage {p.displayName}?</h2>
                <p className="muted small" style={{ margin: '4px 0 0' }}>Send a structured request. No payment until you accept a proposal and sign the contract.</p></div>
              <div className="row">
                {savedIds.canSave ? <Link className="btn btn-primary" to={`/app/requests/new?pro=${p.id}`}>Request proposal</Link>
                  : !user && <Link className="btn btn-primary" to="/login">Sign in to request a proposal</Link>}
                {savedIds.canSave && savedIds.ids && <SaveButton id={p.id} saved={savedIds.ids.has(p.id)} onToggle={(pid) => { savedIds.toggle(pid).catch(setError) }} />}
                {user && <ReportButton subjectType="PROFESSIONAL" subjectId={p.id} what="this profile" />}
              </div>
            </section>}
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


/** Contact before a request: opens (or reopens) one enquiry conversation for the viewer's organisation. */
function AskButton({ professionalId, onError }: { professionalId: string; onError: (e: unknown) => void }) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  return <button className="btn btn-secondary" disabled={busy} onClick={async () => {
    setBusy(true)
    try {
      const org = (await orgApi.mine())[0]
      if (!org) throw new Error('Create or join an organisation first.')
      const thread = await messagingApi.inquire(org.id, professionalId)
      navigate(`/app/messages?thread=${thread.id}`)
    } catch (e) { onError(e) } finally { setBusy(false) }
  }}>Ask a question</button>
}
