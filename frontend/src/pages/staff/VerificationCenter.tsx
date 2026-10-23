import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  CASE_STATUS, evidenceFileUrl, HOSTED_NOTE, PARTNER_NAME, trustApi, verificationApi,
  type AppealQueueItem, type DecisionReason, type EvidenceCheck, type QueueItem, type TrustHistory, type VerificationCase,
} from '../../api/verification'
import {
  AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, KpiStrip, ListDetail,
  Pill, TableFoot, dueText, label, shortDate, shortDateTime, type CheckState, type PillTone,pickRow } from '../../components/admin'
import { CaseOwner, OwnerCell, useAssignments } from '../../components/CaseOwner'
import { FileLink } from '../../components/FileLink'
import { Icon } from '../../components/dashboard'
import { ErrorAlert, Field, useStepUp } from '../../components/ui'
import { countryName } from '../ProfessionalPages'

/* Verification Center (staff design 51 / 84). Replaces the old ReviewQueuePage: one queue of verification checks with
   a right-hand review panel (evidence, readiness, the decision form, revocation), plus the appeals and the second looks
   at automatic partner approvals as their own tabs. Every figure comes from /v1/verification. */

const OPEN = ['PENDING', 'IN_REVIEW', 'NEEDS_INFO']
const DECIDED = ['VERIFIED', 'FAILED', 'EXPIRED', 'REVOKED']
const STATE_TONE: Record<string, PillTone> = {
  PENDING: 'amber', IN_REVIEW: 'blue', NEEDS_INFO: 'amber', VERIFIED: 'green', FAILED: 'red', EXPIRED: 'grey', REVOKED: 'red',
}
const statusLabel = (s: string) => CASE_STATUS[s]?.label ?? label(s)
function StatePill({ status }: { status: string }) {
  return <Pill tone={STATE_TONE[status] ?? 'grey'}>{statusLabel(status)}</Pill>
}

type Tab = 'open' | 'IN_REVIEW' | 'PENDING' | 'NEEDS_INFO' | 'overdue' | 'decided' | 'all' | 'appeals' | 'second'
type Selection = { kind: 'case'; id: string } | { kind: 'appeal'; id: string } | { kind: 'second'; id: string } | null

export default function VerificationCenter() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [appeals, setAppeals] = useState<AppealQueueItem[]>([])
  const [secondLooks, setSecondLooks] = useState<VerificationCase[]>([])
  const [tab, setTab] = useState<Tab>('open')
  const owners = useAssignments(['VERIFICATION_CASE', 'VERIFICATION_APPEAL'])
  const [sel, setSel] = useState<Selection>(null)
  const [opened, setOpened] = useState<VerificationCase | null>(null)
  const [opening, setOpening] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [loadedAt, setLoadedAt] = useState<Date | null>(null)
  const [query, setQuery] = useState('')
  const [person, setPerson] = useState('')
  const [checkType, setCheckType] = useState('')
  const [jurisdiction, setJurisdiction] = useState('')
  const [outcome, setOutcome] = useState('')
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
      if (sequence === loadSequence.current) { setItems(rows); setLoadedAt(new Date()) }
    } catch (err) { if (sequence === loadSequence.current) setError(err) }
    finally { if (sequence === loadSequence.current) { loadInProgress.current = false; setLoading(false) } }
  }, [])
  const loadAppeals = useCallback(() => verificationApi.appeals().then(setAppeals).catch(setError), [])
  const loadSecondLooks = useCallback(() => verificationApi.secondLooks().then(setSecondLooks).catch(setError), [])
  useEffect(() => {
    void load()
    void loadAppeals()
    void loadSecondLooks()
    const timer = window.setInterval(() => void load(), 15000)
    return () => { window.clearInterval(timer) }
  }, [load, loadAppeals, loadSecondLooks])

  const people = [...new Map(items.map((item) => [`${item.subjectType}:${item.subjectId}`, item])).entries()]
    .sort((a, b) => (a[1].subjectName ?? '').localeCompare(b[1].subjectName ?? ''))
  const types = [...new Set(items.map((i) => i.verificationType))].sort()
  const jurisdictions = [...new Set(items.map((i) => i.jurisdiction).filter((j): j is string => !!j))].sort()
  const open = items.filter((i) => OPEN.includes(i.status))
  const inTab = (i: QueueItem) => tab === 'all' ? true : tab === 'open' ? OPEN.includes(i.status)
    : tab === 'overdue' ? OPEN.includes(i.status) && i.overdue : tab === 'decided' ? DECIDED.includes(i.status) : i.status === tab
  const q = query.trim().toLowerCase()
  const filtered = items.filter((i) => inTab(i) && (!person || `${i.subjectType}:${i.subjectId}` === person)
    && (!checkType || i.verificationType === checkType) && (!jurisdiction || i.jurisdiction === jurisdiction)
    && (!outcome || i.status === outcome)
    && (!q || `${i.subjectName ?? ''} ${i.label} ${i.id}`.toLowerCase().includes(q)))
  const count = (pred: (i: QueueItem) => boolean) => items.filter(pred).length
  const reset = () => setVisibleCount(25)

  async function openCase(id: string) {
    const sequence = ++openSequence.current
    setSel({ kind: 'case', id })
    setOpening(id)
    setOpened(null)
    setError(null)
    try {
      const result = await verificationApi.get(id)
      if (sequence === openSequence.current) setOpened(result)
    } catch (err) { if (sequence === openSequence.current) setError(err) }
    finally { if (sequence === openSequence.current) setOpening(null) }
  }
  const close = () => { openSequence.current++; setSel(null); setOpened(null); setOpening(null) }
  const changeTab = (t: Tab) => { setTab(t); reset(); if (t !== 'decided' && t !== 'all') setOutcome('') }

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: 'open', label: 'Open checks', count: open.length },
    { key: 'IN_REVIEW', label: 'In review', count: count((i) => i.status === 'IN_REVIEW') },
    { key: 'PENDING', label: 'Waiting for documents', count: count((i) => i.status === 'PENDING') },
    { key: 'NEEDS_INFO', label: 'More information needed', count: count((i) => i.status === 'NEEDS_INFO') },
    { key: 'overdue', label: 'Overdue', count: count((i) => OPEN.includes(i.status) && i.overdue) },
    { key: 'decided', label: 'Decided', count: count((i) => DECIDED.includes(i.status)) },
    { key: 'all', label: 'All', count: items.length },
    { key: 'appeals', label: 'Appeals', count: appeals.length },
    { key: 'second', label: 'Second looks', count: secondLooks.length },
  ]

  let detail = null
  if (sel?.kind === 'case') {
    detail = (
      <div role="region" aria-label="Open verification case">
        {opening && !opened ? <section className="card adm-detail"><div className="adm-detail-body"><p role="status">Loading verification case…</p></div></section>
          : opened && <CaseDetail c={opened} onClose={close}
            owner={<CaseOwner key={opened.id} kind="VERIFICATION_CASE" caseId={opened.id} assignment={owners.get('VERIFICATION_CASE', opened.id)} onChange={owners.put} />}
            onDecided={async () => { setNotice(`Decision recorded for ${opened.label}.`); close(); await load(true) }}
            onRevoked={async (msg) => { setNotice(msg); close(); await load(true) }} onError={setError} />}
      </div>
    )
  } else if (sel?.kind === 'appeal') {
    const a = appeals.find((x) => x.id === sel.id)
    if (a) detail = <AppealDetail key={a.id} appeal={a} onClose={close} onError={setError}
      owner={<CaseOwner key={a.id} kind="VERIFICATION_APPEAL" caseId={a.id} assignment={owners.get('VERIFICATION_APPEAL', a.id)} onChange={owners.put} />}
      onDecided={async (msg) => { setNotice(msg); close(); await loadAppeals(); await load(true) }} />
  } else if (sel?.kind === 'second') {
    const c = secondLooks.find((x) => x.id === sel.id)
    if (c) detail = <SecondLookDetail key={c.id} c={c} onClose={close} onError={setError}
      onDone={async (msg) => { setNotice(msg); close(); await loadSecondLooks(); await load(true) }} />
  }

  return (
    <>
      <AdminHeader crumb="Trust, risk & compliance / Verification governance" title="Verification Center"
        subtitle="Independent review of identity, credentials, insurance and jurisdiction eligibility. Each check has its own evidence, reviewer and audit trail."
        actions={<button type="button" className="btn btn-secondary" onClick={() => { setLoading(true); void load(true); void loadAppeals(); void loadSecondLooks() }} disabled={loading}>
          <Icon name="refresh" /> {loading ? 'Loading…' : 'Refresh checks'}</button>}
        meta={<><span className="live">Refreshes every 15 seconds</span>{loadedAt && <span>Last loaded {loadedAt.toLocaleTimeString()}</span>}</>} />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      <KpiStrip>
        <AdminKpi icon="shield" tone="blue" label="Open checks" value={open.length} sub="Waiting for a human decision" />
        <AdminKpi icon="eye" tone="teal" label="In review" value={count((i) => i.status === 'IN_REVIEW')} sub="Evidence received" />
        <AdminKpi icon="request" tone="amber" label="Waiting for documents" value={count((i) => i.status === 'PENDING')} sub="Nothing uploaded yet" />
        <AdminKpi icon="message" tone="violet" label="More information needed" value={count((i) => i.status === 'NEEDS_INFO')} sub="Asked of the subject" />
        <AdminKpi icon="clock" tone="red" label="Overdue" value={count((i) => OPEN.includes(i.status) && i.overdue)} sub="Past the expected completion" />
        <AdminKpi icon="scale" tone="green" label="Open appeals" value={appeals.length} sub="Decided by a different reviewer" />
      </KpiStrip>

      <div className="card" style={{ padding: '12px 16px', marginBottom: 16, display: 'flex', gap: 10, alignItems: 'center' }}>
        <span className="kpi-icon green" style={{ width: 28, height: 28 }}><Icon name="check" /></span>
        <span className="small"><strong>Decision separation:</strong> each check is decided on its own evidence by a person, never by AI.
          The reviewer who made a decision cannot decide its appeal.</span>
      </div>

      <ListDetail detail={detail} list={
        <div className="card">
          <CountTabs tabs={tabs} value={tab} onChange={(t) => { changeTab(t); close() }} />
          {tab === 'appeals' ? <AppealsTable rows={appeals} selectedId={sel?.kind === 'appeal' ? sel.id : null} owner={(id) => <OwnerCell assignment={owners.get('VERIFICATION_APPEAL', id)} />}
            onPick={(a) => { openSequence.current++; setOpened(null); setSel({ kind: 'appeal', id: a.id }) }} />
            : tab === 'second' ? <SecondLooksTable rows={secondLooks} selectedId={sel?.kind === 'second' ? sel.id : null}
              onPick={(c) => { openSequence.current++; setOpened(null); setSel({ kind: 'second', id: c.id }) }} />
              : <>
                <FilterBar search={query} onSearch={(v) => { setQuery(v); reset() }} placeholder="Search subject, check or ID…">
                  <FilterSelect label="Professional or firm" value={person} onChange={(v) => { setPerson(v); reset() }}
                    options={people.map(([key, item]) => [key, `${item.subjectName ?? item.subjectId} (${item.subjectType === 'FIRM' ? 'Firm' : 'Professional'})`])} />
                  <FilterSelect label="Check type" value={checkType} onChange={(v) => { setCheckType(v); reset() }} options={types.map((t) => [t, label(t)])} />
                  <FilterSelect label="Jurisdiction" value={jurisdiction} onChange={(v) => { setJurisdiction(v); reset() }}
                    options={jurisdictions.map((j) => [j, countryName(j)])} />
                  {(tab === 'decided' || tab === 'all') && <FilterSelect label="Outcome" value={outcome} onChange={(v) => { setOutcome(v); reset() }}
                    options={(tab === 'all' ? [...OPEN, ...DECIDED] : DECIDED).map((s) => [s, statusLabel(s)])} />}
                </FilterBar>
                <div className="adm-note" role="status">{filtered.length} matching checks · decisions remain separate for each check</div>
                <div className="adm-table-wrap">
                  {loading && items.length === 0 ? <p role="status" style={{ padding: 16 }}>Loading checks…</p> : (
                    <table className="data">
                      <thead><tr><th scope="col">Check</th><th scope="col">Subject</th><th scope="col">Verification type</th><th scope="col">Jur.</th><th scope="col">Review state</th><th scope="col">Evidence</th><th scope="col">SLA due</th><th scope="col">Owner</th>
                        <th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
                      <tbody>
                        {filtered.length === 0 && <tr><td colSpan={9} className="empty-row">{items.length ? 'No checks match these filters.' : 'No open checks waiting for review.'}</td></tr>}
                        {filtered.slice(0, visibleCount).map((i) => {
                          const due = OPEN.includes(i.status) ? dueText(i.estimatedCompletion) : null
                          const selected = sel?.kind === 'case' && sel.id === i.id
                          return (
                            <tr {...pickRow} key={i.id} className={`pick ${selected ? 'selected' : ''}`} onClick={() => openCase(i.id)}>
                              <td><div className="cell-main">{i.label}</div><div className="cell-sub">{i.id.slice(0, 8)}</div></td>
                              <td><div className="cell-main">{i.subjectName ?? '—'}</div><div className="cell-sub">{i.subjectType === 'FIRM' ? 'Firm' : 'Professional'}</div></td>
                              <td>{label(i.verificationType)}
                                {i.providerResult === 'REVIEW' && i.verificationType === 'RESTRICTIONS' && <div className="cell-sub">Possible screening match</div>}
                                {i.providerResult === 'PASS' && i.status !== 'VERIFIED' && <div className="cell-sub">Provider check passed: your decision verifies it</div>}
                                {i.hostedProvider && <div className="cell-sub">{PARTNER_NAME[i.hostedProvider] ?? i.hostedProvider}: {HOSTED_NOTE[i.hostedStatus ?? ''] ?? i.hostedStatus}
                                  {i.hostedReason && ` — ${i.hostedReason}`}</div>}</td>
                              <td>{i.jurisdiction ?? '—'}</td>
                              <td><StatePill status={i.status} /></td>
                              <td>{i.evidenceCount}{(i.flaggedEvidence ?? 0) > 0 && <> <Pill tone="amber">{i.flaggedEvidence} flagged</Pill></>}</td>
                              <td>{shortDate(i.estimatedCompletion)}
                                {due && <div className={`cell-sub ${i.overdue || due.late ? 'late' : ''}`}>{i.overdue ? 'Overdue' : due.text}</div>}</td>
                              <td><OwnerCell assignment={owners.get('VERIFICATION_CASE', i.id)} /></td>
                              <td style={{ textAlign: 'right' }}><button type="button" className="btn btn-secondary btn-sm" disabled={opening === i.id}
                                onClick={(e) => { e.stopPropagation(); void openCase(i.id) }}>{opening === i.id ? 'Loading…' : OPEN.includes(i.status) ? 'Review' : 'View case'}</button></td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
                <TableFoot shown={Math.min(visibleCount, filtered.length)} total={filtered.length} noun="checks" />
                {filtered.length > visibleCount && <div style={{ padding: '0 16px 14px' }}>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => setVisibleCount((n) => n + 25)}>Show more checks</button></div>}
              </>}
        </div>
      } />
    </>
  )
}

/* ---------------- verification case detail ---------------- */

const CHECK_LABEL: Record<EvidenceCheck['verdict'], [string, PillTone]> = {
  MATCHES: ['Looks right', 'green'], UNRELATED: ['May be unrelated', 'amber'], UNREADABLE: ['Hard to read', 'amber'],
  UNSURE: ['Unsure', 'grey'], NOT_CHECKED: ['Not checked', 'grey'],
}
const CHECK_STATE: Record<EvidenceCheck['verdict'], CheckState> = {
  MATCHES: 'done', UNRELATED: 'missing', UNREADABLE: 'missing', UNSURE: 'pending', NOT_CHECKED: 'pending',
}

/** The automatic first look at a file: a hint only. The reviewer opens the file and decides. */
function AutomaticCheck({ check }: { check?: EvidenceCheck | null }) {
  if (!check) return <span className="muted small">Automatic check pending…</span>
  const [text, tone] = CHECK_LABEL[check.verdict]
  return (
    <span className="small"><Pill tone={tone}>{text}</Pill>
      {check.seen && <> <span className="muted">Looks like {check.seen}.</span></>}
      {check.verdict !== 'MATCHES' && <div className="muted">{check.note}</div>}</span>
  )
}

/** Partner answers that leave the decision to staff (verification service PARTNER_REVIEW). */
const PARTNER_CAPTURED = ['declined', 'failed', 'needs_review', 'completed', 'resubmission_requested']

function CaseDetail({ c, owner, onClose, onDecided, onRevoked, onError }: {
  c: VerificationCase; owner?: ReactNode; onClose: () => void; onDecided: () => Promise<void>; onRevoked: (msg: string) => Promise<void>; onError: (e: unknown) => void
}) {
  const [preset, setPreset] = useState<'NEEDS_INFO' | null>(null)
  const isOpen = OPEN.includes(c.status)
  const partnerCaptured = PARTNER_CAPTURED.includes(c.hostedStatus ?? '')
  const canVerify = c.verificationType === 'RESTRICTIONS' || c.evidence.length > 0 || partnerCaptured
  const readiness: { label: string; state: CheckState; note?: string }[] = []
  if (c.verificationType !== 'RESTRICTIONS') {
    readiness.push({ label: 'Evidence submitted', state: c.evidence.length > 0 || partnerCaptured ? 'done' : 'missing',
      note: c.evidence.length > 0 ? `${c.evidence.length} file${c.evidence.length === 1 ? '' : 's'}` : partnerCaptured ? 'Partner capture' : 'Missing' })
  }
  if (c.hostedStatus) {
    readiness.push({ label: `${PARTNER_NAME[c.hostedProvider ?? ''] ?? 'Identity partner'} result`,
      state: c.hostedStatus === 'approved' ? 'done' : ['pending', 'submitted'].includes(c.hostedStatus) ? 'pending' : partnerCaptured ? 'pending' : 'missing',
      note: HOSTED_NOTE[c.hostedStatus] ?? c.hostedStatus })
  }
  c.evidence.forEach((e, n) => {
    readiness.push({ label: `Automatic check, file ${n + 1} (${label(e.evidenceType)})`, state: e.automaticCheck ? CHECK_STATE[e.automaticCheck.verdict] : 'pending',
      note: e.automaticCheck ? CHECK_LABEL[e.automaticCheck.verdict][0] : 'Pending' })
  })
  if (c.subjectLegalName) readiness.push({ label: 'Name as on ID on record', state: 'done', note: 'Compare' })

  return (
    <DetailPanel title={c.label} onClose={onClose} badge={<StatePill status={c.status} />}
      subtitle={<>{c.subjectType === 'PROFESSIONAL' ? <Link to={`/professionals/${c.subjectId}`}>View professional</Link> : c.subjectType === 'FIRM' ? 'Firm' : 'Person'}
        {c.jurisdiction && ` · ${countryName(c.jurisdiction)}`}</>}
      footer={isOpen ? <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPreset('NEEDS_INFO')}>Request evidence</button> : undefined}>
      {isOpen && !canVerify && <Callout tone="amber" title="Decision blocked · evidence incomplete">Nothing to verify against yet: no documents have been
        uploaded. Ask for more information (the professional is told what to upload), or record that it could not be verified.</Callout>}
      {isOpen && canVerify && <Callout tone="blue" title="Ready for an independent decision">Open each file, compare it with the details below, then record the decision.</Callout>}

      <Facts title="Case context" rows={[
        ['Check type', label(c.verificationType)],
        ['Subject', c.subjectType === 'FIRM' ? 'Firm' : c.subjectType === 'IDENTITY' ? 'Person' : 'Professional'],
        ['Jurisdiction', c.jurisdiction ? countryName(c.jurisdiction) : '—'],
        ['Started', shortDate(c.createdAt)],
        ['Expected completion', shortDate(c.estimatedCompletion)],
        ...(c.verifiedAt ? [['Verified', shortDate(c.verifiedAt)] as [string, string]] : []),
        ...(c.expiresAt ? [['Valid until', shortDate(c.expiresAt)] as [string, string]] : []),
        ...(c.appeal ? [['Appeal', label(c.appeal.status)] as [string, string]] : []),
      ]} />

      {(c.subjectLegalName || c.details) && (
        <div className="tip"><span>
          <strong>Compare the documents with:</strong>
          {c.subjectLegalName && <div>Name as on ID: <strong>{c.subjectLegalName}</strong></div>}
          {c.details && Object.entries(c.details).filter(([, v]) => v !== null && v !== '').map(([k, v]) =>
            <div key={k}>{k.replace(/([A-Z])/g, ' $1').replace(/^./, (x) => x.toUpperCase())}: <strong>{String(v)}</strong></div>)}
        </span></div>
      )}

      {owner}

      {readiness.length > 0 && <Checklist title="Evidence readiness" items={readiness} />}

      <div>
        <h3 style={{ fontSize: 13.5, margin: '0 0 8px' }}>Evidence</h3>
        {c.hostedStatus && c.evidence.length === 0 ? (
          <div className="alert alert-info" style={{ margin: 0 }}>
            Checked by {PARTNER_NAME[c.hostedProvider ?? ''] ?? 'the identity partner'}: {HOSTED_NOTE[c.hostedStatus] ?? c.hostedStatus}
            {c.hostedReason && ` (${c.hostedReason})`}.
            The ID photos and selfie are kept by the partner: open this case in the partner's dashboard (Veriff Station or the Persona dashboard) to review them.
          </div>
        ) : c.evidence.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No documents submitted. Registry and screening checks may not need any.</p> : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 10 }}>{c.evidence.map((e) => (
            <li key={e.id} style={{ borderBottom: '1px solid var(--zk-border)', paddingBottom: 8 }}>
              <FileLink file={{ name: e.fileName, hasFile: e.hasFile }} url={evidenceFileUrl(e.id)} />
              <div className="cell-sub">{label(e.evidenceType)} · received {shortDateTime(e.uploadedAt)} · SHA-256 <code>{e.sha256.slice(0, 16)}…</code></div>
              <div style={{ marginTop: 4 }}><AutomaticCheck check={e.automaticCheck} /></div>
            </li>))}</ul>
        )}
      </div>

      {c.subjectType === 'PROFESSIONAL' && <TierHistory professionalId={c.subjectId} />}

      {isOpen ? <DecisionForm key={`${c.id}-${preset ?? ''}`} c={c} initial={preset} onDone={onDecided} />
        : <>
          <Callout tone={c.status === 'VERIFIED' ? 'green' : 'red'} title={`Recorded outcome: ${statusLabel(c.status)}`}>
            {(c.publicReason || c.reasonCode) && <p style={{ margin: '0 0 4px' }}>{c.publicReason || c.reasonCode}</p>}
            {c.expiresAt && <p style={{ margin: '0 0 4px' }}>Valid until: {shortDate(c.expiresAt)}</p>}
            This check has been decided. Use the revocation or appeal workflow to change an outcome.
          </Callout>
          {c.status === 'VERIFIED' && <RevokeForm c={c} onRevoked={onRevoked} onError={onError} />}
        </>}
    </DetailPanel>
  )
}

function DecisionForm({ c, initial, onDone }: { c: VerificationCase; initial: 'NEEDS_INFO' | null; onDone: () => Promise<void> }) {
  // Verifying needs something to look at: an uploaded document or the identity partner's capture (screening excepted).
  const canVerify = c.verificationType === 'RESTRICTIONS' || c.evidence.length > 0 || PARTNER_CAPTURED.includes(c.hostedStatus ?? '')
  const [decision, setDecision] = useState<'VERIFIED' | 'NEEDS_INFO' | 'FAILED'>(initial ?? (canVerify ? 'VERIFIED' : 'NEEDS_INFO'))
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
    <form onSubmit={submit} style={{ borderTop: '1px solid var(--zk-border)', paddingTop: 12 }}>
      {modal}
      <h3 style={{ fontSize: 13.5, margin: '0 0 8px' }}>Decision</h3>
      <ErrorAlert error={error} />
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
      <Field label={decision === 'VERIFIED' ? 'Message to the professional (optional)' : 'Message to the professional'} id="d-msg"
        hint="Plain language: what happened and what they can do next.">
        <textarea id="d-msg" className="input" rows={3} maxLength={500} value={publicReason} onChange={(e) => setPublicReason(e.target.value)}
          required={decision !== 'VERIFIED'} />
      </Field>
      <button className="btn btn-primary" disabled={saving} style={{ width: '100%', justifyContent: 'center' }}>{saving ? 'Recording…' : 'Record decision'}</button>
    </form>
  )
}

/** Revoke a mistaken or outdated verification: the professional sees the reason (and can appeal); the trust tier updates. */
function RevokeForm({ c, onRevoked, onError }: { c: VerificationCase; onRevoked: (msg: string) => Promise<void>; onError: (e: unknown) => void }) {
  const [openForm, setOpenForm] = useState(false)
  const [reason, setReason] = useState('')
  const { run, modal } = useStepUp(onError)
  if (!openForm) return <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpenForm(true)}>Revoke…</button>
  return (
    <div>
      {modal}
      <strong className="small">Revoke “{c.label}”?</strong>
      <p className="muted small">The check becomes “Revoked”, the professional sees your reason (and can appeal), and their trust tier updates.</p>
      <input className="input" aria-label="Revocation reason shown to the professional" maxLength={500}
        placeholder="e.g. Verified by mistake: this is an ID, not a licence" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}>
        <button type="button" className="btn btn-primary btn-sm" disabled={reason.trim().length < 5} onClick={() => run(async () => {
          await verificationApi.revoke(c.id, 'REVOKED_BY_REVIEWER', reason.trim())
          await onRevoked(`Revoked: ${c.label}.`)
        })}>Revoke</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpenForm(false)}>Cancel</button>
      </div>
    </div>
  )
}

/** Staff: how this professional's Trust Tier changed over time, and the signals behind it (assurance evidence). */
function TierHistory({ professionalId }: { professionalId: string }) {
  const [history, setHistory] = useState<TrustHistory | null>(null)
  useEffect(() => { trustApi.history(professionalId).then(setHistory).catch(() => setHistory(null)) }, [professionalId])
  if (!history || (history.tierChanges.length === 0 && history.signals.length === 0)) return null
  return (
    <details className="doc-full"><summary>Trust Tier history ({history.tierChanges.length} change{history.tierChanges.length === 1 ? '' : 's'})</summary>
      <ul className="why">{history.tierChanges.map((h, i) => <li key={i}>{shortDate(h.at)}: Tier {h.fromTier ?? '—'} → <strong>Tier {h.toTier}</strong>
        {h.reasons.length > 0 && <span className="muted small"> · {h.reasons.join('; ')}</span>}</li>)}</ul>
      {history.signals.length > 0 && <><h4>Signals</h4><ul className="why">{history.signals.slice(0, 15).map((s, i) =>
        <li key={i} className={s.adverse ? 'warn-text' : ''}>{shortDate(s.at)}: {s.summary}</li>)}</ul></>}
      {history.flags.length > 0 && <p className="small">Flags: {history.flags.join(', ')}</p>}
    </details>
  )
}

/* ---------------- appeals ---------------- */

function AppealsTable({ rows, selectedId, onPick, owner }: { rows: AppealQueueItem[]; selectedId: string | null; onPick: (a: AppealQueueItem) => void
  owner: (id: string) => ReactNode }) {
  return (
    <>
      <div className="adm-note">Open appeals · the officer who made the original decision cannot decide its appeal</div>
      <div className="adm-table-wrap">
        <table className="data">
          <thead><tr><th scope="col">Check</th><th scope="col">Subject</th><th scope="col">Original outcome</th><th scope="col">Filed</th><th scope="col">Evidence</th><th scope="col">Owner</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={7} className="empty-row">No open appeals.</td></tr>}
            {rows.map((a) => (
              <tr {...pickRow} key={a.id} className={`pick ${selectedId === a.id ? 'selected' : ''}`} onClick={() => onPick(a)}>
                <td><div className="cell-main">{a.caseLabel}</div><div className="cell-sub clamp">{a.statement}</div></td>
                <td>{a.subjectName ?? '—'}</td>
                <td><StatePill status={a.caseStatus} /></td>
                <td>{shortDate(a.filedAt)}</td>
                <td>{a.evidenceCount}</td>
                <td>{owner(a.id)}</td>
                <td style={{ textAlign: 'right' }}>{a.canDecide
                  ? <button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); onPick(a) }}>Review</button>
                  : <span className="muted small" title="You made the original decision">Another reviewer decides</span>}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <TableFoot shown={rows.length} noun="open appeals" />
    </>
  )
}

function AppealDetail({ appeal, owner, onClose, onDecided, onError }: {
  appeal: AppealQueueItem; owner?: ReactNode; onClose: () => void; onDecided: (msg: string) => Promise<void>; onError: (e: unknown) => void
}) {
  const [c, setC] = useState<VerificationCase | null>(null)
  const [note, setNote] = useState('')
  const { run, modal } = useStepUp(onError)
  useEffect(() => { verificationApi.get(appeal.caseId).then(setC).catch(onError) }, [appeal.caseId, onError])
  const decide = (outcome: 'UPHELD' | 'OVERTURNED') => run(async () => {
    await verificationApi.decideAppeal(appeal.id, { outcome, note: note.trim() })
    await onDecided(`Appeal ${outcome === 'OVERTURNED' ? 'granted: the check is now verified' : 'not upheld'} for ${appeal.caseLabel}.`)
  })
  return (
    <DetailPanel title={appeal.caseLabel} subtitle={<>{appeal.subjectName ?? '—'} · appeal filed {shortDate(appeal.filedAt)}</>}
      badge={<Pill tone="amber">Appeal open</Pill>} onClose={onClose}
      footer={appeal.canDecide ? <>
        <button type="button" className="btn btn-primary btn-sm" disabled={note.trim().length < 10} onClick={() => decide('OVERTURNED')}>Overturn: verify</button>
        <button type="button" className="btn btn-secondary btn-sm" disabled={note.trim().length < 10} onClick={() => decide('UPHELD')}>Uphold the decision</button>
      </> : undefined}>
      {modal}
      {!appeal.canDecide && <Callout tone="amber" title="Another reviewer decides">You made the original decision, so a different reviewer must decide this appeal.</Callout>}
      <Facts rows={[['Original outcome', statusLabel(appeal.caseStatus)], ['Original reason', appeal.originalReason ?? '—'], ['Evidence files', appeal.evidenceCount]]} />
      {owner}
      <div><h3 style={{ fontSize: 13.5, margin: '0 0 6px' }}>Appeal statement</h3><p className="small" style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{appeal.statement}</p></div>
      <div>
        <h3 style={{ fontSize: 13.5, margin: '0 0 6px' }}>Evidence</h3>
        {!c ? <p className="muted small" role="status">Loading evidence…</p> : c.evidence.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No documents.</p> : (
          <ul className="deliverables">{c.evidence.map((e) => <li key={e.id}><FileLink file={{ name: e.fileName, hasFile: e.hasFile }} url={evidenceFileUrl(e.id)} />
            {' '}<span className="muted small">· {shortDate(e.uploadedAt)}</span></li>)}</ul>)}
      </div>
      {appeal.canDecide && <Field label="Decision note (shown to the professional)" id="appeal-note">
        <textarea id="appeal-note" className="input" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>}
    </DetailPanel>
  )
}

/* ---------------- second looks at automatic approvals ---------------- */

function SecondLooksTable({ rows, selectedId, onPick }: { rows: VerificationCase[]; selectedId: string | null; onPick: (c: VerificationCase) => void }) {
  return (
    <>
      <div className="adm-note">Automatic partner approvals picked for a person's second look</div>
      <div className="adm-table-wrap">
        <table className="data">
          <thead><tr><th scope="col">Check</th><th scope="col">Subject</th><th scope="col">Approved</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={4} className="empty-row">No automatic approvals waiting for a second look.</td></tr>}
            {rows.map((c) => (
              <tr {...pickRow} key={c.id} className={`pick ${selectedId === c.id ? 'selected' : ''}`} onClick={() => onPick(c)}>
                <td><div className="cell-main">{c.label}</div><div className="cell-sub">{PARTNER_NAME[c.hostedProvider ?? ''] ?? c.hostedProvider ?? 'Partner'}</div></td>
                <td>{c.subjectType === 'PROFESSIONAL' ? 'Professional' : c.subjectType === 'FIRM' ? 'Firm' : 'Person'}</td>
                <td>{shortDate(c.verifiedAt)}</td>
                <td style={{ textAlign: 'right' }}><button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); onPick(c) }}>Review</button></td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <TableFoot shown={rows.length} noun="second looks" />
    </>
  )
}

function SecondLookDetail({ c, onClose, onDone, onError }: { c: VerificationCase; onClose: () => void; onDone: (msg: string) => Promise<void>; onError: (e: unknown) => void }) {
  const [overturning, setOverturning] = useState(false)
  const [reason, setReason] = useState('')
  const { run, modal } = useStepUp(onError)
  return (
    <DetailPanel title={c.label} onClose={onClose} badge={<StatePill status={c.status} />}
      subtitle={c.subjectType === 'PROFESSIONAL' ? <Link to={`/professionals/${c.subjectId}`}>View professional</Link> : 'Firm'}
      footer={!overturning ? <>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => run(async () => {
          await verificationApi.decideSecondLook(c.id, { confirm: true }); await onDone('Approval confirmed.')
        })}>Confirm</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setOverturning(true); setReason('') }}>Overturn…</button>
      </> : undefined}>
      {modal}
      <Callout tone="blue" title="Second look">The partner approved this without a person. Check it; overturning revokes the check with your reason and the person can appeal.</Callout>
      <Facts rows={[
        ['Partner', PARTNER_NAME[c.hostedProvider ?? ''] ?? c.hostedProvider ?? '—'],
        ['Partner result', c.hostedStatus ? HOSTED_NOTE[c.hostedStatus] ?? c.hostedStatus : '—'],
        ['Approved', shortDate(c.verifiedAt)],
        ['Jurisdiction', c.jurisdiction ? countryName(c.jurisdiction) : '—'],
      ]} />
      {c.evidence.length > 0 && <ul className="deliverables">{c.evidence.map((e) => <li key={e.id}>
        <FileLink file={{ name: e.fileName, hasFile: e.hasFile }} url={evidenceFileUrl(e.id)} /></li>)}</ul>}
      {overturning && <form onSubmit={(e) => { e.preventDefault(); run(async () => {
        await verificationApi.decideSecondLook(c.id, { confirm: false, reasonCode: 'SECOND_LOOK_OVERTURNED', publicReason: reason.trim() })
        await onDone('Approval overturned; the check is revoked.')
      }) }}>
        <label className="label" htmlFor="second-look-reason">Message to the person: why it is overturned and what to do</label>
        <textarea id="second-look-reason" className="input" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} required />
        <div className="row" style={{ marginTop: 8 }}><button className="btn btn-danger btn-sm" disabled={reason.trim().length < 10}>Overturn and revoke</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOverturning(false)}>Cancel</button></div>
      </form>}
    </DetailPanel>
  )
}
