import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { messagingApi } from '../api/messaging'
import { formatMoney, orgApi } from '../api/orgs'
import { growthApi, LABEL, RATE_UNIT_LABEL, proApi, type ProcurementKind, type PublicProfile } from '../api/professional'
import { DIMENSION_VALUE, DIMENSIONS } from '../api/verification'
import { useAuth } from '../auth/AuthContext'
import { ReportButton } from '../components/ReportButton'
import { Avatar } from '../components/dashboard'
import { ErrorAlert, Field, SiteFooter, SiteHeader, Loading, useDialog } from '../components/ui'
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
// At capacity is a neutral state (grey), not a warning: the professional is busy, not doing anything wrong.
const AVAILABILITY_CLASS: Record<string, string> = { NOW: 'green', TWO_WEEKS: 'green', ONE_MONTH: 'green', AT_CAPACITY: 'muted-badge' }

/** Where a signed-out visitor goes to act: sign in (or create an account), then straight back to the same request. */
// eslint-disable-next-line react-refresh/only-export-components
export function signInFor(path: string) {
  return { login: `/login?next=${encodeURIComponent(path)}`, join: `/join?type=BUYER&next=${encodeURIComponent(path)}` }
}

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
  const [procurement, setProcurement] = useState<ProcurementKind | null>(null)
  if (!p) {
    return <><SiteHeader /><main className="profile-wrap"><ErrorAlert error={error} />{!error && <Loading />}</main><SiteFooter /></>
  }
  const requestPath = `/app/requests/new?pro=${p.id}`
  const outside = signInFor(requestPath)
  const buyer = savedIds.canSave && !p.isOwnProfile
  const atCapacity = p.availability === 'AT_CAPACITY'
  const similar = `/professionals?${new URLSearchParams({ ...(primary ? { spec: primary.slug } : {}), availability: 'NOW' })}`
  const response = p.history?.medianResponseHours
  const snapshot: [string, string][] = [
    ['Trust Tier', `Tier ${p.trust.tier} · ${TIER_LABEL[p.trust.tier]}`],
    ['Availability', LABEL[p.availability] ?? p.availability],
    ['Based in', [p.city, countryName(p.country)].filter(Boolean).join(', ')],
    ['Experience', p.yearsExperienceBand ? `${p.yearsExperienceBand} years` : '—'],
    ['Engagements', p.engagementTypes.map((t) => LABEL[t]).join(', ') || '—'],
    ['Delivery', p.deliveryModes.map((t) => LABEL[t]).join(', ') || '—'],
    ['Languages', p.languages.join(', ') || '—'],
    ['Serves', p.servedJurisdictions.map(countryName).join(', ') || 'Anywhere'],
    ['Completed on Zoikorum', String(p.history?.completedEngagements ?? 0)],
    ['Typical response', response == null ? '—' : response < 1 ? 'Under 1 hour' : `About ${Math.round(response)} h`],
  ]
  return (
    <>
      <SiteHeader />
      <main className="profile-wrap">
        <nav className="breadcrumb small" aria-label="Breadcrumb">
          <Link to="/professionals">Find professionals</Link>
          {p.primaryCategory && <> › <Link to={`/categories/${p.primaryCategory}`}>{p.primaryCategoryName}</Link></>}
          {primary && <> › <Link to={p.primaryCategory ? `/categories/${p.primaryCategory}?spec=${primary.slug}` : `/professionals?spec=${primary.slug}`}>{primary.name}</Link></>}
          {' › '}<span>{p.displayName}</span>
        </nav>
        <ErrorAlert error={error} />
        {p.isOwnProfile && (
          <div className="alert alert-info">
            This is how buyers see your profile.{p.profileStatus && p.profileStatus !== 'PUBLISHED' ? ' It is not published yet, so only you can see it.' : ''}{' '}
            <Link to="/app/professional/profile">Edit profile</Link>
          </div>
        )}
        {p.underReview && (
          <div className="alert alert-warn" role="status"><strong>Profile under review.</strong> Zoikorum is reviewing this profile, so it appears
            less often in search and some details may change. {p.isOwnProfile ? 'You will have received a notice explaining why and what you can do.'
              : 'You can still read it; every request is checked as usual before an engagement is agreed.'}</div>
        )}
        {outOfArea && <div className="alert alert-warn" role="status">{p.displayName} does not list {countryName(buyerCountry ?? '')} among the places they serve. You can still ask, but an engagement cannot be agreed. <Link to={`/app/find?jurisdiction=${buyerCountry}`}>Show professionals who serve {countryName(buyerCountry ?? '')}</Link></div>}
        <section className="card panel profile-head">
          <div>
            <div className="name-row"><Avatar name={p.displayName} photoUrl={p.photoUrl} size={72} /><h1>{p.displayName}</h1></div>
            {p.headline && <p className="headline">{p.headline}</p>}
            {p.firm && <p className="small" style={{ margin: '0 0 6px' }}>Practises with <Link to={`/firms/${p.firm.id}`}><strong>{p.firm.name}</strong></Link>
              {p.firm.verified ? <span className="badge green" style={{ marginLeft: 8 }}>Firm verified</span> : null}</p>}
            <div className="badges" style={{ marginTop: 12 }}>
              <a href="#verification-report" className={`badge ${p.trust.tier === 'C' ? 'warn' : 'green'}`} title={TIER_MEANING[p.trust.tier]}
                aria-describedby="tier-meaning">Tier {p.trust.tier} · {TIER_LABEL[p.trust.tier]} ⓘ</a>
              <span id="tier-meaning" className="sr-only">{TIER_MEANING[p.trust.tier]}</span>
              {(p.verificationInProgress ?? []).length > 0 && <span className="badge" title={`Under review: ${p.verificationInProgress!.join(', ')}`}>
                Verification in progress</span>}
              <span className={`badge ${AVAILABILITY_CLASS[p.availability] ?? ''}`}>{LABEL[p.availability]}</span>
              {!!p.weeklyHours && <span className="badge">{p.weeklyHours} h / week</span>}
              {keyCredentials.map((c) => <span key={c.name} className="badge green">✓ {c.name}</span>)}
              {p.enterprise?.enterpriseReady && <span className="badge green">Enterprise Ready</span>}
            </div>
            {p.trust.updatedAt && <p className="muted small" style={{ margin: '8px 0 0' }}>Last verified {new Date(p.trust.updatedAt).toLocaleDateString()}</p>}
          </div>
        </section>

        <div className="profile-cols">
          <div>
            <section className="card panel" aria-labelledby="snapshot-h"><h2 id="snapshot-h">At a glance</h2>
              <dl className="snapshot-grid">{snapshot.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
            </section>
            {atCapacity && (
              <section className="card panel capacity-note" role="status">
                <h2 style={{ marginTop: 0 }}>At capacity right now</h2>
                <p className="small" style={{ marginTop: 0 }}>{p.displayName} has reached the number of engagements they take at once, or has paused new
                  work. It is not a mark against them: requests are paused so you are not left waiting.</p>
                {p.isOwnProfile ? <p className="small" style={{ margin: 0 }}>When you can take work again, <Link to="/app/professional/profile?step=engagement">update your availability</Link> and
                  buyers see it at once.</p>
                  : <p className="small" style={{ margin: 0 }}>{buyer ? 'Save them to your shortlist: saved professionals show their availability on your dashboard as soon as it changes. '
                    : 'Sign in and save them to see when they are available again. '}<Link to={similar}>See similar professionals available now</Link></p>}
              </section>
            )}
            {p.bio && (
              <section className="card panel"><h2>About</h2>
                {p.bio.split(/\n+/).map((para, i) => <p key={i}>{para}</p>)}
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
                {p.offerings.map((o) => {
                  const path = `${requestPath}&offering=${o.id}`
                  return (
                    <article key={o.id} className="service" id={`offering-${o.id}`}>
                      <div className="offering-top"><h3>{o.title}</h3><strong>{priceText(o)}</strong></div>
                      <div className="muted small">{o.specializationName} · {o.engagementTypes.map((t) => LABEL[t]).join(', ')}
                        {o.typicalDuration && ` · ${o.typicalDuration}`}</div>
                      {o.summary && <p style={{ marginTop: 8 }}>{o.summary}</p>}
                      {o.deliverables.length > 0 && <ul className="deliverables">{o.deliverables.map((d) => <li key={d}>{d}</li>)}</ul>}
                      {buyer && !atCapacity && <Link className="btn btn-secondary btn-sm" to={path}>Request this service</Link>}
                      {!user && !atCapacity && <Link className="btn btn-secondary btn-sm" to={signInFor(path).login}>Sign in to request this service</Link>}
                    </article>
                  )
                })}
              </section>
            )}
            <section className="card panel"><h2>Contracts &amp; payment protection</h2>
              <ul className="why" style={{ margin: 0 }}>
                <li>Every engagement runs under a signed contract with agreed scope and milestones.</li>
                <li>Payments are held in escrow and released only when you accept the work.</li>
                <li>If something goes wrong, a structured dispute process holds the funds while it is resolved.</li>
              </ul>
            </section>
            <PublicReviews professionalId={p.id} canReply={p.isOwnProfile} />
          </div>
          <aside>
            {!p.isOwnProfile && (
              <section className="card panel cta-stack" aria-label={`Engage ${p.displayName}`}>
                {atCapacity ? <p className="small" style={{ margin: 0 }}><span className="badge muted-badge">At capacity</span> Not taking new requests right now.</p>
                  : buyer ? <Link className="btn btn-primary btn-block" to={requestPath}>Request proposal</Link>
                    : !user ? <>
                      <Link className="btn btn-primary btn-block" to={outside.login}>Sign in to request a proposal</Link>
                      <Link className="btn btn-secondary btn-block" to={outside.join}>Create a buyer account</Link>
                    </> : <p className="muted small" style={{ margin: 0 }}>Requests are sent from a buyer or enterprise account.</p>}
                {buyer && <AskButton professionalId={p.id} onError={setError} />}
                {savedIds.canSave && savedIds.ids && <SaveButton id={p.id} saved={savedIds.ids.has(p.id)} onToggle={(pid) => { savedIds.toggle(pid).catch(setError) }} />}
                <button type="button" className="btn btn-ghost btn-block" onClick={() => setProcurement('PROCUREMENT_PACK')}>View enterprise engagement options</button>
                <button type="button" className="link-btn small" onClick={() => setProcurement('SECURITY_REVIEW')}>Request a security review</button>
                <p className="muted small" style={{ margin: 0 }}>No payment until you accept a proposal and sign the contract.</p>
                {user && <ReportButton subjectType="PROFESSIONAL" subjectId={p.id} what="this profile" />}
              </section>
            )}
            {p.enterprise && p.enterprise.signals.length > 0 && <section className="card panel"><h2>Enterprise signals</h2>
              {p.enterprise.enterpriseReady && <p style={{ margin: '0 0 8px' }}><span className="badge green">Enterprise Ready</span>
                <span className="muted small"> · reviewed by Zoikorum compliance</span></p>}
              <ul className="checklist small">{p.enterprise.signals.map((s) => <li key={s}><span>{s}</span><span className="badge green">✓</span></li>)}</ul>
            </section>}
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
            {p.history?.newToPlatform && <section className="card panel"><p style={{ margin: 0 }}><span className="badge">New to Zoikorum</span>
              <span className="muted small"> · limited platform history. On-time delivery appears after the first engagements.</span></p></section>}
            <section className="card panel"><h2>How they work</h2>
              <ul className="checklist">
                <li><span>Pricing</span><span>{p.pricingModels.map((t) => LABEL[t]).join(', ') || '—'}</span></li>
                {p.indicativeRate && <li><span>Indicative rate</span><span>{formatMoney(p.indicativeRate)} {RATE_UNIT_LABEL[p.rateUnit ?? ''] ?? ''}</span></li>}
                {p.history && <li><span>On-time milestone delivery</span><span>{p.history.onTimeRate === null ? '—' : `${p.history.onTimeRate}%`}</span></li>}
                {(p.onsiteRegions ?? []).length > 0 && <li><span>On-site in</span><span>{p.onsiteRegions!.join(', ')}</span></li>}
                {(p.industries ?? []).length > 0 && <li><span>Industries</span><span>{p.industries!.join(', ')}</span></li>}
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
        <p className="muted small disclosure">
          {p.displayName} is an independent professional. Zoikorum provides marketplace infrastructure, verification,
          contracting facilitation and payment protection; it does not employ professionals or provide regulated professional services.
        </p>
        {procurement && <ProcurementDialog kind={procurement} professionalId={p.id} name={p.displayName} signedIn={!!user}
          onClose={() => setProcurement(null)} />}
      </main>
      <SiteFooter />
    </>
  )
}

/** Procurement pack or security review request (public): name, organisation, email, message. Creates a lead the
    Zoikorum team answers by email; nothing is sent to the professional automatically. */
export function ProcurementDialog({ kind: initialKind, professionalId, name, signedIn, onClose }: {
  kind: ProcurementKind; professionalId?: string; name?: string; signedIn: boolean; onClose: () => void
}) {
  const dialog = useDialog(onClose)
  const [kind, setKind] = useState<ProcurementKind>(initialKind)
  const [f, setF] = useState({ name: '', organization: '', email: '', message: '', website: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [done, setDone] = useState<string | null>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  return (
    <div ref={dialog} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="proc-title" onClick={onClose}>
      <div className="card modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head"><h2 id="proc-title">Enterprise engagement options</h2><button className="icon-btn" aria-label="Close" onClick={onClose}>×</button></div>
        {done ? <>
          <div className="alert alert-success" role="status">Thank you. Request {done} has been received; the Zoikorum team replies by email within one business day.</div>
          <button className="btn btn-primary" onClick={onClose}>Close</button>
        </> : <form onSubmit={async (e) => {
          e.preventDefault(); setBusy(true); setError(null)
          try {
            const r = await growthApi.procurementRequest({ kind, professionalId: professionalId ?? null, ...f })
            setDone(r.reference)
          } catch (err) { setError(err) } finally { setBusy(false) }
        }}>
          <p className="small" style={{ marginTop: 0 }}>Enterprises engage{name ? ` ${name}` : ''} under their own procurement rules: minimum Trust Tier,
            required credentials, approvers, spend limits and contract clauses. {signedIn
              ? <>Your organisation's rules are under <Link to="/app/policies">Policies</Link>.</>
              : <>Set up your organisation through <Link to="/enterprise">enterprise access</Link>.</>}</p>
          <div className="role-grid" role="radiogroup" aria-label="What do you need?">
            {([['PROCUREMENT_PACK', 'Procurement pack', 'Verification report, insurance and contract templates for your vendor file.'],
              ['SECURITY_REVIEW', 'Security review', 'Answers to your security questionnaire and data-handling controls.']] as [ProcurementKind, string, string][]).map(([k, t, d]) => (
              <label key={k} className="role-option"><input type="radio" name="proc-kind" checked={kind === k} onChange={() => setKind(k)} />
                <span><strong>{t}</strong><br /><span className="muted small">{d}</span></span></label>
            ))}
          </div>
          <ErrorAlert error={error} />
          <div className="row">
            <Field label="Your name" id="proc-name"><input id="proc-name" className="input" required minLength={2} maxLength={200} value={f.name} onChange={set('name')} autoComplete="name" /></Field>
            <Field label="Organisation" id="proc-org"><input id="proc-org" className="input" required minLength={2} maxLength={200} value={f.organization} onChange={set('organization')} autoComplete="organization" /></Field>
          </div>
          <Field label="Work email" id="proc-email"><input id="proc-email" className="input" type="email" required value={f.email} onChange={set('email')} autoComplete="email" /></Field>
          <Field label="Message (optional)" id="proc-msg"><textarea id="proc-msg" className="input" rows={3} maxLength={2000} value={f.message} onChange={set('message')} /></Field>
          <div className="hp-field" aria-hidden="true"><label htmlFor="proc-web">Website</label>
            <input id="proc-web" tabIndex={-1} autoComplete="off" value={f.website} onChange={set('website')} /></div>
          <p className="muted small">We use these details only to answer this request. The professional is not sent your contact details automatically.</p>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Sending…' : 'Send request'}</button>
        </form>}
      </div>
    </div>
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
