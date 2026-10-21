import { useCallback, useEffect, useState } from 'react'
import { adminConsoleApi, type AdminContract, type AdminContractSummary } from '../../api/adminConsole'
import { AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, KpiStrip, ListDetail, MetricList, Panel,
  PanelRow, Pill, StackBar, StatusPill, TableFoot, dueText, money, shortDate, type CheckState } from '../../components/admin'
import { ErrorAlert } from '../../components/ui'
import { CONTRACT_COLOR, CONTRACT_LABEL, CONTRACT_ORDER, MILESTONE_LABEL, MILESTONE_ORDER, currentMilestone, fundingState, msLabel,
  nextAction, orderedEntries, route, sortedMilestones, useCursorList, useDebounced } from './staffData'

/* Engagement Oversight (design 54): every engagement from signature to closeout, with the pre-work gates that must hold
   before delivery starts. Counts come from /v1/admin/contracts/summary; rows from /v1/admin/contracts. */

type Tab = '' | 'PENDING_SIGNATURE' | 'ACTIVE' | 'DISPUTED' | 'COMPLETED' | 'TERMINATED'

function gates(c: AdminContract): { label: string; state: CheckState; note: string }[] {
  const first = sortedMilestones(c)[0]
  const firstFunded = !!first && first.status !== 'PENDING_FUNDING'
  return [
    { label: 'Agreement signed by both parties', state: c.signedAt ? 'done' : 'missing', note: c.signedAt ? 'Signed' : 'Not signed' },
    { label: 'Milestones defined', state: c.milestones.length ? 'done' : 'missing', note: c.milestones.length ? `${c.milestones.length}` : 'None' },
    { label: 'First milestone funded', state: firstFunded ? 'done' : c.signedAt ? 'pending' : 'missing', note: firstFunded ? 'Funded' : 'Not funded' },
    { label: 'Contract fully funded', state: c.fundedMinor >= c.totalMinor && c.totalMinor > 0 ? 'done' : 'pending',
      note: `${money(c.fundedMinor, c.currency)} of ${money(c.totalMinor, c.currency)}` },
    { label: 'No open dispute', state: c.hasOpenDispute ? 'missing' : 'done', note: c.hasOpenDispute ? 'Dispute open' : 'Clear' },
  ]
}

export default function EngagementOversight() {
  const [error, setError] = useState<unknown>(null)
  const [summary, setSummary] = useState<AdminContractSummary | null>(null)
  const [tab, setTab] = useState<Tab>('')
  const [search, setSearch] = useState('')
  const q = useDebounced(search.trim())
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState('Overview')

  useEffect(() => { adminConsoleApi.contractSummary().then(setSummary).catch(setError) }, [])
  const load = useCallback((cursor: string | null) => adminConsoleApi.contracts({ q, status: tab, cursor }), [q, tab])
  const list = useCursorList(load, setError)
  const rows = list.rows ?? []
  const selected = rows.find((r) => r.id === selectedId) ?? null

  const by = summary?.byStatus ?? {}
  const ms = summary?.milestonesByStatus ?? {}
  const n = (v: number | undefined) => (summary ? (v ?? 0) : '—')
  const awaitingAcceptance = summary ? (ms.SUBMITTED ?? 0) + (ms.ACCEPTANCE_PENDING_APPROVAL ?? 0) : null

  return (
    <>
      <AdminHeader crumb="Engagement operations / Lifecycle governance" title="Engagement Oversight"
        subtitle="Monitor engagements from executed agreement through protected funding, delivery, acceptance and closeout." />
      <ErrorAlert error={error} />
      <KpiStrip>
        <AdminKpi icon="briefcase" tone="blue" label="Engagements in scope" value={n(summary?.total)} sub="All contracts on the platform" />
        <AdminKpi icon="contract" tone="amber" label="Awaiting signatures" value={n(by.PENDING_SIGNATURE)} sub="Agreement not yet executed" />
        <AdminKpi icon="wallet" tone="red" label="Funding pending" value={n(ms.PENDING_FUNDING)} sub="Milestones awaiting funding" />
        <AdminKpi icon="pulse" tone="green" label="Active delivery" value={n(by.ACTIVE)} sub="Signed, in delivery" />
        <AdminKpi icon="check" tone="teal" label="Awaiting acceptance" value={awaitingAcceptance ?? '—'} sub="Milestones submitted or awaiting approval" />
        <AdminKpi icon="scale" tone="violet" label="Open disputes" value={n(summary?.openDisputes)} sub="Engagements with a live dispute" />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Engagement lifecycle distribution" meta={summary ? `${summary.total} contracts · one current state each` : undefined}>
          <StackBar segments={orderedEntries(by, CONTRACT_ORDER).map(([k, v]) => ({ label: CONTRACT_LABEL[k] ?? k, value: v, color: CONTRACT_COLOR[k] }))} />
        </Panel>
        <Panel title="Governance exceptions" meta="Platform-wide">
          <MetricList rows={[
            { label: 'Open disputes', value: n(summary?.openDisputes), tone: summary?.openDisputes ? 'red' : undefined },
            { label: 'Agreements not signed', value: n(by.PENDING_SIGNATURE), tone: by.PENDING_SIGNATURE ? 'amber' : undefined },
            { label: 'Milestones not funded', value: n(ms.PENDING_FUNDING), tone: ms.PENDING_FUNDING ? 'amber' : undefined },
            { label: 'Disputed milestones', value: n(ms.DISPUTED), tone: ms.DISPUTED ? 'red' : undefined },
          ]} />
        </Panel>
        <Panel title="Milestone stages" meta="All milestones">
          <MetricList rows={orderedEntries(ms, MILESTONE_ORDER).map(([k, v]) => ({ label: MILESTONE_LABEL[k] ?? k, value: v }))} />
          {summary && Object.keys(ms).length === 0 && <p className="muted small">No milestones yet.</p>}
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs<Tab> value={tab} onChange={(t) => { setTab(t); setSelectedId(null) }} tabs={[
              { key: '', label: 'All engagements', count: summary?.total },
              { key: 'PENDING_SIGNATURE', label: 'Pre-work', count: summary ? by.PENDING_SIGNATURE ?? 0 : null },
              { key: 'ACTIVE', label: 'Active', count: summary ? by.ACTIVE ?? 0 : null },
              { key: 'DISPUTED', label: 'Disputed', count: summary ? by.DISPUTED ?? 0 : null },
              { key: 'COMPLETED', label: 'Completed', count: summary ? by.COMPLETED ?? 0 : null },
              { key: 'TERMINATED', label: 'Terminated', count: summary ? by.TERMINATED ?? 0 : null },
            ]} />
            <FilterBar search={search} onSearch={setSearch} placeholder="Search engagement, buyer or professional…" />
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th>Engagement / buyer</th><th>Professional</th><th>Jurisdiction</th><th>Stage</th><th>Next action</th><th>Due</th></tr></thead>
                <tbody>
                  {list.rows && rows.length === 0 && <tr><td colSpan={6} className="empty-row">No engagements match.</td></tr>}
                  {!list.rows && !error && <tr><td colSpan={6} className="empty-row">Loading…</td></tr>}
                  {rows.map((c) => {
                    const next = nextAction(c)
                    const due = dueText(next.due)
                    return (
                      <tr key={c.id} className={`pick ${selectedId === c.id ? 'selected' : ''}`} onClick={() => setSelectedId(c.id)}>
                        <td><div className="cell-id">{c.title}</div><div className="cell-sub">{c.buyer.name}</div></td>
                        <td><div className="cell-main">{c.professional.name}</div></td>
                        <td className="small">{route(c)}</td>
                        <td>{c.hasOpenDispute && c.status !== 'DISPUTED' ? <Pill tone="red">Dispute open</Pill> : <StatusPill status={c.status} />}</td>
                        <td className="small">{next.text}</td>
                        <td className={`small ${due.late ? 'late' : ''}`}>{next.due ? <>{shortDate(next.due)}<div className="cell-sub">{due.text}</div></> : '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <TableFoot shown={rows.length} total={tab ? (summary ? by[tab] ?? 0 : null) : summary?.total} noun="engagements" />
            {list.hasMore && <div style={{ padding: '0 16px 12px' }}>
              <button type="button" className="btn btn-secondary btn-sm" disabled={list.busy} onClick={list.more}>{list.busy ? 'Loading…' : 'Load more'}</button></div>}
          </div>
        }
        detail={selected && <EngagementDetail c={selected} tab={detailTab} onTab={setDetailTab} onClose={() => setSelectedId(null)} />}
      />
    </>
  )
}

function EngagementDetail({ c, tab, onTab, onClose }: { c: AdminContract; tab: string; onTab: (t: string) => void; onClose: () => void }) {
  const g = gates(c)
  const blocked = g.filter((x) => x.state !== 'done')
  const cur = currentMilestone(c)
  const funding = fundingState(c)
  return (
    <DetailPanel title={c.title} subtitle={`${c.buyer.name} ↔ ${c.professional.name} · ${route(c)}`} badge={<StatusPill status={c.status} />}
      onClose={onClose} tabs={{ tabs: ['Overview', 'Milestones'], value: tab, onChange: onTab }}>
      {tab === 'Overview' ? <>
        {blocked.length > 0
          ? <Callout tone={c.hasOpenDispute ? 'red' : 'amber'} title={`${g.length - blocked.length} of ${g.length} gates met`}>
            Outstanding: {blocked.map((b) => b.label.toLowerCase()).join(', ')}.</Callout>
          : <Callout tone="green" title="All pre-work gates met" />}
        <Facts title="Engagement context" rows={[
          ['Buyer', `${c.buyer.name}${c.buyer.country ? ` · ${c.buyer.country}` : ''}`],
          ['Professional', `${c.professional.name}${c.professional.country ? ` · ${c.professional.country}` : ''}`],
          ['Agreement version', `v${c.version}`],
          ['Signed', c.signedAt ? shortDate(c.signedAt) : 'Not signed'],
          ['Contract value', money(c.totalMinor, c.currency)],
          ['Funded', <Pill key="f" tone={funding.tone}>{money(c.fundedMinor, c.currency)} · {funding.text}</Pill>],
          ['Released', money(c.releasedMinor, c.currency)],
          ['Current milestone', cur ? `${msLabel(cur)} · ${MILESTONE_LABEL[cur.status] ?? cur.status}` : '—'],
          ['Created', shortDate(c.createdAt)],
          ['Last updated', shortDate(c.updatedAt)],
        ]} />
        <Checklist title="Pre-work control gates" items={g} />
      </> : (
        <Facts title="Milestone schedule" rows={sortedMilestones(c).map((m) => [
          <span key="l">{msLabel(m)} · {m.title}<div className="cell-sub">{m.dueDate ? `Due ${shortDate(m.dueDate)}` : 'No due date'} · {money(m.amountMinor, c.currency)}</div></span>,
          <StatusPill key="s" status={m.status} />,
        ])} />
      )}
      {tab === 'Milestones' && c.milestones.length === 0 && <p className="muted small">No milestones defined.</p>}
    </DetailPanel>
  )
}
