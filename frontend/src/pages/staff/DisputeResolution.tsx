import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CATEGORIES, CATEGORY_LABEL, disputeApi, OPEN_PHASES, OUTCOME_LABEL, PHASE, type Dispute, type DisputeStatus } from '../../api/disputes'
import { formatMoney } from '../../api/orgs'
import {
  AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, KpiStrip, ListDetail,
  MetricList, Panel, PanelRow, Pill, Progress, TableFoot, TrendChart, dueText, shortDate, shortDateTime, type CheckState, type PillTone,
} from '../../components/admin'
import { Icon } from '../../components/dashboard'
import { ErrorAlert } from '../../components/ui'
import { formatCurrencies, sumByCurrency } from '../../lib/money'

/* Dispute Resolution (staff design 52). Replaces the operator list of DisputesPage. The case itself is still worked on
   /app/disputes/:id (DisputeDetail); this screen is the queue, intake and protected-funds overview. Amounts are always
   shown per currency and never added across currencies. */

const PHASE_TONE: Record<DisputeStatus, PillTone> = {
  EVIDENCE_COLLECTION: 'amber', DIRECT_RESOLUTION: 'blue', MEDIATION: 'violet', DECIDED: 'green', ENFORCED: 'green', CLOSED: 'grey',
}
const PHASES: DisputeStatus[] = ['EVIDENCE_COLLECTION', 'DIRECT_RESOLUTION', 'MEDIATION', 'DECIDED', 'ENFORCED', 'CLOSED']
const DAY = 86_400_000
type Tab = 'open' | DisputeStatus | 'needsMediator' | 'all'

const deadlineOf = (d: Dispute) => d.status === 'EVIDENCE_COLLECTION' ? d.evidenceDeadline : d.status === 'DIRECT_RESOLUTION' ? d.directDeadline : null

export default function DisputeResolution() {
  const [list, setList] = useState<Dispute[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [tab, setTab] = useState<Tab>('open')
  const [q, setQ] = useState('')
  const [category, setCategory] = useState('')
  const [currency, setCurrency] = useState('')
  const [page, setPage] = useState(1)
  const [selId, setSelId] = useState<string | null>(null)
  const [loadedAt, setLoadedAt] = useState<Date | null>(null)
  const load = () => disputeApi.list('operator').then((rows) => { setList(rows); setLoadedAt(new Date()) }).catch(setError)
  useEffect(() => { disputeApi.list('operator').then((rows) => { setList(rows); setLoadedAt(new Date()) }).catch(setError) }, [])

  const rows = list ?? []
  const open = rows.filter((d) => OPEN_PHASES.includes(d.status))
  const by = (s: DisputeStatus) => rows.filter((d) => d.status === s).length
  const needsMediator = rows.filter((d) => d.status === 'MEDIATION' && !d.mediatorAssigned)
  const now = loadedAt ? loadedAt.getTime() : 0  // figures are as of the last load
  const since30 = now - 30 * DAY
  const closed30 = rows.filter((d) => d.closedAt && new Date(d.closedAt).getTime() >= since30).length
  const deadlineSoon = open.filter((d) => { const dl = deadlineOf(d); return dl && new Date(dl).getTime() - now < 2 * DAY }).length
  const currencies = [...new Set(rows.map((d) => d.disputed.currency))].sort()

  // Intake: disputes opened per day over the last 30 days.
  const days = Array.from({ length: 30 }, (_, i) => new Date(now - (29 - i) * DAY))
  const key = (t: Date) => t.toISOString().slice(0, 10)
  const intake = new Map(days.map((t) => [key(t), 0]))
  for (const d of rows) { const k = key(new Date(d.createdAt)); if (intake.has(k)) intake.set(k, (intake.get(k) ?? 0) + 1) }
  const intakeTotal = [...intake.values()].reduce((a, b) => a + b, 0)

  const term = q.trim().toLowerCase()
  const filtered = rows.filter((d) => (tab === 'all' ? true : tab === 'open' ? OPEN_PHASES.includes(d.status)
    : tab === 'needsMediator' ? d.status === 'MEDIATION' && !d.mediatorAssigned : d.status === tab)
    && (!category || d.category === category) && (!currency || d.disputed.currency === currency)
    && (!term || `${d.reference} ${d.contractReference} ${d.summary}`.toLowerCase().includes(term)))
  const PER = 25
  const pages = Math.max(1, Math.ceil(filtered.length / PER))
  const shown = filtered.slice((page - 1) * PER, page * PER)
  const selected = rows.find((d) => d.id === selId) ?? null

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: 'open', label: 'Active', count: open.length },
    { key: 'EVIDENCE_COLLECTION', label: 'Evidence', count: by('EVIDENCE_COLLECTION') },
    { key: 'DIRECT_RESOLUTION', label: 'Direct resolution', count: by('DIRECT_RESOLUTION') },
    { key: 'MEDIATION', label: 'Mediation', count: by('MEDIATION') },
    { key: 'needsMediator', label: 'Needs a mediator', count: needsMediator.length },
    { key: 'DECIDED', label: 'Decided', count: by('DECIDED') },
    { key: 'ENFORCED', label: 'Enforced', count: by('ENFORCED') },
    { key: 'CLOSED', label: 'Closed', count: by('CLOSED') },
    { key: 'all', label: 'All', count: rows.length },
  ]
  const frozen = sumByCurrency(open.map((d) => d.disputed))
  const v = (n: number) => (list ? n : '…')

  return (
    <>
      <AdminHeader crumb="Trust, risk & compliance / Independent dispute governance" title="Dispute Resolution"
        subtitle="Manage engagement disputes through evidence exchange, mediation, impartial decisions, and controlled payment execution."
        actions={<button type="button" className="btn btn-secondary" onClick={load}><Icon name="refresh" /> Refresh</button>}
        meta={<>{loadedAt && <span>Last loaded {loadedAt.toLocaleTimeString()}</span>}<span>Currencies not aggregated</span></>} />
      <ErrorAlert error={error} />

      <KpiStrip>
        <AdminKpi icon="scale" tone="blue" label="Active disputes" value={v(open.length)} sub="Evidence, direct resolution or mediation" />
        <AdminKpi icon="folder" tone="amber" label="Evidence exchange" value={v(by('EVIDENCE_COLLECTION'))} sub="Waiting for both parties" />
        <AdminKpi icon="compare" tone="teal" label="Direct resolution" value={v(by('DIRECT_RESOLUTION'))} sub="Structured proposals" />
        <AdminKpi icon="team" tone="violet" label="In mediation" value={v(by('MEDIATION'))} sub={`${list ? needsMediator.length : '…'} need a mediator`} />
        <AdminKpi icon="clock" tone="red" label="Deadline within 48h" value={v(deadlineSoon)} sub="Evidence or direct-resolution window" />
        <AdminKpi icon="check" tone="green" label="Closed / 30 days" value={v(closed30)} sub="Decided and executed" />
      </KpiStrip>

      <div className="card" style={{ padding: '12px 16px', marginBottom: 16, display: 'flex', gap: 10, alignItems: 'center' }}>
        <span className="kpi-icon green" style={{ width: 28, height: 28 }}><Icon name="check" /></span>
        <span className="small"><strong>Separation of duties:</strong> funds stay frozen until a decision is executed; a platform decision needs the
          mediator and a second reviewer with the Legal role. AI never decides.</span>
      </div>

      <PanelRow cols={3}>
        <Panel title="Case intake / last 30 days" meta={`${intakeTotal} opened`}>
          {!list ? <p className="muted small">Loading…</p> : <TrendChart kind="bar" height={140} labels={days.map((t) => t.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }))}
            series={[{ label: 'Disputes opened', values: [...intake.values()], color: '#12b76a' }]} />}
        </Panel>
        <Panel title="Lifecycle" meta={`${rows.length} cases`}>
          <div className="adm-mini-stats">{PHASES.map((s) => (
            <div key={s}><div className="val">{by(s)}</div><div className="lbl">{PHASE[s].label}</div>
              <div style={{ marginTop: 6 }}><Progress value={by(s)} max={Math.max(1, rows.length)} tone={s === 'EVIDENCE_COLLECTION' ? 'amber' : s === 'MEDIATION' || s === 'DIRECT_RESOLUTION' ? 'blue' : 'green'} /></div></div>))}
          </div>
        </Panel>
        <Panel title="Protected funds" meta="Frozen in open disputes, by currency">
          {frozen.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No funds frozen.</p>
            : <MetricList rows={frozen.map((m) => ({ label: `${m.currency} · ${open.filter((d) => d.disputed.currency === m.currency).length} open`, value: formatMoney(m) }))} />}
          <MetricList rows={[
            { label: 'Referred to arbitration', value: rows.filter((d) => d.arbitration && OPEN_PHASES.includes(d.status)).length },
            { label: 'Platform decision awaiting Legal', value: rows.filter((d) => d.pendingDecision).length, tone: rows.some((d) => d.pendingDecision) ? 'amber' : undefined },
            { label: 'Records on legal hold', value: rows.filter((d) => d.legalHold).length },
          ]} />
        </Panel>
      </PanelRow>

      <ListDetail list={
        <div className="card">
          <CountTabs tabs={tabs} value={tab} onChange={(t) => { setTab(t); setPage(1) }} />
          <FilterBar search={q} onSearch={(s) => { setQ(s); setPage(1) }} placeholder="Search case, engagement or summary…">
            <FilterSelect label="Category" value={category} onChange={(s) => { setCategory(s); setPage(1) }} options={CATEGORIES} />
            <FilterSelect label="Currency" value={currency} onChange={(s) => { setCurrency(s); setPage(1) }} options={currencies.map((c) => [c, c])} />
          </FilterBar>
          <div className="adm-note">{open.length} active cases · {needsMediator.length} need a mediator · frozen {formatCurrencies(open.map((d) => d.disputed))}</div>
          <div className="adm-table-wrap">
            <table className="data">
              <thead><tr><th>Case</th><th>Engagement</th><th>Dispute type</th><th>Amount</th><th>Stage</th><th>Due date</th><th>Opened</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {!list && !error && <tr><td colSpan={8} className="empty-row"><span role="status">Loading disputes…</span></td></tr>}
                {list && filtered.length === 0 && <tr><td colSpan={8} className="empty-row">{rows.length ? 'No disputes match these filters.' : 'No disputes. Cases appear here when a party opens one.'}</td></tr>}
                {shown.map((d) => {
                  const dl = deadlineOf(d)
                  const due = dl ? dueText(dl) : null
                  return (
                    <tr key={d.id} className={`pick ${selId === d.id ? 'selected' : ''}`} onClick={() => setSelId(d.id)}>
                      <td><div className="cell-id">{d.reference}</div><div className="cell-sub clamp">{d.summary}</div></td>
                      <td className="small">{d.contractReference}</td>
                      <td className="small">{CATEGORY_LABEL[d.category]}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>{d.disputed.currency} {formatMoney(d.disputed)}</td>
                      <td><Pill tone={PHASE_TONE[d.status]}>{PHASE[d.status].label}</Pill>
                        {d.status === 'MEDIATION' && !d.mediatorAssigned && <div className="cell-sub late">Needs a mediator</div>}</td>
                      <td>{dl ? <><div>{shortDate(dl)}</div><div className={`cell-sub ${due?.late ? 'late' : ''}`}>{due?.text}</div></> : '—'}</td>
                      <td className="small">{shortDate(d.createdAt)}</td>
                      <td style={{ textAlign: 'right' }}><Link className="btn btn-secondary btn-sm" to={`/app/disputes/${d.id}`} onClick={(e) => e.stopPropagation()}>Open case</Link></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <TableFoot shown={shown.length} total={filtered.length} noun="cases" page={page} pages={pages} onPage={setPage} />
        </div>
      } detail={selected && <DisputeSummary key={selected.id} d={selected} onClose={() => setSelId(null)} />} />
    </>
  )
}

function DisputeSummary({ d, onClose }: { d: Dispute; onClose: () => void }) {
  const dl = deadlineOf(d)
  const isOpen = OPEN_PHASES.includes(d.status)
  const readiness: { label: string; state: CheckState; note?: string }[] = [
    { label: 'Buyer evidence', state: d.evidenceComplete.includes('BUYER') ? 'done' : 'pending', note: d.evidenceComplete.includes('BUYER') ? 'Complete' : 'Pending' },
    { label: 'Professional evidence', state: d.evidenceComplete.includes('PROFESSIONAL') ? 'done' : 'pending', note: d.evidenceComplete.includes('PROFESSIONAL') ? 'Complete' : 'Pending' },
  ]
  if (d.status === 'MEDIATION' || d.mediatorAssigned) readiness.push({ label: 'Neutral mediator', state: d.mediatorAssigned ? 'done' : 'missing', note: d.mediatorAssigned ? 'Assigned' : 'Unassigned' })
  if (d.recommendation) readiness.push({ label: 'Mediator recommendation', state: d.recommendation.rejectedBy?.length ? 'missing' : (d.recommendation.acceptedBy?.length ?? 0) >= 2 ? 'done' : 'pending',
    note: d.recommendation.rejectedBy?.length ? 'Declined' : `${d.recommendation.acceptedBy?.length ?? 0} of 2 accepted` })
  if (d.pendingDecision) readiness.push({ label: 'Second reviewer (Legal)', state: 'pending', note: 'Awaiting approval' })
  if (d.decision) readiness.push({ label: 'Decision issued', state: 'done', note: d.decision.decisionPath.toLowerCase() })
  const evidenceBy = (p: string) => d.evidence.filter((e) => e.party === p).length

  return (
    <DetailPanel title={d.reference} subtitle={<>Engagement {d.contractReference} · {CATEGORY_LABEL[d.category]}</>}
      badge={<Pill tone={PHASE_TONE[d.status]}>{PHASE[d.status].label}</Pill>} onClose={onClose}
      footer={<Link className="btn btn-primary btn-sm" to={`/app/disputes/${d.id}`}>Open case <Icon name="arrow" /></Link>}>
      {isOpen ? <Callout tone="amber" title="Open matter · funds frozen">{d.nextStep}</Callout>
        : <Callout tone="green" title={d.decision ? `Decision: ${OUTCOME_LABEL[d.decision.outcome]}` : PHASE[d.status].label}>{d.decision?.plainSummary ?? d.nextStep}</Callout>}
      <p className="small" style={{ margin: 0 }}>{d.summary}</p>
      <div className="adm-mini-stats">
        <div><div className="lbl">Frozen in escrow</div><div className="val" style={{ fontSize: 17 }}>{formatMoney(d.disputed)}</div><div className="cell-sub">{d.disputed.currency}</div></div>
        <div><div className="lbl">Milestones</div><div className="val" style={{ fontSize: 17 }}>{d.milestones.length}</div><div className="cell-sub">in dispute</div></div>
      </div>
      <Facts title="Case" rows={[
        ['Raised by', d.initiatorParty === 'BUYER' ? 'Buyer' : d.initiatorParty === 'PROFESSIONAL' ? 'Professional' : 'Platform'],
        ['Desired outcome', OUTCOME_LABEL[d.desiredOutcome]],
        ['Opened', shortDateTime(d.createdAt)],
        ['Current deadline', dl ? `${shortDateTime(dl)} · ${dueText(dl).text}` : '—'],
        ['Evidence items', `${evidenceBy('BUYER')} buyer · ${evidenceBy('PROFESSIONAL')} professional`],
        ['Proposals', d.proposals.length],
        ...(d.arbitration ? [['Arbitration', `${d.arbitration.forum} · ${shortDate(d.arbitration.referredAt)}`] as [string, string]] : []),
        ...(d.retainUntil ? [['Retained until', `${shortDate(d.retainUntil)}${d.legalHold ? ' · legal hold' : ''}`] as [string, string]] : []),
      ]} />
      <div>
        <h3 style={{ fontSize: 13.5, margin: '0 0 6px' }}>Milestones</h3>
        <ul className="adm-metrics">{d.milestones.map((m) => <li key={m.id}><span>M{m.sequence} {m.title}</span><strong>{formatMoney(m.amount)}</strong></li>)}</ul>
      </div>
      <Checklist title="Evidence and neutrality readiness" items={readiness} />
      {(d.mediationRequired || d.legalReviewRequired) && <Callout tone="blue" title="Buyer organisation policy">
        {d.mediationRequired ? 'A mediator handles any settlement of this size. ' : ''}{d.legalReviewRequired ? "The organisation's Legal Reviewer must agree to its settlement." : ''}</Callout>}
    </DetailPanel>
  )
}
