import { useCallback, useEffect, useState } from 'react'
import { adminConsoleApi, type AdminContract, type AdminContractSummary } from '../../api/adminConsole'
import { AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, HBars, KpiStrip, ListDetail, MetricList,
  Panel, PanelRow, Pill, Progress, StackBar, StatusPill, TableFoot, dueText, money, shortDate, pickRow, useSelectedParam } from '../../components/admin'
import { ErrorAlert } from '../../components/ui'
import { CONTRACT_COLOR, CONTRACT_LABEL, CONTRACT_ORDER, MILESTONE_COLOR, MILESTONE_LABEL, MILESTONE_ORDER, currentMilestone, fundingState,
  msLabel, nextAction, orderedEntries, route, sortedMilestones, useCursorList, useDebounced } from './staffData'

/* Contracts & Milestones (design 55): agreement execution, versioned obligations, milestone delivery and funding position.
   Counts come from /v1/admin/contracts/summary; rows from /v1/admin/contracts. */

type Tab = '' | 'PENDING_SIGNATURE' | 'ACTIVE' | 'DISPUTED' | 'COMPLETED' | 'TERMINATED'

export default function ContractsMilestones() {
  const [error, setError] = useState<unknown>(null)
  const [summary, setSummary] = useState<AdminContractSummary | null>(null)
  const [tab, setTab] = useState<Tab>('')
  const [search, setSearch] = useState('')
  const [milestone, setMilestone] = useState('')
  const q = useDebounced(search.trim())
  const [selectedId, setSelectedId] = useState<string | null>(null)
  useSelectedParam(setSelectedId)
  const [detailTab, setDetailTab] = useState('Overview')

  useEffect(() => { adminConsoleApi.contractSummary().then(setSummary).catch(setError) }, [])
  const load = useCallback((cursor: string | null) => adminConsoleApi.contracts({ q, status: tab, cursor }), [q, tab])
  const list = useCursorList(load, setError)
  // The milestone filter narrows the loaded rows to contracts whose current milestone is in that state.
  const rows = (list.rows ?? []).filter((c) => !milestone || currentMilestone(c)?.status === milestone)
  const selected = rows.find((r) => r.id === selectedId) ?? null

  const by = summary?.byStatus ?? {}
  const ms = summary?.milestonesByStatus ?? {}
  const n = (v: number | undefined) => (summary ? (v ?? 0) : '—')
  const msTotal = Object.values(ms).reduce((s, v) => s + v, 0)

  return (
    <>
      <AdminHeader crumb="Engagement operations / Agreements & delivery control" title="Contracts & Milestones"
        subtitle="Govern agreement execution, versioned obligations, milestone delivery, buyer acceptance and protected-payment readiness." />
      <ErrorAlert error={error} />
      <KpiStrip>
        <AdminKpi icon="contract" tone="blue" label="Contracts in scope" value={n(summary?.total)} sub="All agreements" />
        <AdminKpi icon="clock" tone="amber" label="Awaiting signatures" value={n(by.PENDING_SIGNATURE)} sub="Not yet executed" />
        <AdminKpi icon="shield" tone="green" label="Executed · in delivery" value={n(by.ACTIVE)} sub="Active signed agreements" />
        <AdminKpi icon="arrow" tone="violet" label="Submitted milestones" value={n(ms.SUBMITTED)} sub="Awaiting buyer decision" />
        <AdminKpi icon="alert" tone="red" label="Disputed milestones" value={n(ms.DISPUTED)} sub={summary ? `${summary.openDisputes} open disputes` : undefined} />
        <AdminKpi icon="check" tone="teal" label="Acceptance awaiting approval" value={n(ms.ACCEPTANCE_PENDING_APPROVAL)} sub="Accepted, approval required" />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Agreement lifecycle distribution" meta={summary ? `${summary.total} contracts · one current state each` : undefined}>
          <StackBar segments={orderedEntries(by, CONTRACT_ORDER).map(([k, v]) => ({ label: CONTRACT_LABEL[k] ?? k, value: v, color: CONTRACT_COLOR[k] }))} />
        </Panel>
        <Panel title="Milestone delivery & disposition" meta={summary ? `${msTotal} milestone records` : undefined}>
          <HBars rows={orderedEntries(ms, MILESTONE_ORDER).map(([k, v]) => ({ label: MILESTONE_LABEL[k] ?? k, value: v, color: MILESTONE_COLOR[k] }))} />
          <p className="adm-foot-note">Accepted is not released: payment release is a separate step.</p>
        </Panel>
        <Panel title="Attention required" meta="May overlap">
          <MetricList rows={[
            { label: 'Signature completion outstanding', value: n(by.PENDING_SIGNATURE), tone: by.PENDING_SIGNATURE ? 'amber' : undefined },
            { label: 'Disputed milestone holds', value: n(ms.DISPUTED), tone: ms.DISPUTED ? 'red' : undefined },
            { label: 'Buyer decision on submitted work', value: n(ms.SUBMITTED), tone: ms.SUBMITTED ? 'amber' : undefined },
            { label: 'Revisions requested', value: n(ms.REVISION_REQUESTED) },
            { label: 'Milestones awaiting funding', value: n(ms.PENDING_FUNDING) },
          ]} />
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs<Tab> value={tab} onChange={(t) => { setTab(t); setSelectedId(null) }} tabs={[
              { key: '', label: 'All contracts', count: summary?.total },
              { key: 'ACTIVE', label: 'Executed', count: summary ? by.ACTIVE ?? 0 : null },
              { key: 'PENDING_SIGNATURE', label: 'Signature queue', count: summary ? by.PENDING_SIGNATURE ?? 0 : null },
              { key: 'DISPUTED', label: 'Held', count: summary ? by.DISPUTED ?? 0 : null },
              { key: 'COMPLETED', label: 'Completed', count: summary ? by.COMPLETED ?? 0 : null },
              { key: 'TERMINATED', label: 'Terminated', count: summary ? by.TERMINATED ?? 0 : null },
            ]} />
            <FilterBar search={search} onSearch={setSearch} placeholder="Search contract, buyer or professional…">
              <FilterSelect label="Current milestone" value={milestone} onChange={setMilestone}
                options={MILESTONE_ORDER.filter((k) => k !== 'ACCEPTED' && k !== 'CANCELLED').map((k) => [k, MILESTONE_LABEL[k]])} />
            </FilterBar>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th scope="col">Contract</th><th scope="col">Buyer / professional</th><th scope="col">Jurisd.</th><th scope="col">Agreement</th><th scope="col">Milestone</th><th scope="col">Funding state</th><th scope="col">Next action / due</th></tr></thead>
                <tbody>
                  {list.rows && rows.length === 0 && <tr><td colSpan={7} className="empty-row">No contracts match.</td></tr>}
                  {!list.rows && !error && <tr><td colSpan={7} className="empty-row">Loading…</td></tr>}
                  {rows.map((c) => {
                    const cur = currentMilestone(c)
                    const next = nextAction(c)
                    const due = dueText(next.due)
                    const f = fundingState(c)
                    return (
                      <tr {...pickRow} key={c.id} className={`pick ${selectedId === c.id ? 'selected' : ''}`} onClick={() => setSelectedId(c.id)}>
                        <td><div className="cell-id">{c.title}</div><div className="cell-sub">{money(c.totalMinor, c.currency)}</div></td>
                        <td><div className="cell-main">{c.buyer.name}</div><div className="cell-sub">{c.professional.name}</div></td>
                        <td className="small">{route(c)}</td>
                        <td><StatusPill status={c.status} /><div className="cell-sub">v{c.version}</div></td>
                        <td>{cur ? <Pill tone={cur.status === 'DISPUTED' ? 'red' : cur.status === 'PENDING_FUNDING' ? 'grey' : 'amber'}>{msLabel(cur)} · {MILESTONE_LABEL[cur.status] ?? cur.status}</Pill>
                          : <span className="muted small">{c.milestones.length ? 'All closed' : 'None'}</span>}</td>
                        <td><Pill tone={f.tone}>{f.text}</Pill><div className="cell-sub">{money(c.fundedMinor, c.currency)} funded</div></td>
                        <td className="small">{next.text}{next.due && <div className={`cell-sub ${due.late ? 'late' : ''}`}>Due {shortDate(next.due)} · {due.text}</div>}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <TableFoot shown={rows.length} total={milestone ? null : tab ? (summary ? by[tab] ?? 0 : null) : summary?.total} noun="contracts" />
            {list.hasMore && <div style={{ padding: '0 16px 12px' }}>
              <button type="button" className="btn btn-secondary btn-sm" disabled={list.busy} onClick={list.more}>{list.busy ? 'Loading…' : 'Load more'}</button></div>}
          </div>
        }
        detail={selected && <ContractDetail c={selected} tab={detailTab} onTab={setDetailTab} onClose={() => setSelectedId(null)} />}
      />
    </>
  )
}

function ContractDetail({ c, tab, onTab, onClose }: { c: AdminContract; tab: string; onTab: (t: string) => void; onClose: () => void }) {
  const list = sortedMilestones(c)
  const accepted = list.filter((m) => m.status === 'ACCEPTED').length
  const counts = list.reduce<Record<string, number>>((a, m) => ({ ...a, [m.status]: (a[m.status] ?? 0) + 1 }), {})
  const cur = currentMilestone(c)
  const outstanding = Math.max(0, c.totalMinor - c.fundedMinor)
  return (
    <DetailPanel title={c.title} subtitle={`${c.buyer.name} → ${c.professional.name} · ${route(c)}`} badge={<StatusPill status={c.status} />}
      onClose={onClose} tabs={{ tabs: ['Overview', 'Milestones'], value: tab, onChange: onTab }}>
      {c.hasOpenDispute && <Callout tone="red" title="Dispute open">Funds tied to the disputed milestone stay on hold until the dispute is decided.</Callout>}
      {!c.hasOpenDispute && cur?.status === 'SUBMITTED' && <Callout tone="amber" title={`${msLabel(cur)} submitted`}>Waiting for the buyer to accept or request a revision.</Callout>}
      {tab === 'Overview' && <>
        <Facts rows={[
          ['Agreement version', `v${c.version}`],
          ['Signed', c.signedAt ? shortDate(c.signedAt) : 'Not signed'],
          ['Governing parties', route(c)],
          ['Created', shortDate(c.createdAt)],
          ['Last updated', shortDate(c.updatedAt)],
        ]} />
        <div className="adm-mini-stats">
          <div><div className="lbl">Contract value</div><div className="val">{money(c.totalMinor, c.currency)}</div></div>
          <div><div className="lbl">Funded</div><div className="val">{money(c.fundedMinor, c.currency)}</div></div>
          <div><div className="lbl">Released</div><div className="val">{money(c.releasedMinor, c.currency)}</div></div>
          <div><div className="lbl">Not yet funded</div><div className="val">{money(outstanding, c.currency)}</div></div>
        </div>
      </>}
      <div className="adm-checks">
        <h3>Milestone schedule <span className="muted small">· {Object.entries(counts).map(([k, v]) => `${v} ${(MILESTONE_LABEL[k] ?? k).toLowerCase()}`).join(' · ') || 'none'}</span></h3>
        {list.length > 0 && <Progress value={accepted} max={list.length} />}
        <MetricList rows={list.map((m) => ({
          label: <>{msLabel(m)} · {m.title}{tab === 'Milestones' && <div className="cell-sub">{money(m.amountMinor, c.currency)} · {m.dueDate ? `due ${shortDate(m.dueDate)}` : 'no due date'}</div>}</>,
          value: <StatusPill status={m.status} />,
        }))} />
      </div>
    </DetailPanel>
  )
}
