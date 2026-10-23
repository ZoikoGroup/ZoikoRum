import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'
import { reportApi, type UserReport } from '../../api/reports'
import { useCapabilities } from '../../auth/capabilities'
import {
  AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, HBars, KpiStrip, ListDetail,
  MetricList, Panel, PanelRow, Pill, StatusPill, TableFoot, dueText, label, shortDate, shortDateTime, type PillTone, pickRow, useSelectedParam } from '../../components/admin'
import { CaseOwner, OwnerCell, useAssignments } from '../../components/CaseOwner'
import { Icon } from '../../components/dashboard'
import { RiskScores } from '../../components/RiskScores'
import { ErrorAlert, useStepUp } from '../../components/ui'

/* Trust & Safety (staff design 78). Replaces the operator view of SafetyPage: the enforcement-case queue with lifecycle
   and signal-source breakdowns, due-process guardrails, and a right-hand panel carrying every workflow step (assess,
   propose with six-field notice, independent approval, reverse, appeal decision, remediation, executive override). */

interface Case {
  id: string
  subjectType: string
  subjectId: string
  summary: string
  signalSource: string
  evidenceRefs: string[]
  approvals: { identityId: string; role: string; at: string }[]
  status: string
  level: number
  reasonCode: string | null
  action: string | null
  notice: Record<string, string> | null
  appeal: { status: string; reason: string; decisionReason?: string } | null
  expiresAt: string | null
  appliedAt: string | null
  createdAt: string
  triageDueAt: string | null
  overdue: boolean
  appealDeadline: string | null
  canAppeal: boolean
  remediation: { task: string; done: boolean; doneAt?: string; note?: string; confirmedBy?: string }[]
  userImpact?: string | null
  postReview?: { rootCause: string; uxImpact: string; policyUpdates: string; by: string; at: string } | null
  postReviewRequired?: boolean
  concludedAt?: string | null
  canConclude?: boolean
}

const NOTICE_FIELDS = ['whatHappened', 'whyItHappened', 'whatChanged', 'whatYouCanDo', 'whatHappensNext', 'howToGetHelp']
const ACTIONS: Record<number, string[]> = {
  1: ['WARNING'],
  2: ['VISIBILITY_REDUCTION', 'DISPUTE_ACCESS_RESTRICTION', 'MANDATORY_REMEDIATION'],
  3: ['ENGAGEMENT_SUSPENSION', 'CREDENTIAL_ENFORCEMENT', 'VERIFICATION_RESET'],
  4: ['SUSPEND_ACCOUNT', 'OFFBOARD'],
}
const STATUSES = ['TRIAGE', 'ASSESSED', 'AWAITING_APPROVAL', 'ACTIVE', 'REVERSED', 'EXPIRED', 'CLOSED_NO_ACTION', 'CONCLUDED']
const CLOSED = ['REVERSED', 'EXPIRED', 'CLOSED_NO_ACTION', 'CONCLUDED']
const STATUS_TONE: Record<string, PillTone> = {
  TRIAGE: 'amber', ASSESSED: 'blue', AWAITING_APPROVAL: 'violet', ACTIVE: 'red', REVERSED: 'green', EXPIRED: 'grey', CLOSED_NO_ACTION: 'green', CONCLUDED: 'green',
}
const LEVEL_TONE: PillTone[] = ['grey', 'blue', 'amber', 'red', 'red']
const fieldLabel = (key: string) => key.replace(/([A-Z])/g, ' $1').replace(/^./, (x) => x.toUpperCase())
const PAGE = 100
const MAX_PAGES = 20

type Tab = 'all' | 'TRIAGE' | 'ASSESSED' | 'AWAITING_APPROVAL' | 'ACTIVE' | 'appeals' | 'closed'

function age(iso: string) {
  const h = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 3_600_000))
  return h < 48 ? `${h}h` : `${Math.round(h / 24)}d`
}

export default function TrustSafety() {
  const { has: can } = useCapabilities()  // staff capabilities: risk scores, opening and deciding cases
  const [params] = useSearchParams()  // the Users page links here with ?subjectType=IDENTITY&subjectId=<id>
  const [rows, setRows] = useState<Case[] | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [tab, setTab] = useState<Tab>('all')
  const owners = useAssignments(['ENFORCEMENT_CASE'])
  const [q, setQ] = useState('')
  const [level, setLevel] = useState('')
  const [source, setSource] = useState('')
  const [overdueOnly, setOverdueOnly] = useState('')
  const [page, setPage] = useState(1)
  const [selId, setSelId] = useState<string | null>(null)
  useSelectedParam(setSelId)
  const [showOpen, setShowOpen] = useState(!!params.get('subjectId'))
  const [showRisk, setShowRisk] = useState(false)
  const [showEthics, setShowEthics] = useState(false)
  const [showFraud, setShowFraud] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)

  // The whole queue is loaded (100 per request) so the lifecycle figures cover every case, not one page.
  const reload = useCallback(async () => {
    const all: Case[] = []
    let more = false
    for (let i = 0; i < MAX_PAGES; i++) {
      const batch = await api<Case[]>('/v1/admin/enforcement-cases', { query: { limit: String(PAGE), offset: String(i * PAGE) } })
      all.push(...batch)
      if (batch.length < PAGE) break
      if (i === MAX_PAGES - 1) more = true
    }
    setRows(all)
    setTruncated(more)
  }, [])
  useEffect(() => { reload().catch(setError) }, [reload])

  async function act(path: string, body: unknown, done: string) {
    setBusy(true)
    setNotice(null)
    try {
      await run(async () => {
        await api(path, { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID() } })
        await reload()
        setNotice(done)
      })
    } finally {
      setBusy(false)
    }
  }

  const list = rows ?? []
  const by = (s: string) => list.filter((c) => c.status === s).length
  const openCases = list.filter((c) => !CLOSED.includes(c.status))
  const appealsPending = list.filter((c) => c.appeal?.status === 'PENDING')
  const overdue = list.filter((c) => c.overdue)
  const remediationToConfirm = list.reduce((n, c) => n + c.remediation.filter((t) => t.done && !t.confirmedBy).length, 0)
  const sources = [...new Set(list.map((c) => c.signalSource))].sort()
  const sourceCounts = sources.map((s) => ({ label: label(s), value: openCases.filter((c) => c.signalSource === s).length }))
    .filter((r) => r.value > 0).sort((a, b) => b.value - a.value)

  const term = q.trim().toLowerCase()
  const filtered = list.filter((c) => (tab === 'all' ? true : tab === 'closed' ? CLOSED.includes(c.status) : tab === 'appeals' ? c.appeal?.status === 'PENDING' : c.status === tab)
    && (!level || String(c.level) === level) && (!source || c.signalSource === source) && (!overdueOnly || c.overdue)
    && (!term || `${c.id} ${c.summary} ${c.subjectId} ${c.signalSource} ${c.reasonCode ?? ''}`.toLowerCase().includes(term)))
  const PER = 25
  const pages = Math.max(1, Math.ceil(filtered.length / PER))
  const shown = filtered.slice((page - 1) * PER, page * PER)
  const selected = list.find((c) => c.id === selId) ?? null

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: 'all', label: 'All cases', count: list.length },
    { key: 'TRIAGE', label: 'Triage', count: by('TRIAGE') },
    { key: 'ASSESSED', label: 'Assessed', count: by('ASSESSED') },
    { key: 'AWAITING_APPROVAL', label: 'Awaiting approval', count: by('AWAITING_APPROVAL') },
    { key: 'ACTIVE', label: 'Active action', count: by('ACTIVE') },
    { key: 'appeals', label: 'Appeals', count: appealsPending.length },
    { key: 'closed', label: 'Closed', count: list.filter((c) => CLOSED.includes(c.status)).length },
  ]

  return (
    <>
      <AdminHeader crumb="Trust, risk & compliance / Human-governed enforcement" title="Trust & Safety"
        subtitle="Investigate signals, document proportional decisions, and protect independent appeal rights."
        actions={<>
          {can('safety.risk.read') && <button type="button" className="btn btn-secondary" onClick={() => setShowRisk((v) => !v)}>
            <Icon name="chart" /> {showRisk ? 'Hide risk scores' : 'Risk scores'}</button>}
          {can('safety.risk.read') && <button type="button" className="btn btn-secondary" onClick={() => setShowFraud((v) => !v)}>
            <Icon name="alert" /> {showFraud ? 'Hide fraud alerts' : 'Fraud alerts'}</button>}
          <button type="button" className="btn btn-secondary" onClick={() => setShowEthics((v) => !v)}>
            <Icon name="scale" /> {showEthics ? 'Hide conflicts' : 'Conflicts of interest'}</button>
          <button type="button" className="btn btn-secondary" onClick={() => { setNotice(null); reload().catch(setError) }} disabled={busy}>
            <Icon name="refresh" /> Refresh cases</button>
          {can('safety.open') && <button type="button" className="btn btn-primary" onClick={() => setShowOpen((v) => !v)}>
            <Icon name="plus" /> Open a case</button>}
        </>}
        meta={truncated ? <span>Showing the first {PAGE * MAX_PAGES} cases</span> : undefined} />
      <ErrorAlert error={error} />
      {modal}
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      {showRisk && can('safety.risk.read') && <div style={{ marginBottom: 16 }}><RiskScores /></div>}
      {showFraud && can('safety.risk.read') && <div style={{ marginBottom: 16 }}><FraudAlerts onOpen={setSelId} /></div>}
      {showEthics && <div style={{ marginBottom: 16 }}><ConflictsRegister canReadAll={can('ethics.conflicts.read')} /></div>}
      {showOpen && can('safety.open') && <OpenCaseForm busy={busy} subjectType={params.get('subjectType')} subjectId={params.get('subjectId')}
        onSubmit={(body) => act('/v1/admin/enforcement-cases', body, 'Safety case opened.')} onCancel={() => setShowOpen(false)} />}

      <KpiStrip>
        <AdminKpi icon="shield" tone="blue" label="Open cases" value={rows ? openCases.length : '…'} sub="Triage through active action" />
        <AdminKpi icon="search" tone="amber" label="In triage" value={rows ? by('TRIAGE') : '…'} sub={`${rows ? overdue.length : '…'} past triage target`} />
        <AdminKpi icon="pulse" tone="teal" label="Assessed" value={rows ? by('ASSESSED') : '…'} sub="Level and reason recorded" />
        <AdminKpi icon="scale" tone="violet" label="Awaiting approval" value={rows ? by('AWAITING_APPROVAL') : '…'} sub="Independent authority required" />
        <AdminKpi icon="lock" tone="red" label="Active actions" value={rows ? by('ACTIVE') : '…'} sub="Enforcement in force" />
        <AdminKpi icon="help" tone="green" label="Appeals pending" value={rows ? appealsPending.length : '…'} sub="Decided by Legal" />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Case lifecycle" meta={`${list.length} cases`}>
          <HBars rows={STATUSES.map((s, i) => ({ label: label(s), value: by(s), color: ['#2f80ed', '#0e9384', '#9b8afb', '#f04438', '#12b76a', '#667085', '#98a2b3', '#12b76a'][i] }))} />
        </Panel>
        <Panel title="Signal sources" meta="Open cases · signals are not findings">
          <HBars rows={sourceCounts} />
        </Panel>
        <Panel title="Due process & decisions">
          <MetricList rows={[
            { label: 'Past triage target', value: overdue.length, tone: overdue.length ? 'red' : 'green' },
            { label: 'Awaiting independent approval', value: by('AWAITING_APPROVAL'), tone: by('AWAITING_APPROVAL') ? 'amber' : undefined },
            { label: 'Appeals pending', value: appealsPending.length, tone: appealsPending.length ? 'amber' : undefined },
            { label: 'Remediation awaiting confirmation', value: remediationToConfirm, tone: remediationToConfirm ? 'amber' : undefined },
            { label: 'Reversed actions', value: by('REVERSED') },
            { label: 'Level 3+ awaiting post-review', value: list.filter((c) => c.postReviewRequired).length,
              tone: list.some((c) => c.postReviewRequired) ? 'amber' : undefined },
          ]} />
          <p className="adm-foot-note">A risk score alone never restricts an account: every action needs a case, a notice and approval.</p>
        </Panel>
      </PanelRow>

      <ListDetail list={
        <div className="card">
          <CountTabs tabs={tabs} value={tab} onChange={(t) => { setTab(t); setPage(1) }} />
          <FilterBar search={q} onSearch={(v) => { setQ(v); setPage(1) }} placeholder="Search case ID, summary, subject or source…">
            <FilterSelect label="Level" value={level} onChange={(v) => { setLevel(v); setPage(1) }} options={[0, 1, 2, 3, 4].map((l) => [String(l), `Level ${l}`])} />
            <FilterSelect label="Signal source" value={source} onChange={(v) => { setSource(v); setPage(1) }} options={sources.map((s) => [s, label(s)])} />
            <FilterSelect label="Triage target" value={overdueOnly} onChange={(v) => { setOverdueOnly(v); setPage(1) }} options={[['1', 'Past triage target only']]} />
          </FilterBar>
          <div className="adm-note">Case metadata only · evidence and reporters open in the case panel</div>
          <div className="adm-table-wrap">
            <table className="data">
              <thead><tr><th scope="col">Case / age</th><th scope="col">Summary & subject</th><th scope="col">Source</th><th scope="col">Stage</th><th scope="col">Level</th><th scope="col">Owner</th><th scope="col">Next step</th></tr></thead>
              <tbody>
                {!rows && <tr><td colSpan={7} className="empty-row"><span role="status">Loading cases…</span></td></tr>}
                {rows && filtered.length === 0 && <tr><td colSpan={7} className="empty-row">No safety cases in this view.</td></tr>}
                {shown.map((c) => (
                  <tr {...pickRow} key={c.id} className={`pick ${selId === c.id ? 'selected' : ''}`} onClick={() => setSelId(c.id)}>
                    <td><div className="cell-id">{c.id.slice(0, 8)}</div><div className="cell-sub">Age {age(c.createdAt)}</div></td>
                    <td><div className="cell-main clamp">{c.summary}</div><div className="cell-sub">{label(c.subjectType)} · <code>{c.subjectId.slice(0, 8)}</code></div></td>
                    <td>{label(c.signalSource)}</td>
                    <td><Pill tone={STATUS_TONE[c.status] ?? 'grey'}>{label(c.status)}</Pill></td>
                    <td><Pill tone={LEVEL_TONE[c.level] ?? 'grey'}>Level {c.level}</Pill></td>
                    <td><OwnerCell assignment={owners.get('ENFORCEMENT_CASE', c.id)} /></td>
                    <td className="small">{nextStep(c)}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>
          <TableFoot shown={shown.length} total={filtered.length} noun="cases" page={page} pages={pages} onPage={setPage} />
        </div>
      } detail={selected && <CaseDetail key={selected.id} c={selected} can={can} busy={busy} act={act} onClose={() => setSelId(null)}
        owner={<CaseOwner key={selected.id} kind="ENFORCEMENT_CASE" caseId={selected.id} assignment={owners.get('ENFORCEMENT_CASE', selected.id)} onChange={owners.put} />} />} />
    </>
  )
}

function nextStep(c: Case): ReactNode {
  if (c.overdue) return <span className="late">Triage overdue</span>
  if (c.appeal?.status === 'PENDING') return 'Appeal decision'
  switch (c.status) {
    case 'TRIAGE': return c.triageDueAt ? `Triage · ${dueText(c.triageDueAt).text}` : 'Triage'
    case 'ASSESSED': return c.level > 0 ? 'Propose action with notice' : 'Close: no action'
    case 'AWAITING_APPROVAL': return 'Independent approval'
    case 'ACTIVE': return c.expiresAt ? `Ends ${shortDate(c.expiresAt)}` : 'In force'
    case 'REVERSED': return c.canConclude ? (c.postReview ? 'Conclude' : 'Post-review, then conclude') : '—'
    default: return '—'
  }
}

function OpenCaseForm({ busy, subjectType, subjectId, onSubmit, onCancel }: {
  busy: boolean; subjectType: string | null; subjectId: string | null; onSubmit: (body: unknown) => void; onCancel: () => void
}) {
  return (
    <form className="card adm-panel" style={{ marginBottom: 16 }} onSubmit={(e) => {
      e.preventDefault()
      const data = new FormData(e.currentTarget)
      onSubmit({
        subjectType: data.get('subjectType'), subjectId: data.get('subjectId'), signalSource: data.get('signalSource'), summary: data.get('summary'),
        evidenceRefs: String(data.get('evidenceRefs')).split('\n').map((s) => s.trim()).filter(Boolean),
      })
    }}>
      <div className="adm-panel-head"><h2>Open evidence-based case</h2></div>
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="field" style={{ flex: 1 }}>
          <label htmlFor="operations-subjectType">Subject Type</label>
          <select id="operations-subjectType" className="input" name="subjectType" defaultValue={subjectType ?? 'IDENTITY'}>
            <option value="IDENTITY">Identity</option><option value="PROFESSIONAL">Professional</option><option value="ORGANIZATION">Organization</option>
          </select>
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label htmlFor="operations-subjectId">Subject UUID</label>
          <input id="operations-subjectId" className="input" name="subjectId" required placeholder="Subject UUID" defaultValue={subjectId ?? ''} />
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label htmlFor="operations-signalSource">Signal Source</label>
          <input id="operations-signalSource" className="input" name="signalSource" required minLength={3} placeholder="Signal source" />
        </div>
      </div>
      <div className="field">
        <label htmlFor="operations-summary">Case Summary</label>
        <textarea id="operations-summary" className="input" name="summary" required minLength={10} maxLength={2000} placeholder="Case summary" rows={3} />
      </div>
      <div className="field">
        <label htmlFor="operations-evidenceRefs">Evidence References (one per line)</label>
        <textarea id="operations-evidenceRefs" className="input" name="evidenceRefs" placeholder="e.g. SHA-256 hashes, dispute IDs, message IDs" rows={2} />
      </div>
      <div className="row">
        <button className="btn btn-primary" disabled={busy}>Open Safety Case</button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

function CaseDetail({ c, owner, can, busy, act, onClose }: {
  c: Case; owner?: ReactNode; can: (...roles: string[]) => boolean; busy: boolean; onClose: () => void
  act: (path: string, body: unknown, done: string) => Promise<void>
}) {
  const [tab, setTab] = useState('Overview')
  const base = `/v1/admin/enforcement-cases/${c.id}`
  const noticeDone = NOTICE_FIELDS.filter((k) => c.notice?.[k]).length
  const tabs = ['Overview', 'Evidence', 'Notice', 'Decision', ...(c.appeal ? ['Appeal'] : [])]
  const restricted = ['ACTIVE'].includes(c.status)
  return (
    <DetailPanel title={`Case ${c.id.slice(0, 8)}`} subtitle={<>{label(c.subjectType)} · <code>{c.subjectId}</code></>}
      badge={<Pill tone={STATUS_TONE[c.status] ?? 'grey'}>{label(c.status)}</Pill>} onClose={onClose}
      tabs={{ tabs, value: tabs.includes(tab) ? tab : 'Overview', onChange: setTab }}>
      {tab === 'Overview' && <>
        {restricted ? <Callout tone="red" title={`Action in force: ${label(c.action)}`}>{c.expiresAt ? `Ends ${shortDateTime(c.expiresAt)}.` : 'No end date set.'}</Callout>
          : c.status === 'REVERSED' ? <Callout tone="green" title="Action ended">This enforcement action has ended. The notice records the original action; other active cases may still apply.</Callout>
            : !CLOSED.includes(c.status) && <Callout tone="amber" title="No account restriction applied">The signal is advisory; a case is not a finding.
              Any action needs an assessment, a six-field notice and independent approval.</Callout>}
        <p className="small" style={{ margin: 0 }}>{c.summary}</p>
        <Facts title="Investigation & scope" rows={[
          ['Subject', `${label(c.subjectType)} ${c.subjectId.slice(0, 8)}`],
          ['Signal source', label(c.signalSource)],
          ['Level', `Level ${c.level}`],
          ['Reason code', c.reasonCode ?? '—'],
          ['User impact', c.userImpact ?? '—'],
          ['Opened', shortDateTime(c.createdAt)],
          ['Triage due', c.triageDueAt ? <span key="due" className={c.overdue ? 'late' : ''}>{shortDateTime(c.triageDueAt)}{c.overdue ? ' · overdue' : ''}</span> : '—'],
          ['Action', c.action ? label(c.action) : 'None'],
          ['Applied', shortDateTime(c.appliedAt)],
          ['Appeal deadline', shortDateTime(c.appealDeadline)],
        ]} />
        {owner}
        {c.postReview && <Facts title="Post-review" rows={[['Root cause', c.postReview.rootCause], ['User experience impact', c.postReview.uxImpact],
          ['Policy updates proposed', c.postReview.policyUpdates], ['Recorded', shortDateTime(c.postReview.at)]]} />}
        {c.postReviewRequired && <Callout tone="amber" title="Post-review required">A Level {c.level} case needs a post-review (root cause, user
          experience impact, policy updates proposed) before it closes.</Callout>}
        <Checklist title="Due-process notice" items={NOTICE_FIELDS.map((k) => ({ label: fieldLabel(k), state: c.notice?.[k] ? 'done' : 'pending' }))} />
        {noticeDone === 0 && <p className="adm-foot-note">The notice is written when an action is proposed.</p>}
        {c.remediation.length > 0 && <div>
          <h3 style={{ fontSize: 13.5, margin: '0 0 6px' }}>Remediation</h3>
          <ul className="why">{c.remediation.map((t, i) => <li key={i}>{t.task}{' '}
            {t.confirmedBy ? <Pill tone="green">Confirmed</Pill> : t.done ? <Pill tone="blue">Done{t.note ? `: ${t.note}` : ''}</Pill> : <Pill tone="amber">To do</Pill>}
            {can('safety.act') && t.done && !t.confirmedBy && <button type="button" className="link-button small" style={{ marginLeft: 6 }}
              onClick={() => act(`${base}/remediation/${i}/confirm`, undefined, 'Remediation confirmed.')}>Confirm</button>}</li>)}</ul>
        </div>}
      </>}

      {tab === 'Evidence' && <>
        <div>
          <h3 style={{ fontSize: 13.5, margin: '0 0 6px' }}>Evidence references</h3>
          {c.evidenceRefs?.length ? <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5 }}>{c.evidenceRefs.map((ref) => <li key={ref}><code>{ref}</code></li>)}</ul>
            : <p className="muted small" style={{ margin: 0 }}>No evidence references recorded.</p>}
        </div>
        {c.signalSource === 'USER_REPORT' && <CaseReports caseId={c.id} />}
        {!!c.approvals?.length && <Facts title="Recorded approvals" rows={c.approvals.map((v) => [label(v.role), <span key={v.identityId}>{shortDateTime(v.at)} · Reviewer <code>{v.identityId.slice(0, 8)}</code></span>])} />}
      </>}

      {tab === 'Notice' && (c.notice ? <Facts title="Notice to the subject" rows={Object.entries(c.notice).map(([k, v]) => [fieldLabel(k), v])} />
        : <p className="muted small">No notice yet. It is written when an action is proposed (Decision tab).</p>)}

      {tab === 'Decision' && <DecisionSteps c={c} can={can} busy={busy} act={act} />}

      {tab === 'Appeal' && c.appeal && <>
        <Facts rows={[['Appeal status', <StatusPill key="s" status={c.appeal.status} />]]} />
        <p className="small" style={{ margin: 0 }}>{c.appeal.reason}</p>
        {c.appeal.decisionReason && <p className="small muted" style={{ margin: 0 }}>Decision reason: {c.appeal.decisionReason}</p>}
        {can('safety.appeals.decide') && c.appeal.status === 'PENDING' ? (
          <form onSubmit={(e) => {
            e.preventDefault()
            const d = new FormData(e.currentTarget)
            act(`${base}/appeal/decision`, { upheld: d.get('upheld') === 'true', reason: d.get('reason') }, 'Appeal decided.')
          }}>
            <div className="field"><label htmlFor="operations-upheld">Decision</label>
              <select id="operations-upheld" className="input" name="upheld">
                <option value="false">Reject appeal</option><option value="true">Uphold appeal and reverse action</option>
              </select></div>
            <div className="field"><label htmlFor="operations-reason">Independent Review Justification</label>
              <textarea id="operations-reason" className="input" name="reason" required minLength={20} maxLength={4000} rows={3} placeholder="Legal review rationale" /></div>
            <button className="btn btn-primary btn-sm" disabled={busy}>Decide Appeal</button>
          </form>
        ) : c.appeal.status === 'PENDING' && <p className="muted small">Appeals are decided independently by Legal.</p>}
      </>}
    </DetailPanel>
  )
}

/** Every workflow step the signed-in role may take on this case, in order. */
function DecisionSteps({ c, can, busy, act }: { c: Case; can: (...roles: string[]) => boolean; busy: boolean
  act: (path: string, body: unknown, done: string) => Promise<void> }) {
  const base = `/v1/admin/enforcement-cases/${c.id}`
  const steps: ReactNode[] = []
  if (can('safety.assess') && ['TRIAGE', 'ASSESSED'].includes(c.status)) steps.push(
    <form key="assess" onSubmit={(e) => {
      e.preventDefault()
      const d = new FormData(e.currentTarget)
      act(`${base}/assess`, { level: Number(d.get('level')), reasonCode: d.get('reasonCode'), userImpact: d.get('userImpact') }, 'Assessment recorded.')
    }}>
      <h3 style={{ fontSize: 13.5, margin: '0 0 8px' }}>Assess</h3>
      <div className="field"><label htmlFor="operations-level">Risk Level</label>
        <select id="operations-level" className="input" name="level" defaultValue={c.level}>{[0, 1, 2, 3, 4].map((n) => <option key={n} value={n}>Level {n}</option>)}</select></div>
      <div className="field"><label htmlFor="operations-reasonCode">Reason Code</label>
        <input id="operations-reasonCode" className="input" name="reasonCode" required minLength={3} placeholder="Reason code" defaultValue={c.reasonCode ?? ''} /></div>
      <div className="field"><label htmlFor="operations-userImpact">User impact (who is affected and how)</label>
        <textarea id="operations-userImpact" className="input" name="userImpact" required minLength={10} maxLength={2000} rows={2}
          defaultValue={c.userImpact ?? ''} placeholder="e.g. Two active clients would lose their adviser mid-engagement" /></div>
      <button className="btn btn-secondary btn-sm" disabled={busy}>Record Assessment</button>
    </form>)
  if (can('safety.act') && c.status === 'ASSESSED' && c.level > 0) steps.push(
    <form key="propose" onSubmit={(e) => {
      e.preventDefault()
      const d = new FormData(e.currentTarget)
      act(`${base}/propose-action`, {
        action: d.get('action'),
        durationDays: d.get('durationDays') ? Number(d.get('durationDays')) : null,
        notice: Object.fromEntries(NOTICE_FIELDS.map((key) => [key, d.get(key)])),
        remediation: String(d.get('remediation') ?? '').split('\n').map((t) => t.trim()).filter(Boolean),
      }, 'Action proposed with notice; it needs independent approval.')
    }}>
      <h3 style={{ fontSize: 13.5, margin: '0 0 8px' }}>Propose notified enforcement action</h3>
      <div className="field"><label htmlFor="operations-action">Action</label>
        <select id="operations-action" className="input" name="action">{ACTIONS[c.level]?.map((a) => <option key={a} value={a}>{label(a)}</option>)}</select></div>
      <div className="field"><label htmlFor="operations-durationDays">Duration in Days (if temporary)</label>
        <input id="operations-durationDays" className="input" name="durationDays" type="number" min={1} max={365} required={c.level === 2} placeholder="e.g. 14" /></div>
      {NOTICE_FIELDS.map((key) => (
        <div className="field" key={key}><label htmlFor={`notice-${key}`}>{fieldLabel(key)}</label>
          <textarea id={`notice-${key}`} className="input" name={key} required minLength={10} maxLength={2000} rows={2} /></div>))}
      {c.level === 2 && <div className="field"><label htmlFor={`remediation-${c.id}`}>Remediation the person must complete (one per line; required for Mandatory remediation)</label>
        <textarea id={`remediation-${c.id}`} className="input" name="remediation" rows={2} /></div>}
      <button className="btn btn-primary btn-sm" disabled={busy}>Propose Action with Notice</button>
    </form>)
  if ((c.level === 4 ? can('safety.approve_severe') : can('safety.approve')) && c.status === 'AWAITING_APPROVAL') steps.push(
    <div key="approve">
      <Callout tone="blue" title="Independent approval">Proposed: {label(c.action)}. Approving applies it and sends the notice.</Callout>
      <button type="button" className="btn btn-primary" style={{ marginTop: 8 }} disabled={busy}
        onClick={() => act(`${base}/approve-action`, undefined, 'Enforcement approved.')}>Approve Enforcement as Independent Reviewer</button>
    </div>)
  if (can('safety.act') && ['TRIAGE', 'ASSESSED'].includes(c.status)) steps.push(
    <ReasonForm key="close" id={`close-${c.id}`} label="Close: no action needed" busy={busy} submit={(reason) => act(`${base}/close`, { reason }, 'Case closed with no action.')} />)
  if (can('safety.reverse') && c.status === 'ACTIVE') steps.push(
    <ReasonForm key="reverse" id={`reverse-${c.id}`} label="Reverse Action" busy={busy} submit={(reason) => act(`${base}/reverse`, { reason }, 'Action reversed.')} />)
  if (can('safety.override') && c.status === 'ACTIVE') steps.push(
    <ReasonForm key="override" id={`override-${c.id}`} label="Executive override: end this action" busy={busy}
      submit={(reason) => act(`${base}/executive-override`, { reason }, 'Action ended by executive override.')} />)
  if ((can('safety.assess') || can('safety.appeals.decide')) && c.level >= 3 && !['CLOSED_NO_ACTION', 'CONCLUDED'].includes(c.status)) steps.push(
    <form key="post-review" onSubmit={(e) => {
      e.preventDefault()
      const d = new FormData(e.currentTarget)
      act(`${base}/post-review`, { rootCause: d.get('rootCause'), uxImpact: d.get('uxImpact'), policyUpdates: d.get('policyUpdates') }, 'Post-review recorded.')
    }}>
      <h3 style={{ fontSize: 13.5, margin: '0 0 8px' }}>{c.postReview ? 'Revise post-review' : 'Post-review (required for Level 3+)'}</h3>
      {([['rootCause', 'Root cause'], ['uxImpact', 'User experience impact'], ['policyUpdates', 'Policy updates proposed']] as const).map(([k, l]) => (
        <div className="field" key={k}><label htmlFor={`pr-${k}-${c.id}`}>{l}</label>
          <textarea id={`pr-${k}-${c.id}`} className="input" name={k} required minLength={k === 'policyUpdates' ? 5 : 10} maxLength={4000} rows={2}
            defaultValue={c.postReview?.[k] ?? ''} /></div>))}
      <button className="btn btn-secondary btn-sm" disabled={busy}>Record post-review</button>
    </form>)
  if ((can('safety.act') || can('safety.reverse')) && c.canConclude) steps.push(
    <div key="conclude">
      <Callout tone="blue" title="Conclude the case">The action has ended. Concluding closes the case{c.postReview ? '.' : ' once its post-review is recorded.'}</Callout>
      <button type="button" className="btn btn-primary btn-sm" style={{ marginTop: 8 }} disabled={busy || !c.postReview}
        onClick={() => act(`${base}/conclude`, undefined, 'Case concluded.')}>Conclude case</button>
    </div>)
  if (can('safety.referral') && c.level === 4) steps.push(<Referrals key="referrals" c={c} busy={busy} act={act} />)
  if (steps.length === 0) return <p className="muted small">No workflow step is open to your role at this stage ({label(c.status)}).</p>
  return <>{steps.map((s, i) => <div key={i} style={i ? { borderTop: '1px solid var(--zk-border)', paddingTop: 12 } : undefined}>{s}</div>)}</>
}

function ReasonForm({ id, label: text, busy, submit }: { id: string; label: string; busy: boolean; submit: (reason: string) => void }) {
  return (
    <form onSubmit={(e) => { e.preventDefault(); submit(String(new FormData(e.currentTarget).get('reason'))) }}>
      <div className="field">
        <label htmlFor={id}>{text} Reason</label>
        <textarea id={id} name="reason" className="input" required minLength={20} maxLength={4000} rows={2} placeholder={`${text}: state reason clearly`} />
      </div>
      <button className="btn btn-secondary btn-sm" disabled={busy}>{text}</button>
    </form>
  )
}

/** The user reports behind a case (staff). Confidential reporters are named only to Risk Lead and Legal. */
function CaseReports({ caseId }: { caseId: string }) {
  const [rows, setRows] = useState<UserReport[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  if (rows === null) return <div><ErrorAlert error={error} />
    <button type="button" className="btn btn-ghost btn-sm" onClick={() => reportApi.forCase(caseId).then(setRows).catch(setError)}>Show the reports</button></div>
  return (
    <div>
      <h3 style={{ fontSize: 13.5, margin: '0 0 6px' }}>User reports ({rows.length})</h3>
      <ul className="why">{rows.map((r) => (
        <li key={r.id}><strong>{r.categoryLabel}</strong> · {r.reporter} · {shortDate(r.createdAt)}
          {r.possibleRetaliation && <> <Pill tone="amber">In an open dispute with the subject</Pill></>}
          <div className="small">{r.description}</div></li>))}</ul>
    </div>
  )
}


interface Referral { id: string; agency: string; agencyReference: string; referredOn: string; legalSignOff: string; createdAt: string }

/** Level 4: referrals to law enforcement or a regulator. Legal only; never shown on the case itself. */
function Referrals({ c, busy, act }: { c: Case; busy: boolean; act: (path: string, body: unknown, done: string) => Promise<void> }) {
  const base = `/v1/admin/enforcement-cases/${c.id}/referrals`
  const [rows, setRows] = useState<Referral[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => api<Referral[]>(base).then(setRows).catch(setError), [base])
  return (
    <div>
      <h3 style={{ fontSize: 13.5, margin: '0 0 8px' }}>Law enforcement / regulator referral (Legal only)</h3>
      <ErrorAlert error={error} />
      {rows === null ? <button type="button" className="btn btn-ghost btn-sm" onClick={load}>Show referrals (audited)</button>
        : rows.length === 0 ? <p className="muted small">No referral recorded.</p>
          : <Facts rows={rows.map((r) => [`${r.agency} · ${shortDate(r.referredOn)}`, <span key={r.id}>{r.agencyReference} · {r.legalSignOff}</span>])} />}
      <form style={{ marginTop: 8 }} onSubmit={async (e) => {
        e.preventDefault()
        const d = new FormData(e.currentTarget)
        await act(base, { agency: d.get('agency'), agencyReference: d.get('agencyReference'), referredOn: d.get('referredOn'),
          legalSignOff: d.get('legalSignOff') }, 'Referral recorded.')
        load()
      }}>
        <div className="row">
          <div className="field" style={{ flex: 1 }}><label htmlFor={`agency-${c.id}`}>Agency</label>
            <input id={`agency-${c.id}`} className="input" name="agency" required minLength={2} maxLength={200} /></div>
          <div className="field" style={{ flex: 1 }}><label htmlFor={`agencyRef-${c.id}`}>Their reference</label>
            <input id={`agencyRef-${c.id}`} className="input" name="agencyReference" required minLength={2} maxLength={200} /></div>
          <div className="field"><label htmlFor={`referredOn-${c.id}`}>Referred on</label>
            <input id={`referredOn-${c.id}`} className="input" name="referredOn" type="date" required /></div>
        </div>
        <div className="field"><label htmlFor={`signoff-${c.id}`}>Legal sign-off</label>
          <textarea id={`signoff-${c.id}`} className="input" name="legalSignOff" required minLength={10} maxLength={2000} rows={2}
            placeholder="Who approved the referral, and on what basis" /></div>
        <button className="btn btn-secondary btn-sm" disabled={busy}>Record referral</button>
      </form>
    </div>
  )
}

interface FraudAlert { id: string; provider: string; alertId: string; subjectType: string; subjectId: string; reasonCode: string
  score: number | null; receivedAt: string; caseId: string | null; caseStatus: string | null }

/** Third-party fraud alerts: advisory signals, each opening a Level 0 review. */
function FraudAlerts({ onOpen }: { onOpen: (caseId: string) => void }) {
  const [rows, setRows] = useState<FraudAlert[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { api<FraudAlert[]>('/v1/admin/fraud-alerts').then(setRows).catch(setError) }, [])
  return (
    <Panel title="Third-party fraud alerts" meta="Advisory · each opens a Level 0 review">
      <ErrorAlert error={error} />
      {!rows ? <p className="muted small" role="status">Loading…</p> : rows.length === 0 ? <p className="muted small">No alerts received.</p> : (
        <table className="data"><thead><tr><th>Received</th><th>Provider</th><th>Subject</th><th>Reason</th><th>Score</th><th>Review</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id}><td className="small">{shortDateTime(r.receivedAt)}</td><td>{r.provider}<div className="cell-sub">{r.alertId}</div></td>
            <td className="small">{label(r.subjectType)} <code>{r.subjectId.slice(0, 8)}</code></td><td className="small">{label(r.reasonCode)}</td>
            <td>{r.score ?? '—'}</td>
            <td>{r.caseId ? <button type="button" className="link-button small" onClick={() => onOpen(r.caseId!)}>{label(r.caseStatus)}</button> : '—'}</td></tr>)}</tbody></table>)}
    </Panel>
  )
}

interface ConflictEntry { id: string; identityId: string; staffName: string | null; kind: 'DECLARATION' | 'RECUSAL'; subjectType: string | null
  subjectId: string | null; caseKind: string | null; caseId: string | null; reason: string; status: string; createdAt: string; withdrawnAt: string | null }

/** Staff conflicts of interest and recusals: a declared conflict blocks you from assessing, approving or deciding matching work. */
function ConflictsRegister({ canReadAll }: { canReadAll: boolean }) {
  const [rows, setRows] = useState<ConflictEntry[] | null>(null)
  const [all, setAll] = useState(false)
  const [kind, setKind] = useState<'DECLARATION' | 'RECUSAL'>('DECLARATION')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => api<ConflictEntry[]>('/v1/admin/conflicts', { query: all ? {} : { mine: 'true' } }).then(setRows).catch(setError), [all])
  useEffect(() => { load() }, [load])
  async function send(path: string, body?: unknown) {
    setBusy(true); setError(null)
    try { await api(path, { method: 'POST', body }); await load() } catch (err) { setError(err) } finally { setBusy(false) }
  }
  return (
    <Panel title="Conflicts of interest & recusals" meta={all ? 'Whole register' : 'Your declarations'}
      action={canReadAll ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAll((v) => !v)}>{all ? 'Show mine' : 'Show register'}</button> : undefined}>
      <ErrorAlert error={error} />
      <form onSubmit={(e) => {
        e.preventDefault()
        const d = new FormData(e.currentTarget)
        send('/v1/admin/conflicts', kind === 'DECLARATION'
          ? { kind, subjectType: d.get('subjectType'), subjectId: d.get('subjectId'), reason: d.get('reason') }
          : { kind, caseKind: d.get('caseKind'), caseId: d.get('caseId'), reason: d.get('reason') })
        e.currentTarget.reset()
      }}>
        <div className="row">
          <div className="field"><label htmlFor="coi-kind">Type</label>
            <select id="coi-kind" className="input" value={kind} onChange={(e) => setKind(e.target.value as 'DECLARATION' | 'RECUSAL')}>
              <option value="DECLARATION">Conflict with a person or organisation</option><option value="RECUSAL">Recuse from one case</option></select></div>
          {kind === 'DECLARATION' ? <>
            <div className="field"><label htmlFor="coi-subjectType">Subject type</label>
              <select id="coi-subjectType" className="input" name="subjectType"><option value="IDENTITY">Person</option>
                <option value="PROFESSIONAL">Professional</option><option value="ORGANIZATION">Organisation</option></select></div>
            <div className="field" style={{ flex: 1 }}><label htmlFor="coi-subjectId">Subject ID</label>
              <input id="coi-subjectId" className="input" name="subjectId" required placeholder="UUID" /></div>
          </> : <>
            <div className="field"><label htmlFor="coi-caseKind">Case type</label>
              <select id="coi-caseKind" className="input" name="caseKind"><option value="DISPUTE">Dispute</option>
                <option value="ENFORCEMENT_CASE">Safety case</option></select></div>
            <div className="field" style={{ flex: 1 }}><label htmlFor="coi-caseId">Case ID</label>
              <input id="coi-caseId" className="input" name="caseId" required maxLength={80} placeholder="UUID" /></div>
          </>}
        </div>
        <div className="field"><label htmlFor="coi-reason">Reason</label>
          <textarea id="coi-reason" className="input" name="reason" required minLength={10} maxLength={2000} rows={2} /></div>
        <button className="btn btn-secondary btn-sm" disabled={busy}>Declare</button>
      </form>
      {rows && rows.length > 0 && <table className="data" style={{ marginTop: 12 }}>
        <thead><tr><th>Declared</th>{all && <th>Staff</th>}<th>Concerns</th><th>Reason</th><th>Status</th><th /></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id}><td className="small">{shortDate(r.createdAt)}</td>{all && <td>{r.staffName ?? '—'}</td>}
          <td className="small">{r.kind === 'DECLARATION' ? `${label(r.subjectType)} ${r.subjectId?.slice(0, 8)}` : `Recusal: ${label(r.caseKind)} ${r.caseId?.slice(0, 8)}`}</td>
          <td className="small">{r.reason}</td><td><StatusPill status={r.status} /></td>
          <td>{!all && r.status === 'ACTIVE' && <button type="button" className="link-button small" disabled={busy}
            onClick={() => send(`/v1/admin/conflicts/${r.id}/withdraw`)}>Withdraw</button>}</td></tr>)}</tbody></table>}
    </Panel>
  )
}
