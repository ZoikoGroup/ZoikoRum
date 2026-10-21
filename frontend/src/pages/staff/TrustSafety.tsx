import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'
import { reportApi, type UserReport } from '../../api/reports'
import { useAuth } from '../../auth/AuthContext'
import {
  AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, HBars, KpiStrip, ListDetail,
  MetricList, Panel, PanelRow, Pill, StatusPill, TableFoot, dueText, label, shortDate, shortDateTime, type PillTone,
} from '../../components/admin'
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
}

const NOTICE_FIELDS = ['whatHappened', 'whyItHappened', 'whatChanged', 'whatYouCanDo', 'whatHappensNext', 'howToGetHelp']
const ACTIONS: Record<number, string[]> = {
  1: ['WARNING'],
  2: ['VISIBILITY_REDUCTION', 'DISPUTE_ACCESS_RESTRICTION'],
  3: ['ENGAGEMENT_SUSPENSION', 'CREDENTIAL_ENFORCEMENT', 'VERIFICATION_RESET'],
  4: ['SUSPEND_ACCOUNT', 'OFFBOARD'],
}
const STATUSES = ['TRIAGE', 'ASSESSED', 'AWAITING_APPROVAL', 'ACTIVE', 'REVERSED', 'EXPIRED', 'CLOSED_NO_ACTION']
const CLOSED = ['REVERSED', 'EXPIRED', 'CLOSED_NO_ACTION']
const STATUS_TONE: Record<string, PillTone> = {
  TRIAGE: 'amber', ASSESSED: 'blue', AWAITING_APPROVAL: 'violet', ACTIVE: 'red', REVERSED: 'green', EXPIRED: 'grey', CLOSED_NO_ACTION: 'green',
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
  const { user } = useAuth()
  const can = (...roles: string[]) => roles.some((role) => user?.platformRoles.some((held) => held === role))
  const [params] = useSearchParams()  // the Users page links here with ?subjectType=IDENTITY&subjectId=<id>
  const [rows, setRows] = useState<Case[] | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [tab, setTab] = useState<Tab>('all')
  const [q, setQ] = useState('')
  const [level, setLevel] = useState('')
  const [source, setSource] = useState('')
  const [overdueOnly, setOverdueOnly] = useState('')
  const [page, setPage] = useState(1)
  const [selId, setSelId] = useState<string | null>(null)
  const [showOpen, setShowOpen] = useState(!!params.get('subjectId'))
  const [showRisk, setShowRisk] = useState(false)
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
          {can('TS_ANALYST', 'RISK_LEAD', 'PLATFORM_ADMIN') && <button type="button" className="btn btn-secondary" onClick={() => setShowRisk((v) => !v)}>
            <Icon name="chart" /> {showRisk ? 'Hide risk scores' : 'Risk scores'}</button>}
          <button type="button" className="btn btn-secondary" onClick={() => { setNotice(null); reload().catch(setError) }} disabled={busy}>
            <Icon name="refresh" /> Refresh cases</button>
          {can('TS_ANALYST') && <button type="button" className="btn btn-primary" onClick={() => setShowOpen((v) => !v)}>
            <Icon name="plus" /> Open a case</button>}
        </>}
        meta={truncated ? <span>Showing the first {PAGE * MAX_PAGES} cases</span> : undefined} />
      <ErrorAlert error={error} />
      {modal}
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      {showRisk && can('TS_ANALYST', 'RISK_LEAD', 'PLATFORM_ADMIN') && <div style={{ marginBottom: 16 }}><RiskScores /></div>}
      {showOpen && can('TS_ANALYST') && <OpenCaseForm busy={busy} subjectType={params.get('subjectType')} subjectId={params.get('subjectId')}
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
          <HBars rows={STATUSES.map((s, i) => ({ label: label(s), value: by(s), color: ['#2f80ed', '#0e9384', '#9b8afb', '#f04438', '#12b76a', '#667085', '#98a2b3'][i] }))} />
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
              <thead><tr><th>Case / age</th><th>Summary & subject</th><th>Source</th><th>Stage</th><th>Level</th><th>Next step</th></tr></thead>
              <tbody>
                {!rows && <tr><td colSpan={6} className="empty-row"><span role="status">Loading cases…</span></td></tr>}
                {rows && filtered.length === 0 && <tr><td colSpan={6} className="empty-row">No safety cases in this view.</td></tr>}
                {shown.map((c) => (
                  <tr key={c.id} className={`pick ${selId === c.id ? 'selected' : ''}`} onClick={() => setSelId(c.id)}>
                    <td><div className="cell-id">{c.id.slice(0, 8)}</div><div className="cell-sub">Age {age(c.createdAt)}</div></td>
                    <td><div className="cell-main clamp">{c.summary}</div><div className="cell-sub">{label(c.subjectType)} · <code>{c.subjectId.slice(0, 8)}</code></div></td>
                    <td>{label(c.signalSource)}</td>
                    <td><Pill tone={STATUS_TONE[c.status] ?? 'grey'}>{label(c.status)}</Pill></td>
                    <td><Pill tone={LEVEL_TONE[c.level] ?? 'grey'}>Level {c.level}</Pill></td>
                    <td className="small">{nextStep(c)}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>
          <TableFoot shown={shown.length} total={filtered.length} noun="cases" page={page} pages={pages} onPage={setPage} />
        </div>
      } detail={selected && <CaseDetail key={selected.id} c={selected} can={can} busy={busy} act={act} onClose={() => setSelId(null)} />} />
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

function CaseDetail({ c, can, busy, act, onClose }: {
  c: Case; can: (...roles: string[]) => boolean; busy: boolean; onClose: () => void
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
          ['Opened', shortDateTime(c.createdAt)],
          ['Triage due', c.triageDueAt ? <span key="due" className={c.overdue ? 'late' : ''}>{shortDateTime(c.triageDueAt)}{c.overdue ? ' · overdue' : ''}</span> : '—'],
          ['Action', c.action ? label(c.action) : 'None'],
          ['Applied', shortDateTime(c.appliedAt)],
          ['Appeal deadline', shortDateTime(c.appealDeadline)],
        ]} />
        <Checklist title="Due-process notice" items={NOTICE_FIELDS.map((k) => ({ label: fieldLabel(k), state: c.notice?.[k] ? 'done' : 'pending' }))} />
        {noticeDone === 0 && <p className="adm-foot-note">The notice is written when an action is proposed.</p>}
        {c.remediation.length > 0 && <div>
          <h3 style={{ fontSize: 13.5, margin: '0 0 6px' }}>Remediation</h3>
          <ul className="why">{c.remediation.map((t, i) => <li key={i}>{t.task}{' '}
            {t.confirmedBy ? <Pill tone="green">Confirmed</Pill> : t.done ? <Pill tone="blue">Done{t.note ? `: ${t.note}` : ''}</Pill> : <Pill tone="amber">To do</Pill>}
            {can('TS_ANALYST', 'RISK_LEAD') && t.done && !t.confirmedBy && <button type="button" className="link-button small" style={{ marginLeft: 6 }}
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
        {can('LEGAL') && c.appeal.status === 'PENDING' ? (
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
  if (can('RISK_LEAD') && ['TRIAGE', 'ASSESSED'].includes(c.status)) steps.push(
    <form key="assess" onSubmit={(e) => {
      e.preventDefault()
      const d = new FormData(e.currentTarget)
      act(`${base}/assess`, { level: Number(d.get('level')), reasonCode: d.get('reasonCode') }, 'Assessment recorded.')
    }}>
      <h3 style={{ fontSize: 13.5, margin: '0 0 8px' }}>Assess</h3>
      <div className="field"><label htmlFor="operations-level">Risk Level</label>
        <select id="operations-level" className="input" name="level" defaultValue={c.level}>{[0, 1, 2, 3, 4].map((n) => <option key={n} value={n}>Level {n}</option>)}</select></div>
      <div className="field"><label htmlFor="operations-reasonCode">Reason Code</label>
        <input id="operations-reasonCode" className="input" name="reasonCode" required minLength={3} placeholder="Reason code" defaultValue={c.reasonCode ?? ''} /></div>
      <button className="btn btn-secondary btn-sm" disabled={busy}>Record Assessment</button>
    </form>)
  if (can('TS_ANALYST', 'RISK_LEAD') && c.status === 'ASSESSED' && c.level > 0) steps.push(
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
      {c.level === 2 && <div className="field"><label htmlFor={`remediation-${c.id}`}>Remediation the person must complete (one per line, optional)</label>
        <textarea id={`remediation-${c.id}`} className="input" name="remediation" rows={2} /></div>}
      <button className="btn btn-primary btn-sm" disabled={busy}>Propose Action with Notice</button>
    </form>)
  if ((c.level === 4 ? can('EXECUTIVE', 'LEGAL') : can('RISK_LEAD', 'LEGAL')) && c.status === 'AWAITING_APPROVAL') steps.push(
    <div key="approve">
      <Callout tone="blue" title="Independent approval">Proposed: {label(c.action)}. Approving applies it and sends the notice.</Callout>
      <button type="button" className="btn btn-primary" style={{ marginTop: 8 }} disabled={busy}
        onClick={() => act(`${base}/approve-action`, undefined, 'Enforcement approved.')}>Approve Enforcement as Independent Reviewer</button>
    </div>)
  if (can('TS_ANALYST', 'RISK_LEAD') && ['TRIAGE', 'ASSESSED'].includes(c.status)) steps.push(
    <ReasonForm key="close" id={`close-${c.id}`} label="Close: no action needed" busy={busy} submit={(reason) => act(`${base}/close`, { reason }, 'Case closed with no action.')} />)
  if (can('RISK_LEAD', 'LEGAL') && c.status === 'ACTIVE') steps.push(
    <ReasonForm key="reverse" id={`reverse-${c.id}`} label="Reverse Action" busy={busy} submit={(reason) => act(`${base}/reverse`, { reason }, 'Action reversed.')} />)
  if (can('EXECUTIVE') && c.status === 'ACTIVE') steps.push(
    <ReasonForm key="override" id={`override-${c.id}`} label="Executive override: end this action" busy={busy}
      submit={(reason) => act(`${base}/executive-override`, { reason }, 'Action ended by executive override.')} />)
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
