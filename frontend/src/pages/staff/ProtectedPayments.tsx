import { useCallback, useEffect, useMemo, useState } from 'react'
import { adminConsoleApi, type AdminEscrowRow, type AdminEscrowSummary } from '../../api/adminConsole'
import { ALLOCATION_STATE, escrowApi, type Escrow } from '../../api/escrow'
import { formatMoney } from '../../api/orgs'
import type { IconName, Tone } from '../../components/dashboard'
import { AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Donut, Facts, FilterBar, FilterSelect, KpiStrip, ListDetail,
  MetricList, Panel, PanelRow, StatusPill, TableFoot, money, shortDate, shortDateTime, type CheckState, pickRow } from '../../components/admin'
import { ErrorAlert } from '../../components/ui'
import { useCursorList } from './staffData'

/* Protected Payments (design 58): money held for milestones, by disposition, one currency at a time (amounts in different
   currencies are never added together). Figures from /v1/admin/escrow/summary; rows from /v1/admin/escrow. */

const ORDER = ['UNFUNDED', 'FUNDING', 'HELD', 'RELEASE_PENDING_APPROVAL', 'ON_HOLD', 'PARTIALLY_RELEASED', 'RELEASED', 'REFUNDED']
const META: Record<string, { icon: IconName; tone: Tone; color: string }> = {
  UNFUNDED: { icon: 'clock', tone: 'amber', color: '#98a2b3' }, FUNDING: { icon: 'refresh', tone: 'blue', color: '#9b8afb' },
  HELD: { icon: 'lock', tone: 'green', color: '#12b76a' }, RELEASE_PENDING_APPROVAL: { icon: 'shield', tone: 'violet', color: '#2f80ed' },
  ON_HOLD: { icon: 'alert', tone: 'red', color: '#f04438' }, PARTIALLY_RELEASED: { icon: 'arrow', tone: 'teal', color: '#0e9384' },
  RELEASED: { icon: 'check', tone: 'green', color: '#0b6b4f' }, REFUNDED: { icon: 'download', tone: 'amber', color: '#f79009' },
}
const statusLabel = (s: string) => (ALLOCATION_STATE as Record<string, { label: string }>)[s]?.label ?? s.toLowerCase().replace(/_/g, ' ')
const rank = (s: string) => (ORDER.includes(s) ? ORDER.indexOf(s) : ORDER.length)

/** Provider references are shown shortened: enough to match a provider statement line, not the full identifier. */
const shortRef = (ref: string) => (ref.length > 8 ? `…${ref.slice(-6)}` : ref)

export default function ProtectedPayments() {
  const [error, setError] = useState<unknown>(null)
  const [summary, setSummary] = useState<AdminEscrowSummary | null>(null)
  const [currency, setCurrency] = useState('')
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => { adminConsoleApi.escrowSummary().then(setSummary).catch(setError) }, [])
  const currencies = useMemo(() => [...new Set((summary?.buckets ?? []).map((b) => b.currency))].sort(), [summary])
  // Default to the currency with the most records; the user can switch.
  const cur = currency || (summary ? [...currencies].sort((a, b) =>
    summary.buckets.filter((x) => x.currency === b).reduce((s, x) => s + x.count, 0) - summary.buckets.filter((x) => x.currency === a).reduce((s, x) => s + x.count, 0))[0] ?? '' : '')
  const buckets = (summary?.buckets ?? []).filter((b) => b.currency === cur).sort((a, b) => rank(a.status) - rank(b.status))
  const total = buckets.reduce((s, b) => s + b.amountMinor, 0)
  const records = buckets.reduce((s, b) => s + b.count, 0)

  const load = useCallback((cursor: string | null) => adminConsoleApi.escrow({ status, currency: cur, cursor }), [status, cur])
  const list = useCursorList(load, setError)
  const term = search.trim().toLowerCase()
  const rows = (list.rows ?? []).filter((r) => !term || [r.contractTitle, r.buyerName, r.professionalName, r.providerReference ?? '', r.id]
    .some((v) => v.toLowerCase().includes(term)))
  const selected = rows.find((r) => r.id === selectedId) ?? null

  return (
    <>
      <AdminHeader crumb="Financial operations / Provider-attested funding" title="Protected Payments"
        subtitle="Monitor protected funding, release eligibility, dispute holds and refunds without bypassing payment controls."
        actions={currencies.length > 0 && <label className="small muted" style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>Currency
          <select className="adm-filter" aria-label="Currency" value={cur} onChange={(e) => { setCurrency(e.target.value); setSelectedId(null) }}>
            {currencies.map((c) => <option key={c} value={c}>{c}</option>)}</select></label>}
        meta={cur ? <span>Currency {cur} only · other currencies are shown separately, never added together</span> : undefined} />
      <ErrorAlert error={error} />
      {summary && summary.buckets.length === 0 && <Callout tone="blue" title="No protected funds yet">Records appear here once a buyer funds a milestone.</Callout>}

      {buckets.length > 0 && <KpiStrip>
        {buckets.map((b) => {
          const m = META[b.status] ?? { icon: 'wallet' as IconName, tone: 'blue' as Tone }
          return <AdminKpi key={b.status} icon={m.icon} tone={m.tone} label={statusLabel(b.status)} value={money(b.amountMinor, cur)}
            sub={`${b.count} record${b.count === 1 ? '' : 's'}`} />
        })}
      </KpiStrip>}

      {buckets.length > 0 && <PanelRow cols={2}>
        <Panel title="Funds by disposition" meta={`${money(total, cur)} · ${records} records · mutually exclusive states`}>
          <Donut center={money(total, cur)} caption={`${cur}, whole units`}
            segments={buckets.map((b) => ({ label: statusLabel(b.status), value: Math.round(b.amountMinor / 100), color: META[b.status]?.color }))} />
        </Panel>
        <Panel title="Records by state" meta={cur}>
          <MetricList rows={buckets.map((b) => ({ label: statusLabel(b.status), value: `${b.count} · ${money(b.amountMinor, cur)}`,
            tone: b.status === 'ON_HOLD' ? 'red' : b.status === 'RELEASE_PENDING_APPROVAL' ? 'amber' : undefined }))} />
          <p className="adm-foot-note">No release, refund or custody override is possible from this page.</p>
        </Panel>
      </PanelRow>}

      <ListDetail
        list={
          <div className="card">
            <CountTabs<string> value={status} onChange={(s) => { setStatus(s); setSelectedId(null) }} tabs={[
              { key: '', label: 'Payment records', count: summary ? records : null },
              ...buckets.map((b) => ({ key: b.status, label: statusLabel(b.status), count: b.count })),
            ]} />
            <FilterBar search={search} onSearch={setSearch} placeholder="Search engagement, party or provider reference…">
              {currencies.length > 1 && <FilterSelect label="Currency" value={currency} onChange={(v) => { setCurrency(v); setSelectedId(null) }}
                options={currencies.map((c) => [c, c])} />}
            </FilterBar>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th scope="col">Engagement / milestone</th><th scope="col">Buyer / professional</th><th scope="col">Amount</th><th scope="col">Provider evidence</th><th scope="col">State</th><th scope="col">Updated</th></tr></thead>
                <tbody>
                  {list.rows && rows.length === 0 && <tr><td colSpan={6} className="empty-row">No payment records match.</td></tr>}
                  {!list.rows && !error && <tr><td colSpan={6} className="empty-row">Loading…</td></tr>}
                  {rows.map((r) => (
                    <tr {...pickRow} key={r.id} className={`pick ${selectedId === r.id ? 'selected' : ''}`} onClick={() => setSelectedId(r.id)}>
                      <td><div className="cell-id">{r.contractTitle}</div><div className="cell-sub">{r.milestoneSequence != null ? `Milestone ${r.milestoneSequence}` : 'Contract level'}</div></td>
                      <td><div className="cell-main">{r.buyerName}</div><div className="cell-sub">{r.professionalName}</div></td>
                      <td><strong>{money(r.amountMinor, r.currency)}</strong><div className="cell-sub">{r.currency}</div></td>
                      <td className="small">{r.providerReference ? <>{r.provider ?? 'Provider'}<div className="cell-sub" title="Provider reference (shortened)">{shortRef(r.providerReference)}</div></> : <span className="muted">No provider reference</span>}</td>
                      <td><StatusPill status={r.status} /></td>
                      <td className="small">{shortDate(r.updatedAt)}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={rows.length} total={term ? null : status ? buckets.find((b) => b.status === status)?.count : records} noun="records" />
            {list.hasMore && <div style={{ padding: '0 16px 12px' }}>
              <button type="button" className="btn btn-secondary btn-sm" disabled={list.busy} onClick={list.more}>{list.busy ? 'Loading…' : 'Load more'}</button></div>}
          </div>
        }
        detail={selected && <PaymentDetail key={selected.id} r={selected} onClose={() => setSelectedId(null)} />}
      />
    </>
  )
}

const ACCEPTED = new Set(['RELEASE_PENDING_APPROVAL', 'RELEASED', 'PARTIALLY_RELEASED'])
const PAID = new Set(['RELEASED', 'PARTIALLY_RELEASED'])

function PaymentDetail({ r, onClose }: { r: AdminEscrowRow; onClose: () => void }) {
  const [escrow, setEscrow] = useState<Escrow | null>(null)
  const [tab, setTab] = useState('Release readiness')
  // The escrow account gives funding and release timestamps; staff read it as OPERATOR. If it is not readable, the row alone is shown.
  useEffect(() => { escrowApi.byContract(r.contractId).then(setEscrow).catch(() => setEscrow(null)) }, [r.contractId])
  const alloc = escrow?.allocations.find((a) => a.milestoneId === r.milestoneId) ?? null
  const state = alloc?.state ?? r.status
  const funded = !!alloc?.fundedAt || !['UNFUNDED', 'FUNDING'].includes(state)
  const items: { label: string; state: CheckState; note: string }[] = [
    { label: 'Funding captured by the provider', state: funded ? 'done' : state === 'FUNDING' ? 'pending' : 'missing', note: funded ? (alloc?.fundedAt ? shortDate(alloc.fundedAt) : 'Captured') : 'Not funded' },
    { label: 'Provider reference recorded', state: r.providerReference ? 'done' : 'missing', note: r.providerReference ? 'Recorded' : 'Missing' },
    { label: 'No dispute hold', state: state === 'ON_HOLD' ? 'missing' : 'done', note: state === 'ON_HOLD' ? 'Frozen' : 'Clear' },
    { label: 'Buyer acceptance', state: ACCEPTED.has(state) ? 'done' : 'pending', note: ACCEPTED.has(state) ? 'Accepted' : 'Pending' },
    { label: 'Release approved and paid', state: PAID.has(state) ? 'done' : 'pending', note: PAID.has(state) ? (alloc?.releasedAt ? shortDate(alloc.releasedAt) : 'Released') : 'Pending' },
  ]
  const open = items.filter((i) => i.state !== 'done')
  const fundings = (escrow?.fundings ?? []).filter((f) => !r.milestoneId || f.milestoneIds.includes(r.milestoneId))
  return (
    <DetailPanel title={r.contractTitle} subtitle={`${r.milestoneSequence != null ? `Milestone ${r.milestoneSequence}` : 'Contract'} · ${r.currency}`}
      badge={<StatusPill status={r.status} />} onClose={onClose} tabs={{ tabs: ['Release readiness', 'Funding'], value: tab, onChange: setTab }}>
      {tab === 'Release readiness' ? <>
        {PAID.has(state) ? <Callout tone="green" title="Released" />
          : <Callout tone={state === 'ON_HOLD' ? 'red' : 'amber'} title="Release not yet eligible">{open.map((o) => o.label).join(' · ')}</Callout>}
        <div className="adm-mini-stats">
          <div><div className="lbl">Allocation</div><div className="val">{money(r.amountMinor, r.currency)}</div></div>
          {alloc && <div><div className="lbl">Released</div><div className="val">{formatMoney(alloc.released)}</div></div>}
        </div>
        <Facts title="Source-linked payment context" rows={[
          ['Buyer', r.buyerName], ['Professional', r.professionalName],
          ['Provider', r.provider ?? '—'], ['Provider reference', r.providerReference ? shortRef(r.providerReference) : '—'],
          ...(alloc?.releaseReference ? [['Release reference', alloc.releaseReference] as [string, string]] : []),
          ['Currency', r.currency], ['Last update', shortDateTime(r.updatedAt)],
        ]} />
        <Checklist title="Release prerequisites" items={items} />
      </> : (
        fundings.length === 0 ? <p className="muted small">{escrow ? 'No funding attempts for this milestone.' : 'Funding history is not available.'}</p> : (
          <MetricList rows={fundings.map((f) => ({
            label: <>{shortDateTime(f.createdAt)}{f.failureMessage && <div className="cell-sub">{f.failureMessage}</div>}</>,
            value: <>{formatMoney(f.amount)} <StatusPill status={f.status} /></>,
          }))} />
        )
      )}
    </DetailPanel>
  )
}
