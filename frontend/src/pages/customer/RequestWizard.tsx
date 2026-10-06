import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { orgApi, type Organization } from '../../api/orgs'
import { CURRENCIES, LABEL, proApi, toMinor, type PublicProfile } from '../../api/professional'
import { budgetText, DURATION_LABEL, DURATIONS, proposalApi, type Attachment, type Duration, type EngagementType, type ProposalRequest } from '../../api/proposals'
import { sha256OfFile } from '../../api/verification'
import { Avatar, Icon } from '../../components/dashboard'
import { PortalHeader, TierBadge } from '../../components/portal'
import { ErrorAlert, Field } from '../../components/ui'

/* Request Proposal flow (RFP wireframe s.3–10): context → scope → commercial → governance → review & send.
   One requirement can go to up to 3 chosen professionals; each answers with their own proposal. */

const STEPS = ['Engagement context', 'Scope', 'Commercial', 'Protections', 'Review & send']
const CONTEXTS: [string, string][] = [['STARTUP', 'Startup'], ['SME', 'SME'], ['MID_MARKET', 'Mid-market'], ['ENTERPRISE', 'Enterprise'], ['INDIVIDUAL', 'Individual']]
const ALLOWED = '.pdf,.docx,.xlsx,.png,.jpg,.jpeg'
const today = () => new Date().toISOString().slice(0, 10)

interface Form {
  service: string; engagementType: EngagementType; businessContext: string; objective: string; details: string
  desiredStartDate: string; estimatedDuration: Duration; deliveryMode: 'REMOTE' | 'ONSITE' | 'HYBRID'; location: string
  budgetOn: boolean; budgetMin: string; budgetMax: string; currency: string; ndaRequired: boolean; attachments: Attachment[]
  acknowledged: boolean
}

export default function RequestWizard() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const ids = useMemo(() => params.getAll('pro').slice(0, 3), [params])
  const offeringId = params.get('offering')
  const [pros, setPros] = useState<PublicProfile[]>([])
  const [org, setOrg] = useState<Organization | null>(null)
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [sent, setSent] = useState<ProposalRequest[] | null>(null)
  const [f, setF] = useState<Form>({
    service: '', engagementType: 'PROJECT', businessContext: '', objective: '', details: '', desiredStartDate: '',
    estimatedDuration: 'THREE_SIX_WEEKS', deliveryMode: 'REMOTE', location: '', budgetOn: false, budgetMin: '', budgetMax: '',
    currency: 'USD', ndaRequired: false, attachments: [], acknowledged: false,
  })
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }))

  useEffect(() => {
    let live = true
    Promise.all(ids.map((id) => proApi.publicProfile(id))).then((list) => {
      if (!live) return
      setPros(list)
      const offering = offeringId ? list[0]?.offerings.find((o) => o.id === offeringId) : undefined
      const first = list[0]
      setF((x) => ({
        ...x,
        service: x.service || offering?.title || first?.specializations[0]?.name || first?.headline || '',
        engagementType: (offering?.engagementTypes[0] ?? first?.engagementTypes[0] ?? x.engagementType) as EngagementType,
        currency: first?.indicativeRate?.currency ?? x.currency,
      }))
    }).catch(setError)
    orgApi.mine().then((orgs) => { if (live) setOrg(orgs.find((o) => o.myRoles.includes('REQUESTER')) ?? null) }).catch(setError)
    return () => { live = false }
  }, [ids, offeringId])

  if (ids.length === 0) {
    return (
      <>
        <PortalHeader eyebrow="Requests" title="Request a proposal" subtitle="Choose who you want to hear from first." />
        <section className="card panel"><p style={{ margin: 0 }}>Requests go to professionals you choose — up to three at once so you can
          compare their proposals. <Link to="/app/find">Find professionals</Link> or pick from your <Link to="/app/saved">saved list</Link>, then
          use <strong>Request proposal</strong>.</p></section>
      </>
    )
  }

  const problems = [
    !f.service.trim() || f.objective.trim().length < 5 ? 0 : -1,
    !f.desiredStartDate || f.desiredStartDate < today() || (f.deliveryMode !== 'REMOTE' && !f.location.trim()) ? 1 : -1,
    f.budgetOn && (!f.budgetMax || (f.budgetMin !== '' && Number(f.budgetMin) > Number(f.budgetMax))) ? 2 : -1,
  ].filter((s) => s >= 0)
  const canNext = !problems.includes(step) && (step !== 3 || f.acknowledged)

  async function addFiles(files: FileList | null) {
    if (!files) return
    const room = 3 - f.attachments.length
    const picked = Array.from(files).slice(0, room)
    const hashed = await Promise.all(picked.map(async (file) => ({ name: file.name, size: file.size, sha256: await sha256OfFile(file) })))
    set('attachments', [...f.attachments, ...hashed])
  }

  async function submit(draft: boolean) {
    if (!org) return
    setBusy(true)
    setError(null)
    try {
      const result = await proposalApi.createRequests({
        organizationId: org.id, professionalIds: ids, offeringId: ids.length === 1 ? offeringId : null, service: f.service.trim(),
        engagementType: f.engagementType, businessContext: f.businessContext || null, objective: f.objective.trim(), details: f.details.trim(),
        desiredStartDate: f.desiredStartDate, estimatedDuration: f.estimatedDuration, deliveryMode: f.deliveryMode,
        location: f.deliveryMode === 'REMOTE' ? null : f.location.trim(),
        budget: f.budgetOn ? { minMinor: f.budgetMin ? toMinor(f.budgetMin) : null, maxMinor: toMinor(f.budgetMax), currency: f.currency } : null,
        ndaRequired: f.ndaRequired, attachments: f.attachments, acknowledged: f.acknowledged, draft,
      })
      if (draft) navigate(`/app/requests/${result[0].id}`)
      else setSent(result)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <section className="card panel confirm-state">
        <span className="kpi-icon green big"><Icon name="check" /></span>
        <h1>Your proposal request has been sent.</h1>
        <ul className="assurance compact">
          <li><Icon name="check" /><span>{sent.length === 1 ? sent[0].professional.displayName : `${sent.length} professionals`} notified</span></li>
          <li><Icon name="check" /><span>You'll see each proposal on the request page as it arrives</span></li>
          <li><Icon name="check" /><span>No payment required yet</span></li>
        </ul>
        <div className="row" style={{ justifyContent: 'center' }}>
          <Link className="btn btn-primary" to={`/app/requests/${sent[0].id}`}>Track request</Link>
          <Link className="btn btn-secondary" to="/app/saved">Request another proposal</Link>
          <Link className="btn btn-secondary" to="/app/find">Browse similar professionals</Link>
        </div>
      </section>
    )
  }

  const review = (title: string, at: number, body: ReactNode) => (
    <div className="review-block"><div className="panel-head"><h3>{title}</h3>
      <button className="btn btn-ghost btn-sm" onClick={() => setStep(at)}>Edit</button></div>{body}</div>
  )

  return (
    <>
      <PortalHeader eyebrow="Requests" title="Request a proposal" subtitle="A structured request: professionals reply with scope, milestones and price — no payment until you accept and sign." />
      <div className="governance-strip"><span><Icon name="shield" /> Verified identity</span><span><Icon name="contract" /> Contract-ready</span>
        <span><Icon name="lock" /> Payment protection</span><span><Icon name="clock" /> Audit record</span></div>
      <ol className="wizard-steps">{STEPS.map((s, i) => (
        <li key={s} className={i === step ? 'active' : i < step ? 'done' : ''}>
          <button disabled={i > step && problems.some((p) => p < i)} onClick={() => setStep(i)}><span className="n">{i < step ? '✓' : i + 1}</span>{s}</button>
        </li>))}</ol>
      {!org && <div className="alert alert-error" role="alert">You need the Requester role in an organisation to send requests. Ask your Org Admin.</div>}
      <ErrorAlert error={error} />

      <div className="home-grid wide">
        <section className="card panel wizard-body">
          {step === 0 && <>
            <h2>What do you need?</h2>
            <Field label="Service needed" id="w-service"><input id="w-service" className="input" value={f.service} maxLength={200} onChange={(e) => set('service', e.target.value)} /></Field>
            <div className="field"><span className="label">Engagement type</span>
              <div className="choice-grid">{(['ADVISORY', 'PROJECT', 'RETAINER', 'FRACTIONAL'] as const).map((t) => (
                <label key={t} className={`choice ${f.engagementType === t ? 'on' : ''}`}><input type="radio" name="et" checked={f.engagementType === t} onChange={() => set('engagementType', t)} />
                  <strong>{LABEL[t]}</strong></label>))}</div></div>
            <Field label="Business context (optional)" id="w-ctx"><select id="w-ctx" className="input" value={f.businessContext} onChange={(e) => set('businessContext', e.target.value)}>
              <option value="">Use my organisation's</option>{CONTEXTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
            <Field label="In one sentence, what outcome are you looking to achieve?" id="w-obj" hint={`${f.objective.length}/300 · Try: “Need help preparing audited financials for year-end close.”`}>
              <textarea id="w-obj" className="input" rows={2} maxLength={300} value={f.objective} onChange={(e) => set('objective', e.target.value)} /></Field>
          </>}

          {step === 1 && <>
            <h2>Scope and timing</h2>
            <Field label="Details" id="w-details" hint={`${f.details.length}/1200 · What does “done” look like? How will success be measured? What will you provide?`}>
              <textarea id="w-details" className="input" rows={6} maxLength={1200} value={f.details} onChange={(e) => set('details', e.target.value)} /></Field>
            <div className="row">
              <Field label="Desired start date" id="w-start"><input id="w-start" type="date" className="input" min={today()} value={f.desiredStartDate} onChange={(e) => set('desiredStartDate', e.target.value)} /></Field>
              <Field label="Estimated duration" id="w-dur"><select id="w-dur" className="input" value={f.estimatedDuration} onChange={(e) => set('estimatedDuration', e.target.value as Duration)}>
                {DURATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
            </div>
            <div className="row">
              <Field label="Delivery" id="w-mode"><select id="w-mode" className="input" value={f.deliveryMode} onChange={(e) => set('deliveryMode', e.target.value as Form['deliveryMode'])}>
                <option value="REMOTE">Remote</option><option value="ONSITE">On-site</option><option value="HYBRID">Hybrid</option></select></Field>
              {f.deliveryMode !== 'REMOTE' && <Field label="Location" id="w-loc"><input id="w-loc" className="input" value={f.location} maxLength={200} onChange={(e) => set('location', e.target.value)} placeholder="City, country" /></Field>}
            </div>
            <div className="field"><span className="label">Attachments (optional, up to 3)</span>
              {f.attachments.map((a) => <div key={a.sha256} className="file-row"><Icon name="request" /><span>{a.name}</span>
                <button className="btn btn-ghost btn-sm" onClick={() => set('attachments', f.attachments.filter((x) => x !== a))}>Remove</button></div>)}
              {f.attachments.length < 3 && <input type="file" accept={ALLOWED} multiple onChange={(e) => addFiles(e.target.files).catch(setError)} />}
              <p className="muted small" style={{ margin: '4px 0 0' }}>PDF, DOCX, XLSX, PNG or JPG. Each file is fingerprinted in your browser; secure upload arrives with document storage.</p></div>
          </>}

          {step === 2 && <>
            <h2>Commercial preferences</h2>
            <label className="checkbox"><input type="checkbox" checked={f.budgetOn} onChange={(e) => set('budgetOn', e.target.checked)} /><span>Share a budget range (optional — helps professionals propose accurately)</span></label>
            {f.budgetOn && <div className="row">
              <Field label="Currency" id="w-cur"><select id="w-cur" className="input" value={f.currency} onChange={(e) => set('currency', e.target.value)}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
              <Field label="Minimum (optional)" id="w-min"><input id="w-min" className="input" inputMode="decimal" value={f.budgetMin} onChange={(e) => set('budgetMin', e.target.value.replace(/[^0-9.]/g, ''))} /></Field>
              <Field label="Maximum" id="w-max"><input id="w-max" className="input" inputMode="decimal" value={f.budgetMax} onChange={(e) => set('budgetMax', e.target.value.replace(/[^0-9.]/g, ''))} /></Field>
            </div>}
            <p className="muted small">This does not lock pricing. Each professional proposes their own price and milestones.</p>
            <label className="checkbox"><input type="checkbox" checked={f.ndaRequired} onChange={(e) => set('ndaRequired', e.target.checked)} />
              <span><strong>NDA required before proposal</strong><br /><span className="muted small">Professionals see your objective, details and files only after accepting the NDA.</span></span></label>
          </>}

          {step === 3 && <>
            <h2>Your protections</h2>
            <ul className="assurance">{['Written agreement generated by the platform', 'Defined scope and milestones', 'Payment protection options',
              'Dispute resolution access', 'Audit-grade engagement records'].map((t) => <li key={t}><Icon name="check" /><span>{t}</span></li>)}</ul>
            <label className="checkbox"><input type="checkbox" checked={f.acknowledged} onChange={(e) => set('acknowledged', e.target.checked)} />
              <span>I understand Zoikorum facilitates the engagement but does not provide professional services.</span></label>
          </>}

          {step === 4 && <>
            <h2>Review and send</h2>
            {review('Professionals', 0, <p className="small">{pros.map((p) => p.displayName).join(', ')}</p>)}
            {review('Service & objective', 0, <p className="small"><strong>{f.service}</strong> · {LABEL[f.engagementType]}<br />{f.objective}</p>)}
            {review('Scope & timeline', 1, <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{f.details || <span className="muted">No extra details</span>}<br />
              Start {f.desiredStartDate} · {DURATION_LABEL[f.estimatedDuration]} · {LABEL[f.deliveryMode]}{f.location ? ` (${f.location})` : ''}
              {f.attachments.length > 0 && <><br />{f.attachments.length} attachment{f.attachments.length > 1 ? 's' : ''}</>}</p>)}
            {review('Commercial preferences', 2, <p className="small">{f.budgetOn && f.budgetMax ? budgetText({ minMinor: f.budgetMin ? toMinor(f.budgetMin) : null, maxMinor: toMinor(f.budgetMax), currency: f.currency }) : 'Open to proposal'}
              {f.ndaRequired && ' · NDA required'}</p>)}
            {review('Protections', 3, <p className="small">{f.acknowledged ? 'Acknowledged' : <span className="danger-text">Please confirm the acknowledgement</span>}</p>)}
          </>}

          <div className="wizard-nav">
            {step > 0 ? <button className="btn btn-secondary" onClick={() => setStep(step - 1)}>Back</button> : <Link className="btn btn-ghost" to="/app/requests">Cancel</Link>}
            <div style={{ flex: 1 }} />
            {step >= 1 && <button className="btn btn-ghost" disabled={busy || !org || problems.includes(0) || problems.includes(1)} onClick={() => submit(true)}>Save draft</button>}
            {step < 4 ? <button className="btn btn-primary btn-lg" disabled={!canNext} onClick={() => setStep(step + 1)}>Continue</button>
              : <button className="btn btn-primary btn-lg" disabled={busy || !org || problems.length > 0 || !f.acknowledged} onClick={() => submit(false)}>
                {busy ? 'Sending…' : `Send proposal request${ids.length > 1 ? 's' : ''}`}</button>}
          </div>
        </section>

        <aside>
          <section className="card panel">
            <div className="panel-head"><h2>Engagement summary</h2></div>
            <ul className="pro-list">{pros.map((p) => (
              <li key={p.id}><Avatar name={p.displayName} photoUrl={p.photoUrl} size={32} />
                <span><strong>{p.displayName}</strong><br /><span className="muted small">{p.headline}</span></span><TierBadge tier={p.trust.tier} /></li>))}</ul>
            {pros.some((p) => p.trust.tier === 'C') && <p className="tip" style={{ marginTop: 12 }}><Icon name="help" /><span>Tier C professionals can read your request but must
              verify their identity (Tier B) before they can send a proposal.</span></p>}
            <dl className="facts" style={{ marginTop: 14 }}>
              <dt>Service</dt><dd>{f.service || '—'}</dd>
              <dt>Type</dt><dd>{LABEL[f.engagementType]}</dd>
              <dt>Start</dt><dd>{f.desiredStartDate || '—'}</dd>
              <dt>Budget</dt><dd>{f.budgetOn && f.budgetMax ? budgetText({ minMinor: f.budgetMin ? toMinor(f.budgetMin) : null, maxMinor: toMinor(f.budgetMax), currency: f.currency }) : 'Open'}</dd>
            </dl>
          </section>
          <section className="card panel"><div className="panel-head"><h2>What happens next</h2></div>
            <ol className="side-steps">{[['They reply', 'A structured proposal, or a decline with a reason.'], ['You compare', 'Scope, milestones, price and timeline side by side.'],
              ['You accept one', 'A contract is generated from the accepted proposal.']].map(([t, d], i) => (
              <li key={t}><span className="n">{i + 1}</span><span><strong>{t}</strong><br /><span className="muted small">{d}</span></span></li>))}</ol></section>
        </aside>
      </div>
    </>
  )
}
