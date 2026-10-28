import type { BeneficialOwner } from '../api/verification'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  CASE_STATUS, DIMENSION_VALUE, DIMENSIONS, evidenceFileUrl, HOSTED_NOTE, PARTNER_NAME, trustApi, verificationApi,
  type AppealQueueItem, type DecisionReason, type EvidenceCheck, type EvidenceType, type QueueItem, type SelfServiceType, type SubjectType, type Trust, type TrustHistory, type VerificationCase,
} from '../api/verification'
import { toUpload } from '../api/files'
import { FileLink } from '../components/FileLink'
import { HostedVerification } from '../components/HostedVerification'
import { ErrorAlert, Field, useStepUp, Loading } from '../components/ui'
import { NoFirm, useMyFirm } from './FirmPages'
import { COUNTRIES } from './Join'
import { countryName, useMyProfile } from './ProfessionalPages'
import { proApi, type Profile } from '../api/professional'
import { lightName, trustLight } from '../lib/trustLight'
import { TrustLight } from '../components/TrustLight'

const OPEN = ['PENDING', 'IN_REVIEW', 'NEEDS_INFO']
const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—')

const EVIDENCE_FOR: Record<string, { type: EvidenceType; label: string }> = {
  IDENTITY: { type: 'ID_DOCUMENT', label: 'Passport, national ID card or driving licence' },
  CREDENTIAL: { type: 'LICENSE', label: 'Licence or certificate' },
  JURISDICTION: { type: 'LICENSE', label: 'Licence or registration for this jurisdiction' },
  INSURANCE: { type: 'INSURANCE_POLICY', label: 'Insurance policy schedule' },
  FIRM_REGISTRATION: { type: 'REGISTRATION_DOCUMENT', label: 'Certificate of incorporation or registry extract' },
  BACKGROUND: { type: 'OTHER', label: 'Background-check report or the screening provider\'s confirmation' },
  BENEFICIAL_OWNERSHIP: { type: 'REGISTRATION_DOCUMENT', label: 'Shareholder register or register of persons with significant control' },
}

const START_INFO: Record<SelfServiceType, { title: string; desc: string }> = {
  IDENTITY: { title: 'Verify your identity (start here)', desc: 'Required for everyone: passport, national ID (e.g. Aadhaar) or driving licence. Gives an Amber trust light. Reviewed within about 24 hours.' },
  JURISDICTION: { title: 'Verify a professional licence for a country', desc: 'Only if you hold a licence to practise (e.g. CA, CPA, bar admission). Upload the licence, not your ID. Not needed for most technology or advisory work.' },
  INSURANCE: { title: 'Verify professional indemnity insurance', desc: 'Only for regulated work (legal, audit, tax filing). Upload the policy schedule.' },
  FIRM_REGISTRATION: { title: 'Verify the firm registration', desc: 'Confirms the firm is a registered legal entity.' },
  BACKGROUND: { title: 'Background check', desc: 'Some enterprise buyers require it for regulated or sensitive work. Runs only with your consent; you see the result before buyers do.' },
  BENEFICIAL_OWNERSHIP: { title: 'Declare beneficial owners', desc: 'Everyone who owns 25% or more of the firm, or controls it. Enterprise buyers and regulators ask for this.' },
}
const CONSENT_TEXT = 'I consent to Zoikorum, through its screening provider, checking my identity against criminal-record, '
  + 'sanctions and professional-discipline sources where the law allows, and to the result being recorded on my verification. '
  + 'I can withdraw before the check completes.'

export function CaseStatusBadge({ status }: { status: string }) {
  const s = CASE_STATUS[status] ?? { label: status, cls: '' }
  return <span className={`badge ${s.cls}`}>{s.label}</span>
}

/** Trust light, the five verification areas, and why. */
export function TrustSummary({ trust }: { trust: Trust }) {
  return (
    <section className="card panel">
      <div className="trust-head">
        <span className={`tier tier-${trust.tier}`} aria-hidden><span className="light-dot" style={{ background: trustLight(trust.tier).color, width: 14, height: 14 }} />{lightName(trust.tier)}</span>
        <div>
          <h2 style={{ margin: 0 }}>{lightName(trust.tier)} trust light: {trustLight(trust.tier).label}</h2>
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
      <h3>What each trust light unlocks</h3>
      <table className="data">
        <thead><tr><th>Trust light</th><th>Needs</th><th>Unlocks</th></tr></thead>
        <tbody>
          <tr><td><TrustLight tier="C" /></td><td>A published profile</td><td>Visible in search; no contracts or protected payments</td></tr>
          <tr><td><TrustLight tier="B" /></td><td>Identity verified, screening clear</td><td>Respond to requests; limited-risk engagements (per buyer policy)</td></tr>
          <tr><td><TrustLight tier="A" /></td><td>Amber + required credentials, a verified jurisdiction, insurance where required</td><td>Enterprise and regulated engagements</td></tr>
        </tbody>
      </table>
    </section>
  )
}

function EvidenceUpload({ c, onDone }: { c: VerificationCase; onDone: (c: VerificationCase) => void }) {
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [done, setDone] = useState(false)
  const hint = EVIDENCE_FOR[c.verificationType] ?? { type: 'OTHER' as EvidenceType, label: 'Supporting document' }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const items = await Promise.all(files.map((f) => toUpload(f, ['pdf', 'jpg', 'jpeg', 'png'])))
      onDone(await verificationApi.addEvidence(c.id, hint.type, items))
      setFiles([])
      setDone(true)
      window.setTimeout(() => setDone(false), 8000)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="evidence-form">
      <ErrorAlert error={error} />
      {done && <div className="alert alert-success" role="status">Document uploaded successfully. It is now with the reviewer.</div>}
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
      {c.isMine && (c.status === 'NEEDS_INFO' || (c.status === 'IN_REVIEW' && (c.evidence.length > 0 || (!!c.hostedStatus && !['pending', 'submitted'].includes(c.hostedStatus))))) && (
        <p className="small" style={{ margin: '8px 0 0' }}>A person is reviewing this check.{' '}
          <Link to={`/app/help?topic=verification&case=${c.id}`}>Request review help</Link> if something is unclear or urgent.</p>
      )}
      {hosted && !uploadInstead && <button type="button" className="text-btn small"
        onClick={() => setUploadInstead(true)}>Can't use a camera? Upload your document for a person to review instead</button>}
      {c.isMine && OPEN.includes(c.status) && (c.verificationType !== 'RESTRICTIONS' || c.status === 'NEEDS_INFO')
        && (!hosted || uploadInstead) && <EvidenceUpload c={c} onDone={onChange} />}
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
        <table className="data"><thead><tr><th>Check</th><th>Subject</th><th>Filed</th><th>Evidence</th><th><span className="sr-only">Actions</span></th></tr></thead>
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
    the professional sees; the trust light updates). */
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
          <p className="muted small">The check becomes “Revoked”, the professional sees your reason (and can appeal), and their trust light updates.</p>
          <input className="input" placeholder="Reason shown to the professional, e.g. Verified by mistake: this is an ID, not a licence" maxLength={500}
            value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn-primary btn-sm" disabled={reason.trim().length < 5} onClick={() => run(async () => {
              await verificationApi.revoke(target.id, 'REVOKED_BY_REVIEWER', reason.trim())
              onRevoked(`Revoked: ${target.label} for ${target.subjectName}.`); setTarget(null); setReason(''); await load()
            })}>Revoke</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setTarget(null)}>Cancel</button></div>
        </div>}
        <table className="data"><thead><tr><th>Check</th><th>Subject</th><th>Verified</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{items.map((q) => <tr key={q.id}><td><strong>{q.label}</strong></td><td>{q.subjectName ?? '—'}</td>
            <td><CaseStatusBadge status={q.status} /></td>
            <td style={{ textAlign: 'right' }}><button className="btn btn-ghost btn-sm" onClick={() => { setTarget(q); setReason('') }}>Revoke…</button></td></tr>)}</tbody></table>
      </>)}
    </section>
  )
}

const FIRM_START_INFO: Partial<Record<SelfServiceType, { title: string; desc: string }>> = {
  JURISDICTION: { title: 'Verify a firm licence for a country', desc: 'Only if the firm itself is licensed or registered to practise there (e.g. an audit or law firm registration). Upload the firm\'s licence.' },
  INSURANCE: { title: 'Verify the firm\'s professional indemnity insurance', desc: 'For regulated work (legal, audit, tax filing). Upload the firm\'s policy schedule, with its end date.' },
}
const PERSON_START_INFO: Partial<Record<SelfServiceType, { title: string; desc: string }>> = {
  IDENTITY: { title: 'Verify your identity as authorized representative', desc: 'Passport, national ID or driving licence. The firm can offer regulated work only once a representative\'s identity is verified.' },
}

/** All checks for a subject, plus buttons to start the self-service ones. */
// eslint-disable-next-line react-refresh/only-export-components
export function ChecksPanel({ subjectType, subjectId, allowed, onChanged }: {
  subjectType: SubjectType
  subjectId: string
  allowed: SelfServiceType[]
  onChanged?: () => void
}) {
  const info = (t: SelfServiceType) =>
    (subjectType === 'FIRM' ? FIRM_START_INFO[t] : subjectType === 'IDENTITY' ? PERSON_START_INFO[t] : undefined) ?? START_INFO[t]
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

  const [owners, setOwners] = useState<BeneficialOwner[]>([{ name: '', country: 'GB', percent: 100, control: false }])
  async function start(type: SelfServiceType) {
    setError(null)
    try {
      if (type === 'BACKGROUND' && !confirm(CONSENT_TEXT)) return
      await verificationApi.start({ verificationType: type, subjectType, subjectId, ...(type === 'JURISDICTION' ? { jurisdiction } : {}),
        ...(type === 'BACKGROUND' ? { consent: true } : {}), ...(type === 'BENEFICIAL_OWNERSHIP' ? { owners } : {}) })
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
              <span><strong>{info(t).title}</strong><br /><span className="muted small">{info(t).desc}</span></span>
              <span className="row" style={{ flexWrap: 'nowrap' }}>
                {t === 'BENEFICIAL_OWNERSHIP' && !active(t) && <OwnersEditor owners={owners} onChange={setOwners} />}
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
  if (loading) return <Loading />
  if (!profile) return <p className="muted">Create your <Link to="/app/professional">professional profile</Link> first.</p>
  return (
    <>
      <div className="page-head"><div><h1>Verification &amp; trust</h1>
        <p className="muted" style={{ margin: 0 }}>Verified checks move your trust light towards Green. Checks are made by a verification provider or a compliance reviewer — never by AI.</p></div></div>
      {trust && <TrustSummary trust={trust} />}
      <IdentityDetailsConfirm profile={profile} />
      <ChecksPanel subjectType="PROFESSIONAL" subjectId={profile.id} allowed={['IDENTITY', 'JURISDICTION', 'INSURANCE', 'BACKGROUND']}
        onChanged={() => setTimeout(loadTrust, 1500)} />
    </>
  )
}

export function FirmVerificationPage() {
  const { firm, loading, error, isAdmin } = useMyFirm()
  if (loading) return <Loading />
  if (!firm) return <NoFirm error={error} />
  return (
    <>
      <div className="page-head"><div><h1>Firm verification</h1>
        <p className="muted" style={{ margin: 0 }}>{firm.legalName} · {firm.status === 'VERIFIED' ? 'Verified' : 'Verification pending'}</p></div></div>
      {isAdmin ? <ChecksPanel subjectType="FIRM" subjectId={firm.id} allowed={['FIRM_REGISTRATION', 'BENEFICIAL_OWNERSHIP', 'JURISDICTION', 'INSURANCE']} />
        : <p className="muted">Only Firm Admins can manage firm verification.</p>}
    </>
  )
}

// ---- Compliance review queue -------------------------------------------------

const CHECK_LABEL: Record<EvidenceCheck['verdict'], [string, string]> = {
  MATCHES: ['Looks right', 'green'], UNRELATED: ['May be unrelated', 'warn'], UNREADABLE: ['Hard to read', 'warn'],
  UNSURE: ['Unsure', ''], NOT_CHECKED: ['Not checked', ''],
}

/** The automatic first look at a file: a hint only. The reviewer opens the file and decides. */
function AutomaticCheck({ check }: { check?: EvidenceCheck | null }) {
  if (!check) return <span className="muted small">Pending…</span>
  const [label, tone] = CHECK_LABEL[check.verdict]
  return (
    <span className="small"><span className={`badge ${tone}`}>{label}</span>
      {check.seen && <> <span className="muted">Looks like {check.seen}.</span></>}
      {check.verdict !== 'MATCHES' && <div className="muted">{check.note}</div>}</span>
  )
}

/** Partner answers that leave the decision to staff (verification service PARTNER_REVIEW). */
const PARTNER_CAPTURED = ['declined', 'failed', 'needs_review', 'completed', 'resubmission_requested']

function DecisionForm({ c, onDone }: { c: VerificationCase; onDone: () => void }) {
  // Verifying needs something to look at: an uploaded document or the identity partner's capture (screening excepted).
  const canVerify = c.verificationType === 'RESTRICTIONS' || c.evidence.length > 0 || PARTNER_CAPTURED.includes(c.hostedStatus ?? '')
  const [decision, setDecision] = useState<'VERIFIED' | 'NEEDS_INFO' | 'FAILED'>(canVerify ? 'VERIFIED' : 'NEEDS_INFO')
  const [reasons, setReasons] = useState<DecisionReason[]>([])
  const [reasonCode, setReasonCode] = useState('')
  const [otherCode, setOtherCode] = useState('')
  const [publicReason, setPublicReason] = useState('')
  useEffect(() => { verificationApi.decisionReasons(c.verificationType).then(setReasons).catch(() => {}) }, [c.verificationType])
  const fitting = reasons.filter((r) => r.decisions.includes(decision))
  /** A standard reason fills in its plain-language message; staff can still edit it. */
  function pickReason(code: string) {
    setReasonCode(code)
    const message = reasons.find((r) => r.code === code)?.message
    if (message) setPublicReason(message)
  }
  function pickDecision(next: typeof decision) {
    setDecision(next)
    if (reasonCode && !reasons.find((r) => r.code === reasonCode)?.decisions.includes(next)) { setReasonCode(''); setPublicReason('') }
  }
  const [expiresAt, setExpiresAt] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)
  const { run, modal } = useStepUp(setError)

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    run(async () => {
      if (savingRef.current) return
      savingRef.current = true
      setSaving(true)
      try {
        await verificationApi.decide(c.id, {
        decision, reasonCode: reasonCode === 'OTHER' && otherCode.trim() ? otherCode.trim() : reasonCode,
        ...(publicReason ? { publicReason } : {}),
        ...(decision === 'VERIFIED' && expiresAt ? { expiresAt: new Date(`${expiresAt}T23:59:59Z`).toISOString() } : {}),
      })
        await onDone()
      } finally { savingRef.current = false; setSaving(false) }
    })
  }

  return (
    <form onSubmit={submit}>
      {modal}
      <ErrorAlert error={error} />
      {!canVerify && (
        <div className="alert alert-info" role="note">
          Nothing to verify against yet: no documents have been uploaded. Ask for more information (the professional is
          told what to upload), or record that it could not be verified.
        </div>
      )}
      <div className="row">
        <Field label="Decision" id="d-decision">
          <select id="d-decision" className="input" value={decision} onChange={(e) => pickDecision(e.target.value as typeof decision)}>
            {canVerify && <option value="VERIFIED">Verified</option>}
            <option value="NEEDS_INFO">Ask for more information</option>
            <option value="FAILED">Not verified</option>
          </select>
        </Field>
        <Field label="Reason" id="d-code" hint="Standard reasons fill in the message below; you can edit it.">
          <select id="d-code" className="input" value={reasonCode} onChange={(e) => pickReason(e.target.value)} required>
            <option value="">Choose a reason…</option>
            {fitting.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
          </select>
        </Field>
        {reasonCode === 'OTHER' && (
          <Field label="Short code for this reason (optional)" id="d-other" hint="For reports, e.g. EMBASSY_LETTER">
            <input id="d-other" className="input" value={otherCode} maxLength={60}
              onChange={(e) => setOtherCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))} />
          </Field>
        )}
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
      <button className="btn btn-primary" disabled={saving}>{saving ? 'Recording…' : 'Record decision'}</button>
    </form>
  )
}

export function ReviewQueuePage() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [selected, setSelected] = useState<VerificationCase | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [opening, setOpening] = useState<string | null>(null)
  const [person, setPerson] = useState('')
  const [query, setQuery] = useState('')
  const [checkType, setCheckType] = useState('')
  const [status, setStatus] = useState('OPEN')
  const [visibleCount, setVisibleCount] = useState(25)
  const loadSequence = useRef(0)
  const loadInProgress = useRef(false)
  const openSequence = useRef(0)
  const load = useCallback(async (force = false) => {
    if (loadInProgress.current && !force) return
    loadInProgress.current = true
    const sequence = ++loadSequence.current
    try {
      const rows = await verificationApi.reviewCases()
      if (sequence === loadSequence.current) setItems(rows)
    } catch (err) { if (sequence === loadSequence.current) setError(err) }
    finally { if (sequence === loadSequence.current) { loadInProgress.current = false; setLoading(false) } }
  }, [])
  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 15000)
    return () => { window.clearInterval(timer) }
  }, [load])
  const people = [...new Map(items.map(item => [`${item.subjectType}:${item.subjectId}`, item])).entries()]
    .sort((a, b) => (a[1].subjectName ?? '').localeCompare(b[1].subjectName ?? ''))
  const filtered = items.filter(item => (!person || `${item.subjectType}:${item.subjectId}` === person)
    && (!checkType || item.verificationType === checkType) && (!status || (status === 'OPEN' ? OPEN.includes(item.status) : item.status === status))
    && (!query.trim() || `${item.subjectName ?? ''} ${item.label}`.toLowerCase().includes(query.trim().toLowerCase())))
  function resetFilters() { setVisibleCount(25) }

  async function open(id: string) {
    const sequence = ++openSequence.current
    setOpening(id)
    setSelected(null)
    setError(null)
    try {
      const result = await verificationApi.get(id)
      if (sequence === openSequence.current) setSelected(result)
    } catch (err) { if (sequence === openSequence.current) setError(err) }
    finally { if (sequence === openSequence.current) setOpening(null) }
  }

  return (
    <>
      <div className="page-head"><div><h1>Verification reviews</h1>
        <p className="muted" style={{ margin: 0 }}>Filter verification history by person, check and status. Open cases need an independent human decision.</p></div></div>
      <ErrorAlert error={error} />
      <SecondLooks onDone={setNotice} onError={setError} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {opening && <p role="status">Loading verification case…</p>}
      {selected && (
        <section className="card panel" aria-label="Open verification case">
          <div className="offering-top">
            <div><h2 style={{ margin: 0 }}>{selected.label}</h2>
              <p className="muted small">{selected.subjectType === 'PROFESSIONAL'
                ? <Link to={`/professionals/${selected.subjectId}`}>View professional</Link> : 'Firm'}
                {selected.jurisdiction && ` · ${countryName(selected.jurisdiction)}`}</p></div>
            <CaseStatusBadge status={selected.status} />
          </div>
          {(selected.subjectLegalName || selected.details) && (
            <div className="tip" style={{ marginBottom: 12 }}><span>
              <strong>Compare the documents with:</strong>
              {selected.subjectLegalName && <div>Name as on ID: <strong>{selected.subjectLegalName}</strong></div>}
              {selected.details && Object.entries(selected.details).filter(([, v]) => v !== null && v !== '').map(([k, v]) =>
                <div key={k}>{k.replace(/([A-Z])/g, ' $1').replace(/^./, (x) => x.toUpperCase())}: <strong>{String(v)}</strong></div>)}
            </span></div>
          )}
          {selected.subjectType === 'PROFESSIONAL' && <TierHistoryPanel professionalId={selected.subjectId} />}
          <h3>Evidence</h3>
          {selected.hostedStatus && selected.evidence.length === 0 ? (
            <div className="alert alert-info" style={{ marginBottom: 16 }}>
              Checked by {PARTNER_NAME[selected.hostedProvider ?? ''] ?? 'the identity partner'}: {HOSTED_NOTE[selected.hostedStatus] ?? selected.hostedStatus}
              {selected.hostedReason && ` (${selected.hostedReason})`}.
              The ID photos and selfie are kept by the partner: open this case in the partner's dashboard (Veriff Station or the Persona dashboard) to review them.
            </div>
          ) : selected.evidence.length === 0 ? <p className="muted small">No documents submitted. Registry and screening checks may not need any.</p> : (
            <table className="data" style={{ marginBottom: 16 }}>
              <thead><tr><th>File</th><th>Type</th><th>Automatic check</th><th>SHA-256</th><th>Received</th></tr></thead>
              <tbody>{selected.evidence.map((e) => (
                <tr key={e.id}><td><FileLink file={{ name: e.fileName, hasFile: e.hasFile }} url={evidenceFileUrl(e.id)} /></td><td>{e.evidenceType}</td>
                  <td><AutomaticCheck check={e.automaticCheck} /></td>
                  <td><code>{e.sha256.slice(0, 16)}…</code></td><td>{fmtDate(e.uploadedAt)}</td></tr>
              ))}</tbody>
            </table>
          )}
          {OPEN.includes(selected.status) ? <DecisionForm key={selected.id} c={selected} onDone={async () => { setNotice(`Decision recorded for ${selected.label}.`); setSelected(current => current?.id === selected.id ? null : current); await load(true) }} /> : <div className="tip"><span><strong>Recorded outcome: {selected.status.replaceAll('_', ' ')}</strong>{(selected.publicReason || selected.reasonCode) && <p>{selected.publicReason || selected.reasonCode}</p>}{selected.expiresAt && <p>Valid until: {fmtDate(selected.expiresAt)}</p>}<p>This check has been decided. Use the revocation or appeal workflow to change an outcome.</p></span></div>}
          <div style={{ height: 8 }} />
          <button className="btn btn-ghost btn-sm" onClick={() => { openSequence.current++; setSelected(null) }}>Close</button>
        </section>
      )}
      <AppealsPanel onDecided={setNotice} />
      <VerifiedPanel onRevoked={async (msg) => { setNotice(msg); await load(true) }} />
      <section className="card panel">
        <h2>Verification checks</h2>
        <div className="review-filters">
          <Field label="Search person or check" id="review-search"><input id="review-search" className="input" value={query} onChange={e => { setQuery(e.target.value); resetFilters() }} /></Field>
          <Field label="Professional or firm" id="review-person"><select id="review-person" className="input" value={person} onChange={e => { setPerson(e.target.value); resetFilters() }}><option value="">All people and firms</option>{people.map(([key, item]) => <option key={key} value={key}>{item.subjectName ?? item.subjectId} ({item.subjectType === 'FIRM' ? 'Firm' : 'Professional'})</option>)}</select></Field>
          <Field label="Check type" id="review-type"><select id="review-type" className="input" value={checkType} onChange={e => { setCheckType(e.target.value); resetFilters() }}><option value="">All checks</option>{[...new Set(items.map(item => item.verificationType))].map(type => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}</select></Field>
          <Field label="Status" id="review-status"><select id="review-status" className="input" value={status} onChange={e => { setStatus(e.target.value); resetFilters() }}><option value="OPEN">Open checks</option><option value="">All statuses</option>{[...OPEN, 'VERIFIED', 'FAILED', 'EXPIRED', 'REVOKED'].map(value => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></Field>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={() => { setLoading(true); void load(true) }} disabled={loading}>{loading ? 'Loading…' : 'Refresh checks'}</button>
        <p className="muted small" role="status">{filtered.length} matching checks. Decisions remain separate for each check.</p>
        {loading && items.length === 0 ? <p role="status">Loading checks…</p> : filtered.length === 0 ? <p className="muted">{items.length ? 'No checks match these filters.' : 'No open checks waiting for review.'}</p> : (
          <table className="data">
            <thead><tr><th>Check</th><th>Subject</th><th>Status</th><th>Evidence</th><th>Due</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{filtered.slice(0, visibleCount).map((q) => (
              <tr key={q.id}>
                <td><strong>{q.label}</strong>{q.providerResult === 'REVIEW' && q.verificationType === 'RESTRICTIONS' &&
                  <div className="muted small">Possible screening match</div>}
                  {q.hostedProvider && <div className="muted small">{PARTNER_NAME[q.hostedProvider] ?? q.hostedProvider}: {HOSTED_NOTE[q.hostedStatus ?? ''] ?? q.hostedStatus}
                    {q.hostedReason && ` — ${q.hostedReason}`}</div>}</td>
                <td>{q.subjectName ?? '—'} <span className="muted small">({q.subjectType === 'FIRM' ? 'Firm' : 'Professional'})</span></td>
                <td><CaseStatusBadge status={q.status} /></td>
                <td>{q.evidenceCount}{(q.flaggedEvidence ?? 0) > 0 && <> <span className="badge warn" title="The automatic check thinks a file is unrelated or unreadable">
                  {q.flaggedEvidence} flagged</span></>}</td>
                <td>{fmtDate(q.estimatedCompletion)} {q.overdue && <span className="badge warn">Overdue</span>}</td>
                <td style={{ textAlign: 'right' }}><button className="btn btn-secondary btn-sm" disabled={opening === q.id} onClick={() => open(q.id)}>{opening === q.id ? 'Loading…' : OPEN.includes(q.status) ? 'Review' : 'View case'}</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
        {filtered.length > visibleCount && <button className="btn btn-secondary" onClick={() => setVisibleCount(n => n + 25)}>Show more checks</button>}
      </section>
    </>
  )
}


/** Automatic partner approvals picked for a person's second look (ethics code: human oversight of every approval process). */
function SecondLooks({ onDone, onError }: { onDone: (msg: string) => void; onError: (err: unknown) => void }) {
  const [rows, setRows] = useState<VerificationCase[]>([])
  const [overturning, setOverturning] = useState<VerificationCase | null>(null)
  const [reason, setReason] = useState('')
  const { run, modal } = useStepUp(onError)
  const load = useCallback(() => verificationApi.secondLooks().then(setRows).catch(onError), [onError])
  useEffect(() => { load() }, [load])
  if (rows.length === 0) return null
  return (
    <section className="card panel">
      {modal}
      <div className="panel-head"><h2>Second looks at automatic approvals</h2><span className="badge">{rows.length}</span></div>
      <p className="muted small" style={{ marginTop: 0 }}>The partner approved these without a person. Check them; overturning revokes the
        check with your reason and the person can appeal.</p>
      <table className="data"><thead><tr><th>Check</th><th>Approved</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{rows.map((c) => <tr key={c.id}>
          <td><strong>{c.label}</strong><div className="muted small">{c.subjectType === 'PROFESSIONAL' ? <Link to={`/professionals/${c.subjectId}`}>View professional</Link> : 'Firm'}</div></td>
          <td className="small">{fmtDate(c.verifiedAt)}</td>
          <td><span className="row" style={{ flexWrap: 'nowrap' }}>
            <button className="btn btn-secondary btn-sm" onClick={() => run(async () => {
              await verificationApi.decideSecondLook(c.id, { confirm: true }); onDone('Approval confirmed.'); await load()
            })}>Confirm</button>
            <button className="btn btn-ghost btn-sm" onClick={() => { setOverturning(c); setReason('') }}>Overturn…</button></span></td>
        </tr>)}</tbody></table>
      {overturning && <form style={{ marginTop: 12 }} onSubmit={(e) => { e.preventDefault(); run(async () => {
        await verificationApi.decideSecondLook(overturning.id, { confirm: false, reasonCode: 'SECOND_LOOK_OVERTURNED', publicReason: reason.trim() })
        setOverturning(null); onDone('Approval overturned; the check is revoked.'); await load()
      }) }}>
        <label className="label" htmlFor="second-look-reason">Message to the person: why it is overturned and what to do</label>
        <textarea id="second-look-reason" className="input" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} required />
        <div className="row" style={{ marginTop: 8 }}><button className="btn btn-danger btn-sm" disabled={reason.trim().length < 10}>Overturn and revoke</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOverturning(null)}>Cancel</button></div>
      </form>}
    </section>
  )
}


/** Staff: how this professional's trust light changed over time, and the signals behind it (assurance evidence). */
function TierHistoryPanel({ professionalId }: { professionalId: string }) {
  const [history, setHistory] = useState<TrustHistory | null>(null)
  useEffect(() => { trustApi.history(professionalId).then(setHistory).catch(() => setHistory(null)) }, [professionalId])
  if (!history || (history.tierChanges.length === 0 && history.signals.length === 0)) return null
  return (
    <details className="doc-full" style={{ marginBottom: 12 }}><summary>Trust light history ({history.tierChanges.length} change{history.tierChanges.length === 1 ? '' : 's'})</summary>
      <ul className="why">{history.tierChanges.map((h, i) => <li key={i}>{fmtDate(h.at)}: {h.fromTier ? lightName(h.fromTier) : '—'} → <strong>{lightName(h.toTier)}</strong>
        {h.reasons.length > 0 && <span className="muted small"> · {h.reasons.join('; ')}</span>}</li>)}</ul>
      {history.signals.length > 0 && <><h4>Signals</h4><ul className="why">{history.signals.slice(0, 15).map((s, i) =>
        <li key={i} className={s.adverse ? 'warn-text' : ''}>{fmtDate(s.at)}: {s.summary}</li>)}</ul></>}
      {history.flags.length > 0 && <p className="small">Flags: {history.flags.join(', ')}</p>}
    </details>
  )
}


/** Beneficial owners of a firm: name, country, share, and whether they control it. */
function OwnersEditor({ owners, onChange }: { owners: BeneficialOwner[]; onChange: (o: BeneficialOwner[]) => void }) {
  const set = (i: number, patch: Partial<BeneficialOwner>) => onChange(owners.map((o, j) => j === i ? { ...o, ...patch } : o))
  return (
    <span className="owners" style={{ display: 'grid', gap: 4 }}>
      {owners.map((o, i) => <span key={i} className="row" style={{ flexWrap: 'nowrap' }}>
        <input className="input" aria-label="Owner name" placeholder="Full name" value={o.name} onChange={(e) => set(i, { name: e.target.value })} />
        <select className="input" aria-label="Owner country" value={o.country} onChange={(e) => set(i, { country: e.target.value })}>
          {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</select>
        <input className="input" aria-label="Share %" type="number" min={0} max={100} style={{ width: 80 }} value={o.percent}
          onChange={(e) => set(i, { percent: Number(e.target.value) })} />
        <label className="small"><input type="checkbox" checked={o.control} onChange={(e) => set(i, { control: e.target.checked })} /> controls</label>
        {owners.length > 1 && <button className="btn btn-ghost btn-sm" onClick={() => onChange(owners.filter((_, j) => j !== i))}>Remove</button>}
      </span>)}
      <button className="btn btn-ghost btn-sm" onClick={() => onChange([...owners, { name: '', country: 'GB', percent: 0, control: false }])}>Add owner</button>
    </span>
  )
}

const CAPTURED = ['submitted', 'approved', 'declined', 'failed', 'needs_review', 'completed', 'resubmission_requested']

/** After the identity partner has captured the ID (or a document was uploaded): confirm the name on the ID matches the
    legal name on the profile. The partner does not send the extracted name back to us, so the person confirms it here;
    a mismatch can be corrected while the check is open, or raised with support once it is verified. */
function IdentityDetailsConfirm({ profile: initial }: { profile: Profile }) {
  const [profile, setProfile] = useState(initial)
  const [c, setCase] = useState<VerificationCase | null>(null)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(initial.legalName ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const storageKey = c ? `zk.identity-confirmed.${c.id}` : null
  const [confirmed, setConfirmed] = useState(false)
  useEffect(() => {
    verificationApi.forSubject('PROFESSIONAL', initial.id).then((cases) => {
      const k = cases.find((x) => x.verificationType === 'IDENTITY' && x.isMine && !['FAILED', 'REVOKED', 'EXPIRED'].includes(x.status)) ?? null
      setCase(k)
      try { setConfirmed(!!k && localStorage.getItem(`zk.identity-confirmed.${k.id}`) === '1') } catch { /* storage blocked */ }
    }).catch(() => {})
  }, [initial.id])
  if (!c || !(c.evidence.length > 0 || CAPTURED.includes(c.hostedStatus ?? ''))) return null
  const verified = c.status === 'VERIFIED'
  if (confirmed && !editing) return null
  return (
    <section className="card panel" aria-labelledby="idc-h">
      <h2 id="idc-h" style={{ marginTop: 0 }}>Confirm your details</h2>
      <p className="small">Your ID has been {verified ? 'verified' : 'captured'}. Check that the name on it matches the legal name on your profile;
        a mismatch is the most common reason a check is sent back.</p>
      <ErrorAlert error={error} />
      <ul className="checklist small">
        <li><span>Legal name on your profile (private)</span><strong>{profile.legalName || 'Not set'}</strong></li>
        <li><span>Name shown to buyers</span><strong>{profile.displayName}</strong></li>
      </ul>
      {editing && !verified ? (
        <form className="row" style={{ alignItems: 'flex-end', marginTop: 8 }} onSubmit={async (e) => {
          e.preventDefault(); setBusy(true); setError(null)
          try { const p = await proApi.update(profile.version, { legalName: name.trim() }); setProfile(p); setEditing(false) }
          catch (err) { setError(err) } finally { setBusy(false) }
        }}>
          <Field label="Legal name exactly as on your ID" id="idc-name">
            <input id="idc-name" className="input" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <button className="btn btn-primary btn-sm" disabled={busy || !name.trim()}>{busy ? 'Saving…' : 'Save correction'}</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
        </form>
      ) : (
        <div className="row" style={{ marginTop: 8 }}>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => {
            try { if (storageKey) localStorage.setItem(storageKey, '1') } catch { /* storage blocked */ }
            setConfirmed(true)
          }}>Yes, it matches my ID</button>
          {verified
            ? <Link className="btn btn-secondary btn-sm" to={`/app/help?topic=verification&case=${c.id}&request=name-correction`}>Request a name correction</Link>
            : <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>Correct my legal name</button>}
        </div>
      )}
    </section>
  )
}

