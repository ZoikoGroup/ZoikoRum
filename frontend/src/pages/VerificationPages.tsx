import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  CASE_STATUS, DIMENSION_VALUE, DIMENSIONS, sha256OfFile, trustApi, verificationApi,
  type EvidenceType, type QueueItem, type SelfServiceType, type SubjectType, type Trust, type VerificationCase,
} from '../api/verification'
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
  IDENTITY: { title: 'Verify your identity', desc: 'Needed for Tier B. Reviewed within about 24 hours.' },
  JURISDICTION: { title: 'Verify a licensed jurisdiction', desc: 'Needed for Tier A: proves where you may practise.' },
  INSURANCE: { title: 'Verify professional indemnity insurance', desc: 'Needed for Tier A when your work is regulated.' },
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
          <p className="muted small" style={{ margin: 0 }}>Trust score {trust.score} / 100</p>
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
      const items = await Promise.all(files.map(async (f) => ({ name: f.name, sha256: await sha256OfFile(f), size: f.size })))
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
      <Field label={hint.label} id={`ev-${c.id}`} hint="Up to 5 files, 25 MB each.">
        <input id={`ev-${c.id}`} type="file" multiple accept=".pdf,.jpg,.jpeg,.png"
          onChange={(e) => setFiles([...(e.target.files ?? [])].slice(0, 5))} />
      </Field>
      <button className="btn btn-secondary btn-sm" disabled={busy || files.length === 0}>{busy ? 'Sending…' : 'Submit for review'}</button>
    </form>
  )
}

function CaseCard({ c, onChange }: { c: VerificationCase; onChange: (c: VerificationCase) => void }) {
  return (
    <article className="case">
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
        <ul className="deliverables">{c.evidence.map((e) => <li key={e.id}>{e.fileName} <span className="muted small">· {fmtDate(e.uploadedAt)}</span></li>)}</ul>
      )}
      {c.isMine && OPEN.includes(c.status) && c.verificationType !== 'RESTRICTIONS' && <EvidenceUpload c={c} onDone={onChange} />}
    </article>
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
  useEffect(() => { load() }, [load])

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
          Secure document storage is not connected yet: for each file we record only its name, size and SHA-256 fingerprint.
          Credential checks start automatically when you add a credential to your profile.
        </p>
      </section>
      <section className="card panel">
        <h2>Your checks</h2>
        {cases.length === 0 ? <p className="muted" style={{ margin: 0 }}>No checks yet.</p>
          : cases.map((c) => <CaseCard key={c.id} c={c} onChange={() => { load(); onChanged?.() }} />)}
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
        <p className="muted" style={{ margin: 0 }}>Verified checks raise your Trust Tier. Every decision is made by a person, never by AI.</p></div></div>
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
          {selected.evidence.length === 0 ? <p className="muted small">No documents submitted. Registry and screening checks may not need any.</p> : (
            <table className="data" style={{ marginBottom: 16 }}>
              <thead><tr><th>File</th><th>Type</th><th>SHA-256</th><th>Received</th></tr></thead>
              <tbody>{selected.evidence.map((e) => (
                <tr key={e.id}><td>{e.fileName}</td><td>{e.evidenceType}</td><td><code>{e.sha256.slice(0, 16)}…</code></td><td>{fmtDate(e.uploadedAt)}</td></tr>
              ))}</tbody>
            </table>
          )}
          <DecisionForm c={selected} onDone={async () => { setNotice(`Decision recorded for ${selected.label}.`); setSelected(null); await load() }} />
          <div style={{ height: 8 }} />
          <button className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>Close</button>
        </section>
      )}
      <section className="card panel">
        {items.length === 0 ? <p className="muted" style={{ margin: 0 }}>Nothing waiting. All checks are decided.</p> : (
          <table className="data">
            <thead><tr><th>Check</th><th>Subject</th><th>Status</th><th>Evidence</th><th>Due</th><th /></tr></thead>
            <tbody>{items.map((q) => (
              <tr key={q.id}>
                <td><strong>{q.label}</strong>{q.providerResult === 'REVIEW' && q.verificationType === 'RESTRICTIONS' &&
                  <div className="muted small">Possible screening match</div>}</td>
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
