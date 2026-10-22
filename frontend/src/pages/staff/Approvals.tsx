import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  approvalsApi, approverText, KIND_LABEL, STATUS_LABEL, type ApprovalKind, type ApprovalRequest, type ApprovalStatus, type ApprovalSummary,
} from '../../api/approvals'
import { ROLE_LABEL } from '../../api/auth'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, Initials, KpiStrip, ListDetail, Pill, TableFoot,
  shortDateTime, type PillTone,pickRow } from '../../components/admin'
import { ErrorAlert, useStepUp } from '../../components/ui'

/* Approvals (maker-checker for privileged staff actions). Sources: GET /v1/admin/approval-requests (?awaitingMe, ?mine,
   ?status, ?kind), GET /v1/admin/approval-requests/summary, POST /v1/admin/approval-requests/{id}/decision and /cancel.
   One staff member asks (staff roles, switches, financial exceptions, money replays, audit exports); a different person
   with the required role approves or rejects here, with a fresh two-step code. Approving carries the action out at once
   and the request shows APPLIED, or FAILED with the reason: nothing is shown as done before the server says it is. */

type TabKey = 'awaiting' | 'mine' | 'all'

const STATUS_TONE: Record<ApprovalStatus, PillTone> = {
  REQUESTED: 'amber', APPLIED: 'green', FAILED: 'red', REJECTED: 'red', EXPIRED: 'grey', CANCELLED: 'grey',
}
const KINDS = Object.keys(KIND_LABEL) as ApprovalKind[]
const STATUSES = Object.keys(STATUS_LABEL) as ApprovalStatus[]

function LifecyclePill({ status }: { status: ApprovalStatus }) {
  return <Pill tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Pill>
}

/** "3h 12m left" / "expired", refreshed by the caller's clock. */
function countdown(expiresAt: string, now: number): { text: string; late: boolean } {
  const ms = new Date(expiresAt).getTime() - now
  if (ms <= 0) return { text: 'Expired', late: true }
  const mins = Math.floor(ms / 60_000)
  const h = Math.floor(mins / 60)
  return { text: h > 0 ? `${h}h ${mins % 60}m left` : `${mins}m left`, late: h < 2 }
}

function useNow(everyMs = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), everyMs)
    return () => window.clearInterval(t)
  }, [everyMs])
  return now
}

const who = (p: ApprovalRequest['requestedBy'] | null) => (p ? p.displayName ?? p.email ?? p.id.slice(0, 8) : '—')

export default function Approvals() {
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<TabKey>('awaiting')
  const [rows, setRows] = useState<ApprovalRequest[] | null>(null)
  const [summary, setSummary] = useState<ApprovalSummary | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [selected, setSelected] = useState<ApprovalRequest | null>(null)
  const { run, modal } = useStepUp(setError)
  const now = useNow()

  const load = useCallback(async () => {
    try {
      const filters = tab === 'awaiting' ? { awaitingMe: true, kind: kind || undefined }
        : { mine: tab === 'mine', status: status || undefined, kind: kind || undefined }
      const [list, s] = await Promise.all([approvalsApi.list({ ...filters, limit: 100 }), approvalsApi.summary()])
      setRows(list); setSummary(s)
    } catch (err) { setError(err) }
  }, [tab, kind, status])
  useEffect(() => { void load() }, [load])

  // A notification links here with ?request=<id>: open that request whatever the tab.
  const linked = params.get('request')
  useEffect(() => {
    if (!linked) return
    approvalsApi.get(linked).then((r) => { setSelected(r); if (!r.canDecide) setTab(r.canCancel ? 'mine' : 'all') }).catch(setError)
  }, [linked])

  function pick(r: ApprovalRequest | null) {
    setSelected(r); setNotice('')
    if (!r && linked) setParams({}, { replace: true })
  }

  function decided(r: ApprovalRequest) {
    setSelected(r)
    setNotice(r.status === 'APPLIED' ? `Approved and applied: ${r.summary}.`
      : r.status === 'FAILED' ? `Approved, but it could not be carried out: ${r.applyError ?? 'see the request'}.`
        : r.status === 'REJECTED' ? `Rejected: ${r.summary}. Nothing was changed.`
          : `Request ${STATUS_LABEL[r.status].toLowerCase()}.`)
    void load()
  }

  const decide = (r: ApprovalRequest, approve: boolean, note: string) => run(async () => {
    setError(null); setNotice('')
    decided(await approvalsApi.decide(r.id, approve, note.trim() || undefined))
  })
  const cancel = (r: ApprovalRequest) => {
    if (!confirm('Cancel this request? Nothing will be changed.')) return
    void run(async () => {
      setError(null); setNotice('')
      decided(await approvalsApi.cancel(r.id))
    })
  }

  const all = rows ?? []
  const term = q.trim().toLowerCase()
  const shown = all.filter((r) => !term || [r.summary, r.justification, who(r.requestedBy), KIND_LABEL[r.kind]].some((v) => v.toLowerCase().includes(term)))

  return (
    <>
      <AdminHeader crumb="Administration & support / Governance" title="Approvals"
        subtitle="Privileged staff actions wait here for a second person. Approve or reject with a fresh two-step code: approving carries the action out at once, and nobody approves their own request." />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {modal}

      <KpiStrip>
        <AdminKpi icon="check" tone={summary?.awaitingMe ? 'amber' : 'green'} label="Awaiting my decision" value={summary ? summary.awaitingMe : '—'}
          sub="Requests you can approve or reject" />
        <AdminKpi icon="clock" tone="blue" label="My open requests" value={summary ? summary.myOpen : '—'} sub="Waiting for another person" />
        <AdminKpi icon="shield" tone="green" label="Applied (7 days)" value={summary ? summary.applied7d : '—'}
          sub={summary?.failed7d ? `${summary.failed7d} approved but failed` : 'Approved and carried out'} />
        <AdminKpi icon="alert" tone={summary?.rejectedOrExpired7d ? 'red' : 'violet'} label="Rejected or expired (7 days)"
          value={summary ? summary.rejectedOrExpired7d : '—'} sub="Never carried out" />
      </KpiStrip>

      <ListDetail
        list={
          <div className="card">
            <CountTabs tabs={[
              { key: 'awaiting' as TabKey, label: 'Awaiting my decision', count: summary?.awaitingMe ?? null },
              { key: 'mine' as TabKey, label: 'My requests', count: summary?.myOpen ?? null },
              { key: 'all' as TabKey, label: 'All', count: tab === 'all' && rows ? rows.length : null },
            ]} value={tab} onChange={(t) => { setTab(t); setRows(null); pick(null) }} />
            <FilterBar search={q} onSearch={setQ} placeholder="Search request, reason or requester…">
              <FilterSelect label="Kind" value={kind} onChange={setKind} options={KINDS.map((k) => [k, KIND_LABEL[k]])} />
              {tab !== 'awaiting' && <FilterSelect label="Status" value={status} onChange={setStatus} options={STATUSES.map((s) => [s, STATUS_LABEL[s]])} />}
            </FilterBar>
            <div className="adm-note">Maker-checker · step-up to request and to decide · requests expire if nobody decides · every step is audited</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th scope="col">Request</th><th scope="col">Requested by</th><th scope="col">Status</th><th scope="col">Expires</th><th scope="col"><span className="sr-only">Action</span></th></tr></thead>
                <tbody>
                  {rows === null && <tr><td colSpan={5} className="empty-row">Loading requests…</td></tr>}
                  {rows && shown.length === 0 && <tr><td colSpan={5} className="empty-row">
                    {tab === 'awaiting' ? 'Nothing is waiting for your decision.' : 'No requests here.'}</td></tr>}
                  {shown.map((r) => {
                    const due = countdown(r.expiresAt, now)
                    return (
                      <tr {...pickRow} key={r.id} className={`pick ${selected?.id === r.id ? 'selected' : ''}`} onClick={() => pick(r)}>
                        <td><div className="cell-main">{r.summary}</div><div className="cell-sub">{KIND_LABEL[r.kind]}</div></td>
                        <td><span className="name-cell"><Initials name={who(r.requestedBy)} /><span><div className="cell-main">{who(r.requestedBy)}</div>
                          <div className="cell-sub">{shortDateTime(r.requestedAt)}</div></span></span></td>
                        <td><LifecyclePill status={r.status} /></td>
                        <td className={r.status === 'REQUESTED' && due.late ? 'late' : ''}>{r.status === 'REQUESTED' ? due.text : '—'}</td>
                        <td><button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); pick(r) }}>
                          {r.canDecide ? 'Decide' : 'View'}</button></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <TableFoot shown={shown.length} total={all.length} noun="requests" />
          </div>
        }
        detail={selected && <RequestDetail key={`${selected.id}:${selected.status}`} r={selected} now={now} onClose={() => pick(null)}
          onDecide={(approve, note) => void decide(selected, approve, note)} onCancel={() => cancel(selected)} />}
      />
    </>
  )
}

/** Requested -> Approved -> Applied, with the step the request stopped at. */
function Lifecycle({ r }: { r: ApprovalRequest }) {
  const approved = r.status === 'APPLIED' || r.status === 'FAILED'
  const steps: { label: string; state: 'done' | 'now' | 'stop' | 'todo'; note?: string }[] = [
    { label: 'Requested', state: 'done', note: shortDateTime(r.requestedAt) },
    approved ? { label: 'Approved', state: 'done', note: shortDateTime(r.decidedAt) }
      : r.status === 'REQUESTED' ? { label: 'Awaiting approval', state: 'now' }
        : { label: STATUS_LABEL[r.status], state: 'stop', note: shortDateTime(r.decidedAt ?? r.expiresAt) },
    r.status === 'APPLIED' ? { label: 'Applied', state: 'done', note: shortDateTime(r.appliedAt) }
      : r.status === 'FAILED' ? { label: 'Could not be applied', state: 'stop' } : { label: 'Applied', state: 'todo' },
  ]
  const mark = { done: '✓', now: '…', stop: '×', todo: '' }
  const cls = { done: 'done', now: 'pending', stop: 'missing', todo: 'pending' }
  return (
    <div className="adm-checks">
      <h3>Lifecycle</h3>
      <ul>{steps.map((s) => (
        <li key={s.label} style={s.state === 'todo' ? { opacity: 0.55 } : undefined}>
          <span className={`adm-check ${cls[s.state]}`} aria-hidden>{mark[s.state]}</span>
          <span className="grow">{s.label}</span>{s.note && <span className="muted small">{s.note}</span>}
        </li>))}</ul>
    </div>
  )
}

function payloadRows(r: ApprovalRequest): [string, string][] {
  const show = (k: string, v: unknown): string => {
    if (v === null || v === undefined || v === '') return k === 'expiresAt' ? 'Permanent' : '—'
    if (k === 'role') return ROLE_LABEL[String(v)] ?? String(v)
    if (k === 'expiresAt') return shortDateTime(String(v))
    if (typeof v === 'boolean') return v ? 'Yes' : 'No'
    return typeof v === 'object' ? JSON.stringify(v) : String(v)
  }
  const names: Record<string, string> = {
    identityId: 'Account', role: 'Role', expiresAt: 'Access ends', key: 'Switch', paused: 'Pause', itemKind: 'Item', itemId: 'Item reference',
    outcome: 'Outcome', note: 'What happened', failureId: 'Delivery failure', scope: 'Scope', format: 'Format', exportId: 'Export',
  }
  return Object.entries(r.payload).map(([k, v]) => [names[k] ?? k, show(k, v)])
}

function RequestDetail({ r, now, onClose, onDecide, onCancel }: {
  r: ApprovalRequest; now: number; onClose: () => void; onDecide: (approve: boolean, note: string) => void; onCancel: () => void
}) {
  const [note, setNote] = useState('')
  const due = countdown(r.expiresAt, now)
  const open = r.status === 'REQUESTED'
  return (
    <DetailPanel title={KIND_LABEL[r.kind]} subtitle={r.summary} badge={<LifecyclePill status={r.status} />} onClose={onClose}
      footer={open && (r.canDecide || r.canCancel) ? <>
        {r.canDecide && <>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => onDecide(true, note)}>Approve and apply</button>
          <button type="button" className="btn btn-secondary btn-sm" style={{ color: 'var(--zk-danger)' }} disabled={note.trim().length < 5}
            title={note.trim().length < 5 ? 'Say why you are rejecting it' : undefined} onClick={() => onDecide(false, note)}>Reject</button>
        </>}
        {r.canCancel && <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel request</button>}
      </> : undefined}>
      {open && (r.canDecide
        ? <Callout tone="amber" title={`Your decision · ${due.text}`}>Approving carries this out immediately and is recorded with your name. You will be asked
            for a fresh two-step code.</Callout>
        : <Callout tone="blue" title={`Awaiting approval · ${due.text}`}>Waiting for another {approverText(r.approverRoles)}
            {r.canCancel ? ' (you asked for it, so you cannot approve it)' : ''}. Nothing changes until it is approved.</Callout>)}
      {r.status === 'APPLIED' && <Callout tone="green" title="Applied">Approved by {who(r.decidedBy)} and carried out {shortDateTime(r.appliedAt)}.</Callout>}
      {r.status === 'FAILED' && <Callout tone="red" title="Approved, but not applied">{r.applyError ?? 'The action could not be carried out.'} Nothing was changed.</Callout>}
      {(r.status === 'REJECTED' || r.status === 'EXPIRED' || r.status === 'CANCELLED') && <Callout tone="red" title={STATUS_LABEL[r.status]}>
        {r.status === 'EXPIRED' ? 'Nobody decided it in time.' : r.status === 'CANCELLED' ? 'Withdrawn by the requester.' : `Rejected by ${who(r.decidedBy)}.`} The action was never
        carried out.</Callout>}
      <div className="adm-facts"><h3>Justification</h3><p className="small" style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{r.justification}</p></div>
      <Lifecycle r={r} />
      <Facts title="Request" rows={[
        ['Requested by', <span key="rb">{who(r.requestedBy)}{r.requestedBy.email && r.requestedBy.displayName ? <span className="cell-sub">{r.requestedBy.email}</span> : null}</span>],
        ['Requested', shortDateTime(r.requestedAt)],
        ['Expires', open ? <span key="ex" className={due.late ? 'late' : ''}>{shortDateTime(r.expiresAt)} · {due.text}</span> : shortDateTime(r.expiresAt)],
        ['May approve', r.approverRoles.map((x) => ROLE_LABEL[x] ?? x).join(' or ')],
        ...(r.decidedBy ? [['Decided by', `${who(r.decidedBy)} · ${shortDateTime(r.decidedAt)}`] as [string, string]] : []),
        ...(r.decisionNote ? [['Decision note', r.decisionNote] as [string, string]] : []),
      ]} />
      <Facts title="What will be done" rows={payloadRows(r)} />
      {r.result && <Facts title="Result" rows={Object.entries(r.result).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : String(v)])} />}
      {open && r.canDecide && <label className="small" style={{ display: 'grid', gap: 4 }}>Decision note (required to reject)
        <textarea className="input" rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></label>}
    </DetailPanel>
  )
}
