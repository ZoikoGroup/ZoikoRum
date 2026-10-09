import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  CASE_STATUS, DIMENSION_VALUE, DIMENSIONS, evidenceFileUrl, HOSTED_NOTE, PARTNER_NAME, trustApi, verificationApi,
  type AppealQueueItem, type EvidenceType, type QueueItem, type SelfServiceType, type SubjectType, type Trust, type VerificationCase,
} from '../api/verification'
import { toUpload } from '../api/files'
import { FileLink } from '../components/FileLink'
import { HostedVerification } from '../components/HostedVerification'
import { ErrorAlert, Field, useStepUp } from '../components/ui'
import { useMyFirm } from './FirmPages'
import { COUNTRIES } from './Join'
import { countryName, useMyProfile } from './ProfessionalPages'

const OPEN = ['PENDING', 'IN_REVIEW', 'NEEDS_INFO']
const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—')

const EVIDENCE_FOR: Record<string, { type: EvidenceType; label: string }> = {
  IDENTITY: { type: 'ID_DOCUMENT', label: 'Passport, national ID card or driving licence' },
  CREDENTIAL: { type: 'LICENSE', label: 'Licence or certificate' },
  JURISDICTION: { type: 'LICENSE', label: 'Licence or registration for this jurisdiction' },
  INSURANCE: { type: 'INSURANCE_POLICY', label: 'Insurance policy schedule' },
  FIRM_REGISTRATION: { type: 'REGISTRATION_DOCUMENT', label: 'Certificate of incorporation or registry extract' },
}

const START_INFO: Record<SelfServiceType, { title: string; desc: string }> = {
  IDENTITY: { title: 'Verify your identity (start here)', desc: 'Required for everyone: passport, national ID (e.g. Aadhaar) or driving licence. Gives Tier B. Reviewed within about 24 hours.' },
  JURISDICTION: { title: 'Verify a professional licence for a country', desc: 'Only if you hold a licence to practise (e.g. CA, CPA, bar admission). Upload the licence, not your ID. Not needed for most technology or advisory work.' },
  INSURANCE: { title: 'Verify professional indemnity insurance', desc: 'Only for regulated work (legal, audit, tax filing). Upload the policy schedule.' },
  FIRM_REGISTRATION: { title: 'Verify the firm registration', desc: 'Confirms the firm is a registered legal entity.' },
}

export function CaseStatusBadge({ status }: { status: string }) {
  const s = CASE_STATUS[status] ?? { label: status, cls: '' }
  return <span className={`badge ${s.cls}`}>{s.label}</span>
}

/** Tier, the five verification areas, and why. */
export function TrustSummary({ trust }: { trust: Trust }) {
  return (
    <section className="card panel">
      <div className="trust-head">
        <span className={`tier tier-${trust.tier}`}>Tier {trust.tier}</span>
        <div>
          <h2 style={{ margin: 0 }}>{trust.tierLabel}</h2>
          {trust.score !== null && <p className="muted small" style={{ margin: 0 }}>Trust score {trust.score} / 100</p>}
        </div>
      </div>
      <ul className="checklist">
        {DIMENSIONS.map((d) => {
          const v = DIMENSION_VALUE[trust.dimensions[d.key]] ?? { label: 'Not verified', good: false }
          return <li key={d.key}><span>{d.label}</span><span className={`badge ${v.good ? 'green' : ''}`}>{v.label}</span></li>
        })}
      </ul>
      {trust.explanation.length > 0 && (
        <ul className="why">{trust.explanation.map((e) => <li key={e}>{e}</li>)}</ul>
      )}
      <h3>What each tier unlocks</h3>
      <table className="data">
        <thead><tr><th>Tier</th><th>Needs</th><th>Unlocks</th></tr></thead>
        <tbody>
          <tr><td><strong>C</strong> · Discovery</td><td>A published profile</td><td>Visible in search; no contracts or protected payments</td></tr>
          <tr><td><strong>B</strong> · Verified Identity</td><td>Identity verified, screening clear</td><td>Respond to requests; limited-risk engagements (per buyer policy)</td></tr>
          <tr><td><strong>A</strong> · Fully Verified</td><td>B + required credentials, a verified jurisdiction, insurance where required</td><td>Enterprise and regulated engagements</td></tr>
        </tbody>
      </table>
    </section>
  )
}

function EvidenceUpload({ c, onDone }: { c: VerificationCase; onDone: (c: VerificationCase) => void }) {
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const hint = EVIDENCE_FOR[c.verificationType] ?? { type: 'OTHER' as EvidenceType, label: 'Supporting document' }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const items = await Promise.all(files.map((f) => toUpload(f, ['pdf', 'jpg', 'jpeg', 'png'])))
      onDone(await verificationApi.addEvidence(c.id, hint.type, items))
      setFiles([])
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="evidence-form">
      <ErrorAlert error={error} />
      <Field label={hint.label} id={`ev-${c.id}`} hint="PDF, JPG or PNG. Up to 5 files, 10 MB each. Only you and the compliance reviewer can open them.">
        <input id={`ev-${c.id}`} type="file" multiple accept=".pdf,.jpg,.jpeg,.png"
          onChange={(e) => setFiles([...(e.target.files ?? [])].slice(0, 5))} />
      </Field>
      <button className="btn btn-secondary btn-sm" disabled={busy || files.length === 0}>{busy ? 'Sending…' : 'Submit for review'}</button>
    </form>
  )
}

function CaseCard({ c, onChange, hostedOn }: { c: VerificationCase; onChange: (c: VerificationCase) => void; hostedOn: boolean }) {
  // Identity checks run in the partner's hosted flow when one is switched on; uploading stays available.
  const hosted = hostedOn && c.verificationType === 'IDENTITY' && c.isMine && c.evidence.length === 0 && OPEN.includes(c.status)
  const [uploadInstead, setUploadInstead] = useState(false)
  const needsUpload = c.isMine && OPEN.includes(c.status) && c.evidence.length === 0 && c.verificationType !== 'RESTRICTIONS'
    && !(hosted && c.status === 'IN_REVIEW')
  return (
    <article className={`case ${needsUpload && c.verificationType === 'IDENTITY' ? 'case-highlight' : ''}`}>
      {needsUpload && <div className="small" style={{ marginBottom: 6 }}><span className="badge warn">Action needed</span>{' '}
        {hosted ? <>Verify your identity online, below</>
          : <>Upload: <strong>{(EVIDENCE_FOR[c.verificationType] ?? { label: 'a supporting document' }).label}</strong></>}</div>}
      <div className="offering-top">
        <div>
          <h3>{c.label}</h3>
          <div className="muted small">
            Started {fmtDate(c.createdAt)}
            {OPEN.includes(c.status) && c.estimatedCompletion && ` · usually done by ${fmtDate(c.estimatedCompletion)}`}
            {c.status === 'VERIFIED' && c.expiresAt && ` · valid until ${fmtDate(c.expiresAt)}`}
          </div>
        </div>
        <CaseStatusBadge status={c.status} />
      </div>
      {c.publicReason && ['NEEDS_INFO', 'FAILED', 'REVOKED'].includes(c.status) && (
        <div className="alert alert-warn" style={{ marginTop: 10 }}>{c.publicReason}</div>
      )}
      {c.evidence.length > 0 && (
        <ul className="deliverables">{c.evidence.map((e) => <li key={e.id}><FileLink file={{ name: e.fileName, hasFile: e.hasFile }} url={evidenceFileUrl(e.id)} /> <span className="muted small">· {fmtDate(e.uploadedAt)}</span></li>)}</ul>
      )}
      {hosted && <HostedVerification c={c} onChange={onChange} />}
      {hosted && !uploadInstead && <button type="button" className="text-btn small"
        onClick={() => setUploadInstead(true)}>Can't use a camera? Upload your document for a person to review instead</button>}
      {c.isMine && OPEN.includes(c.status) && c.verificationType !== 'RESTRICTIONS' && (!hosted || uploadInstead) && <EvidenceUpload c={c} onDone={onChange} />}
      {c.appeal && <div className={`alert ${c.appeal.status === 'OVERTURNED' ? 'alert-success' : 'alert-info'}`} style={{ marginTop: 10 }}>
        <strong>Appeal {c.appeal.status === 'OPEN' ? 'under review' : c.appeal.status === 'OVERTURNED' ? 'successful' : 'not upheld'}</strong>
        {c.appeal.status === 'OPEN' ? ' — an independent reviewer will decide. You can add new documents below.' : c.appeal.decisionNote ? `: ${c.appeal.decisionNote}` : ''}
      </div>}
      {c.isMine && c.appeal?.status === 'OPEN' && c.verificationType !== 'RESTRICTIONS' && <EvidenceUpload c={c} onDone={onChange} />}
      {c.isMine && c.appealDeadline && !c.appeal && <AppealForm c={c} onDone={onChange} />}
    </article>
  )
}

/** Appeal a failed or revoked check (Governance s.11): once, before the deadline, decided by an independent reviewer. */
function AppealForm({ c, onDone }: { c: VerificationCase; onDone: (c: VerificationCase) => void }) {
  const [open, setOpen] = useState(false)
  const [statement, setStatement] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  if (!open) return <p className="small" style={{ marginTop: 8 }}>Think this decision is wrong?{' '}
    <button className="link-btn small" style={{ display: 'inline', padding: 0 }} onClick={() => setOpen(true)}>Appeal it</button>{' '}
    <span className="muted">(by {fmtDate(c.appealDeadline)})</span></p>
  return (
    <form className="evidence-form" onSubmit={async (e) => {
      e.preventDefault(); setBusy(true); setError(null)
      try { onDone(await verificationApi.appeal(c.id, statement.trim())) } catch (err) { setError(err) } finally { setBusy(false) }
    }}>
      <ErrorAlert error={error} />
      <Field label="Why is the decision wrong?" id={`ap-${c.id}`} hint="Be specific. After sending you can add new documents. A different reviewer decides, once.">
        <textarea id={`ap-${c.id}`} className="input" rows={3} maxLength={2000} value={statement} onChange={(e) => setStatement(e.target.value)} />
      </Field>
      <div className="row"><button className="btn btn-primary btn-sm" disabled={busy || statement.trim().length < 20}>{busy ? 'Sending…' : 'Send appeal'}</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>Cancel</button></div>
    </form>
  )
}

/** Compliance officers: open appeals. The officer who made the original decision cannot decide its appeal. */
function AppealsPanel({ onDecided }: { onDecided: (msg: string) => void }) {
  const [items, setItems] = useState<AppealQueueItem[]>([])
  const [selected, setSelected] = useState<{ appeal: AppealQueueItem; c: VerificationCase } | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => verificationApi.appeals().then(setItems).catch(setError), [])
  useEffect(() => { load() }, [load])
  const decide = (outcome: 'UPHELD' | 'OVERTURNED') => selected && run(async () => {
    await verificationApi.decideAppeal(selected.appeal.id, { outcome, note: note.trim() })
    onDecided(`Appeal ${outcome === 'OVERTURNED' ? 'granted: the check is now verified' : 'not upheld'} for ${selected.appeal.caseLabel}.`)
    setSelected(null); setNote(''); await load()
  })
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Appeals</h2><span className="muted small">{items.length} open</span></div>
      <ErrorAlert error={error} />
      {modal}
      {selected && <div className="evidence-form">
        <strong>{selected.appeal.caseLabel}</strong> · {selected.appeal.subjectName}
        <p className="small"><span className="muted">Original reason:</span> {selected.appeal.originalReason ?? '—'}</p>
        <p className="small"><span className="muted">Appeal:</span> {selected.appeal.statement}</p>
        <ul className="deliverables">{selected.c.evidence.map((e) => <li key={e.id}><FileLink file={{ name: e.fileName, hasFile: e.hasFile }} url={evidenceFileUrl(e.id)} /> <span className="muted small">· {fmtDate(e.uploadedAt)}</span></li>)}</ul>
        <Field label="Decision note (shown to the professional)" id="appeal-note">
          <textarea id="appeal-note" className="input" rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <div className="row">
          <button className="btn btn-primary btn-sm" disabled={note.trim().length < 10} onClick={() => decide('OVERTURNED')}>Overturn: verify</button>
          <button className="btn btn-secondary btn-sm" disabled={note.trim().length < 10} onClick={() => decide('UPHELD')}>Uphold the decision</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>Close</button></div>
      </div>}
      {items.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No open appeals.</p> : (
        <table className="data"><thead><tr><th>Check</th><th>Subject</th><th>Filed</th><th>Evidence</th><th /></tr></thead>
          <tbody>{items.map((a) => <tr key={a.id}><td><strong>{a.caseLabel}</strong><div className="muted small clamp">{a.statement}</div></td>
            <td>{a.subjectName ?? '—'}</td><td className="small">{fmtDate(a.filedAt)}</td><td>{a.evidenceCount}</td>
            <td style={{ textAlign: 'right' }}>{a.canDecide
              ? <button className="btn btn-secondary btn-sm" onClick={() => verificationApi.get(a.caseId).then((c) => setSelected({ appeal: a, c })).catch(setError)}>Review</button>
              : <span className="muted small" title="You made the original decision">Another reviewer decides</span>}</td></tr>)}</tbody></table>
      )}
    </section>
  )
}

/** Compliance officers: recently verified checks, so a mistaken or outdated verification can be revoked (with a reason
    the professional sees; the trust tier updates). */
function VerifiedPanel({ onRevoked }: { onRevoked: (msg: string) => void }) {
  const [items, setItems] = useState<QueueItem[]>([])
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState<QueueItem | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => verificationApi.verified().then((p) => setItems(p.items)).catch(setError), [])
  useEffect(() => { if (open) load() }, [open, load])
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Verified checks</h2>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show, to correct a mistake'}</button></div>
      <ErrorAlert error={error} />
      {modal}
      {open && (items.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No verified checks.</p> : <>
        {target && <div className="evidence-form">
          <strong>Revoke “{target.label}” for {target.subjectName}?</strong>
          <p className="muted small">The check becomes “Revoked”, the professional sees your reason (and can appeal), and their trust tier updates.</p>
          <input className="input" placeholder="Reason shown to the professional, e.g. Verified by mistake: this is an ID, not a licence" maxLength={500}
            value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn-primary btn-sm" disabled={reason.trim().length < 5} onClick={() => run(async () => {
              await verificationApi.revoke(target.id, 'REVOKED_BY_REVIEWER', reason.trim())
              onRevoked(`Revoked: ${target.label} for ${target.subjectName}.`); setTarget(null); setReason(''); await load()
            })}>Revoke</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setTarget(null)}>Cancel</button></div>
        </div>}
        <table className="data"><thead><tr><th>Check</th><th>Subject</th><th>Verified</th><th /></tr></thead>
          <tbody>{items.map((q) => <tr key={q.id}><td><strong>{q.label}</strong></td><td>{q.subjectName ?? '—'}</td>
            <td><CaseStatusBadge status={q.status} /></td>
            <td style={{ textAlign: 'right' }}><button className="btn btn-ghost btn-sm" onClick={() => { setTarget(q); setReason('') }}>Revoke…</button></td></tr>)}</tbody></table>
      </>)}
    </section>
  )
}

/** All checks for a subject, plus buttons to start the self-service ones. */
function ChecksPanel({ subjectType, subjectId, allowed, onChanged }: {
  subjectType: SubjectType
  subjectId: string
  allowed: SelfServiceType[]
  onChanged?: () => void
}) {
  const [cases, setCases] = useState<VerificationCase[]>([])
  const [jurisdiction, setJurisdiction] = useState('US')
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => verificationApi.forSubject(subjectType, subjectId).then(setCases).catch(setError), [subjectType, subjectId])
  const [params, setParams] = useSearchParams()
  const returnedFrom = params.get('verification')  // the identity partner sends the person back here with ?verification=<case id>
  const [hostedOn, setHostedOn] = useState(false)
  useEffect(() => { verificationApi.configuration().then((cfg) => setHostedOn(cfg.hostedIdentity && cfg.configured)).catch(() => {}) }, [])
  const changed = useRef(onChanged)
  useEffect(() => { changed.current = onChanged })
  useEffect(() => {
    if (!returnedFrom) {
      load()
      return
    }
    setParams({}, { replace: true })
    verificationApi.hostedRefresh(returnedFrom).catch(setError).finally(() => { load(); changed.current?.() })
  }, [load, returnedFrom, setParams])

  async function start(type: SelfServiceType) {
    setError(null)
    try {
      await verificationApi.start({ verificationType: type, subjectType, subjectId, ...(type === 'JURISDICTION' ? { jurisdiction } : {}) })
      await load()
      onChanged?.()
    } catch (err) {
      setError(err)
    }
  }
  const active = (type: string) => cases.some((c) => c.verificationType === type && (OPEN.includes(c.status) || c.status === 'VERIFIED')
    && (type !== 'JURISDICTION' || c.jurisdiction === jurisdiction))

  return (
    <>
      <ErrorAlert error={error} />
      <section className="card panel">
        <h2>Start a check</h2>
        <ul className="checklist">
          {allowed.map((t) => (
            <li key={t}>
              <span><strong>{START_INFO[t].title}</strong><br /><span className="muted small">{START_INFO[t].desc}</span></span>
              <span className="row" style={{ flexWrap: 'nowrap' }}>
                {t === 'JURISDICTION' && (
                  <select className="input" aria-label="Jurisdiction" value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)}>
                    {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
                  </select>
                )}
                {active(t) ? <span className="badge green">Started</span>
                  : <button className="btn btn-primary btn-sm" onClick={() => start(t)}>Start</button>}
              </span>
            </li>
          ))}
        </ul>
        <p className="muted small" style={{ margin: '12px 0 0' }}>
          Documents are stored securely: only you and the compliance reviewer can open them, and every opening is recorded.
          Credential checks start automatically when you add a credential to your profile.
        </p>
      </section>
      <section className="card panel">
        <h2>Your checks</h2>
        {cases.length === 0 ? <p className="muted" style={{ margin: 0 }}>No checks yet.</p>
          : [...cases].sort((a, b) => Number(b.verificationType === 'IDENTITY') - Number(a.verificationType === 'IDENTITY'))
            .map((c) => <CaseCard key={c.id} c={c} hostedOn={hostedOn} onChange={() => { load(); onChanged?.() }} />)}
      </section>
    </>
  )
}

export function ProfessionalVerificationPage() {
  const { profile, loading } = useMyProfile()
  const [trust, setTrust] = useState<Trust | null>(null)
  const loadTrust = useCallback(() => { if (profile) trustApi.get(profile.id).then(setTrust).catch(() => {}) }, [profile])
  useEffect(() => { loadTrust() }, [loadTrust])
  if (loading) return <p className="muted">Loading…</p>
  if (!profile) return <p className="muted">Create your <Link to="/app/professional">professional profile</Link> first.</p>
  return (
    <>
      <div className="page-head"><div><h1>Verification &amp; trust</h1>
        <p className="muted" style={{ margin: 0 }}>Verified checks raise your Trust Tier. Checks are made by a verification provider or a compliance reviewer — never by AI.</p></div></div>
      {trust && <TrustSummary trust={trust} />}
      <ChecksPanel subjectType="PROFESSIONAL" subjectId={profile.id} allowed={['IDENTITY', 'JURISDICTION', 'INSURANCE']}
        onChanged={() => setTimeout(loadTrust, 1500)} />
    </>
  )
}

export function FirmVerificationPage() {
  const { firm, loading, isAdmin } = useMyFirm()
  if (loading) return <p className="muted">Loading…</p>
  if (!firm) return <p className="muted">Your firm is still being set up. Refresh in a moment.</p>
  return (
    <>
      <div className="page-head"><div><h1>Firm verification</h1>
        <p className="muted" style={{ margin: 0 }}>{firm.legalName} · {firm.status === 'VERIFIED' ? 'Verified' : 'Verification pending'}</p></div></div>
      {isAdmin ? <ChecksPanel subjectType="FIRM" subjectId={firm.id} allowed={['FIRM_REGISTRATION']} />
        : <p className="muted">Only Firm Admins can manage firm verification.</p>}
    </>
  )
}

// ---- Compliance review queue -------------------------------------------------

function DecisionForm({ c, onDone }: { c: VerificationCase; onDone: () => void }) {
  const [decision, setDecision] = useState<'VERIFIED' | 'NEEDS_INFO' | 'FAILED'>('VERIFIED')
  const [reasonCode, setReasonCode] = useState('')
  const [publicReason, setPublicReason] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    run(async () => {
      await verificationApi.decide(c.id, {
        decision, reasonCode, ...(publicReason ? { publicReason } : {}),
        ...(decision === 'VERIFIED' && expiresAt ? { expiresAt: new Date(`${expiresAt}T23:59:59Z`).toISOString() } : {}),
      })
      onDone()
    })
  }

  return (
    <form onSubmit={submit}>
      {modal}
      <ErrorAlert error={error} />
      <div className="row">
        <Field label="Decision" id="d-decision">
          <select id="d-decision" className="input" value={decision} onChange={(e) => setDecision(e.target.value as typeof decision)}>
            <option value="VERIFIED">Verified</option>
            <option value="NEEDS_INFO">Ask for more information</option>
            <option value="FAILED">Not verified</option>
          </select>
        </Field>
        <Field label="Reason code" id="d-code" hint="e.g. DOCUMENT_MATCH, REGISTRY_MATCH, BLURRY_SCAN">
          <input id="d-code" className="input" value={reasonCode} onChange={(e) => setReasonCode(e.target.value.toUpperCase())} required minLength={2} />
        </Field>
        {decision === 'VERIFIED' && (
          <Field label="Valid until (optional)" id="d-exp" hint="Credentials default to their own expiry date.">
            <input id="d-exp" className="input" type="date" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
          </Field>
        )}
      </div>
      <div style={{ height: 16 }} />
      <Field label={decision === 'VERIFIED' ? 'Message to the professional (optional)' : 'Message to the professional'} id="d-msg"
        hint="Plain language: what happened and what they can do next.">
        <textarea id="d-msg" className="input" rows={3} maxLength={500} value={publicReason} onChange={(e) => setPublicReason(e.target.value)}
          required={decision !== 'VERIFIED'} />
      </Field>
      <button className="btn btn-primary">Record decision</button>
    </form>
  )
}

export function ReviewQueuePage() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [selected, setSelected] = useState<VerificationCase | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => verificationApi.queue().then((p) => setItems(p.items)).catch(setError), [])
  useEffect(() => { load() }, [load])

  async function open(id: string) {
    setError(null)
    try {
      setSelected(await verificationApi.get(id))
    } catch (err) {
      setError(err)
    }
  }

  return (
    <>
      <div className="page-head"><div><h1>Verification reviews</h1>
        <p className="muted" style={{ margin: 0 }}>Open checks waiting for a human decision. You cannot review your own case.</p></div></div>
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {selected && (
        <section className="card panel">
          <div className="offering-top">
            <div><h2 style={{ margin: 0 }}>{selected.label}</h2>
              <p className="muted small">{selected.subjectType === 'PROFESSIONAL'
                ? <Link to={`/professionals/${selected.subjectId}`}>View professional</Link> : 'Firm'}
                {selected.jurisdiction && ` · ${countryName(selected.jurisdiction)}`}</p></div>
            <CaseStatusBadge status={selected.status} />
          </div>
          <h3>Evidence</h3>
          {selected.hostedStatus && selected.evidence.length === 0 ? (
            <div className="alert alert-info" style={{ marginBottom: 16 }}>
              Checked by {PARTNER_NAME[selected.hostedProvider ?? ''] ?? 'the identity partner'}: {HOSTED_NOTE[selected.hostedStatus] ?? selected.hostedStatus}
              {selected.hostedReason && ` (${selected.hostedReason})`}.
              The ID photos and selfie are kept by the partner: open this case in the partner's dashboard (Veriff Station or the Persona dashboard) to review them.
            </div>
          ) : selected.evidence.length === 0 ? <p className="muted small">No documents submitted. Registry and screening checks may not need any.</p> : (
            <table className="data" style={{ marginBottom: 16 }}>
              <thead><tr><th>File</th><th>Type</th><th>SHA-256</th><th>Received</th></tr></thead>
              <tbody>{selected.evidence.map((e) => (
                <tr key={e.id}><td><FileLink file={{ name: e.fileName, hasFile: e.hasFile }} url={evidenceFileUrl(e.id)} /></td><td>{e.evidenceType}</td><td><code>{e.sha256.slice(0, 16)}…</code></td><td>{fmtDate(e.uploadedAt)}</td></tr>
              ))}</tbody>
            </table>
          )}
          <DecisionForm c={selected} onDone={async () => { setNotice(`Decision recorded for ${selected.label}.`); setSelected(null); await load() }} />
          <div style={{ height: 8 }} />
          <button className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>Close</button>
        </section>
      )}
      <AppealsPanel onDecided={setNotice} />
      <VerifiedPanel onRevoked={async (msg) => { setNotice(msg); await load() }} />
      <section className="card panel">
        {items.length === 0 ? <p className="muted" style={{ margin: 0 }}>Nothing waiting. All checks are decided.</p> : (
          <table className="data">
            <thead><tr><th>Check</th><th>Subject</th><th>Status</th><th>Evidence</th><th>Due</th><th /></tr></thead>
            <tbody>{items.map((q) => (
              <tr key={q.id}>
                <td><strong>{q.label}</strong>{q.providerResult === 'REVIEW' && q.verificationType === 'RESTRICTIONS' &&
                  <div className="muted small">Possible screening match</div>}
                  {q.hostedProvider && <div className="muted small">{PARTNER_NAME[q.hostedProvider] ?? q.hostedProvider}: {HOSTED_NOTE[q.hostedStatus ?? ''] ?? q.hostedStatus}
                    {q.hostedReason && ` — ${q.hostedReason}`}</div>}</td>
                <td>{q.subjectName ?? '—'} <span className="muted small">({q.subjectType === 'FIRM' ? 'Firm' : 'Professional'})</span></td>
                <td><CaseStatusBadge status={q.status} /></td>
                <td>{q.evidenceCount}</td>
                <td>{fmtDate(q.estimatedCompletion)} {q.overdue && <span className="badge warn">Overdue</span>}</td>
                <td style={{ textAlign: 'right' }}><button className="btn btn-secondary btn-sm" onClick={() => open(q.id)}>Review</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </>
  )
}
