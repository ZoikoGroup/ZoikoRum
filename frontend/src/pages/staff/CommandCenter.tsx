import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { platformActivity, type AuditRecord } from '../../api/audit'
import { ROLE_LABEL } from '../../api/auth'
import { api } from '../../api/client'
import { paymentsApi, type OpsItem } from '../../api/escrow'
import { formatMoney } from '../../api/orgs'
import { adminApi, type AdminOverview } from '../../api/saved'
import { useAuth } from '../../auth/AuthContext'
import { useCapabilities } from '../../auth/capabilities'
import { ago, describe } from '../../components/activity'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, Donut, KpiStrip, Panel, PanelRow, Pill, TrendChart, label, shortDateTime,
} from '../../components/admin'
import { Icon } from '../../components/dashboard'
import { ErrorAlert, Loading } from '../../components/ui'
import { downloadFile } from '../../lib/exports'
import { fillDaily, hoursText, loadFunnels, pctText, type Funnels, type Kpis, type MarketplaceHealth, type WorkerBacklog } from './Analytics'
import { PriorityPill, STREAM_LABEL, useWorkItems, type Workstream } from './WorkQueue'
import { lightColor, lightName } from '../../lib/trustLight'

/* Command Center: the staff home. Platform counts, the period's activity, risk and money figures, the latest audit-ledger
   activity, the top of the person's work queue and system health. Every figure is live and role-scoped: cards whose
   source the person's roles cannot read are left out. */

const PERIODS: [string, string][] = [['7', 'Last 7 days'], ['30', 'Last 30 days'], ['90', 'Last 90 days']]
const DAY = 86_400_000

/** "↑ 12% vs previous 30 days" from this period's and the previous period's figure. */
function delta(now: number, before: number | undefined, days: number): ReactNode {
  if (before === undefined) return undefined
  const span = `vs previous ${days} days`
  if (now === before) return <>No change {span}</>
  const up = now > before
  const text = before === 0 ? `+${now}` : `${Math.round((Math.abs(now - before) / before) * 100)}%`
  return <><span style={{ color: up ? 'var(--zk-green)' : 'var(--zk-danger)', fontWeight: 600 }}>{up ? '↑' : '↓'} {text}</span> {span}</>
}

function MiniStat({ icon, tone, label: title, value, sub, to }: { icon: Parameters<typeof Icon>[0]['name']; tone: string; label: string; value: ReactNode; sub?: ReactNode; to?: string }) {
  const body = (
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
      <span className={`kpi-icon ${tone}`} aria-hidden><Icon name={icon} /></span>
      <div style={{ minWidth: 0 }}><div className="lbl">{title}</div><div className="val">{value}</div>{sub && <div className="muted small">{sub}</div>}</div>
    </div>
  )
  return <div>{to ? <Link to={to} style={{ color: 'inherit', textDecoration: 'none' }}>{body}</Link> : body}</div>
}

type HealthRow = { label: string; ok: boolean; note: string }

export default function CommandCenter() {
  const { user } = useAuth()
  const roles = useMemo(() => user?.platformRoles ?? [], [user])
  const { caps, has } = useCapabilities()  // what this staff sign-in may read: panels it cannot are left out
  const held = useMemo(() => [...caps].sort(), [caps])
  const canKpis = has('analytics.kpis.read')
  const canMoney = has('finexceptions.read', 'health.read')
  const canLedger = has('audit.records.read')
  const isAdmin = has('iam.read')
  const isOfficer = has('verification.read')

  const [days, setDays] = useState('30')
  const [tick, setTick] = useState(0)
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [kpis, setKpis] = useState<Kpis | null>(null)
  const [prev, setPrev] = useState<Kpis | null>(null)
  const [health, setHealth] = useState<MarketplaceHealth | null>(null)
  const [funnels, setFunnels] = useState<Funnels | null>(null)
  const [activity, setActivity] = useState<AuditRecord[] | null>(null)
  const [ops, setOps] = useState<OpsItem[] | null>(null)
  const [worker, setWorker] = useState<WorkerBacklog | null>(null)
  const [apiUp, setApiUp] = useState<boolean | null>(null)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [currency, setCurrency] = useState('')
  const [span, setSpan] = useState<{ since: string; until: string } | null>(null)
  const [queueTab, setQueueTab] = useState<'all' | Workstream>('all')
  const work = useWorkItems(held)
  const reloadWork = work.reload

  const n = Number(days)
  useEffect(() => {
    const to = new Date()
    const from = new Date(to.getTime() - n * DAY)
    const before = new Date(from.getTime() - n * DAY)
    const range = { from: from.toISOString(), to: to.toISOString() }
    setSpan({ since: new Date(to.getTime() - (n - 1) * DAY).toISOString().slice(0, 10), until: to.toISOString().slice(0, 10) })
    adminApi.overview().then(setOverview).catch(setError)
    api<MarketplaceHealth>('/v1/analytics/marketplace-health', { query: range }).then(setHealth).catch(setError)
    loadFunnels(range).then(setFunnels)
    if (canKpis) {
      api<Kpis>('/v1/admin/kpis', { query: range }).then(setKpis).catch(setError)
      api<Kpis>('/v1/admin/kpis', { query: { from: before.toISOString(), to: from.toISOString() } }).then(setPrev).catch(() => setPrev(null))
    }
    if (canLedger) platformActivity(40).then(setActivity).catch(() => setActivity([]))
    if (canMoney) {
      paymentsApi.opsWorklist().then((w) => setOps(w.items)).catch(() => setOps(null))
      api<WorkerBacklog>('/v1/admin/worker').then(setWorker).catch(() => setWorker(null))
    }
    api<{ status: string }>('/health', { auth: false }).then((h) => setApiUp(h.status === 'ok')).catch(() => setApiUp(false))
      .finally(() => setCheckedAt(new Date()))
  }, [n, tick, canKpis, canLedger, canMoney])

  const refresh = useCallback(() => { setTick((t) => t + 1); reloadWork() }, [reloadWork])

  if (!user) return null
  const o = overview
  const k = kpis
  const periodLabel = PERIODS.find(([v]) => v === days)?.[1] ?? ''
  const tiers = Object.entries(health?.trustTierDistribution ?? {}).sort(([a], [b]) => a.localeCompare(b))
  const tiered = tiers.reduce((s, [, x]) => s + x, 0)
  const series = health ? fillDaily(health.daily, span?.since, span?.until) : null
  const currencies = k?.payments.byCurrency ?? []
  const pay = currencies.find((c) => c.currency === currency) ?? currencies[0] ?? null
  const prevPay = pay ? prev?.payments.byCurrency.find((c) => c.currency === pay.currency) : undefined
  const fees = k?.board.feesByCurrency ?? []
  const prevFee = fees.length === 1 ? prev?.board.feesByCurrency.find((f) => f.currency === fees[0].currency)?.amountMinor ?? (prev ? 0 : undefined) : undefined
  const openOps = ops?.filter((i) => !i.resolvedAt) ?? null
  const chargebacks = openOps?.filter((i) => i.kind === 'CHARGEBACK_LOSS').length ?? null
  const rows = (activity ?? []).map((r) => ({ r, text: describe(r) })).filter((x) => x.text).slice(0, 6)

  const items = work.items ?? []
  const queueStreams = [...new Set(items.map((i) => i.stream))]
  const queueShown = items.filter((i) => queueTab === 'all' || i.stream === queueTab).slice(0, 5)

  const healthRows: HealthRow[] = [
    ...(apiUp === null ? [] : [{ label: 'API services', ok: apiUp, note: apiUp ? 'Operational' : 'Not responding' }]),
    ...(worker ? [
      { label: 'Event publishing', ok: worker.oldestUnpublishedSeconds < 300,
        note: worker.unpublishedEvents ? `${worker.unpublishedEvents} waiting · oldest ${Math.round(worker.oldestUnpublishedSeconds / 60)} min` : 'Operational' },
      { label: 'Scheduled timers', ok: worker.overdueTimers === 0 || worker.oldestOverdueTimerSeconds < 300,
        note: worker.overdueTimers ? `${worker.overdueTimers} overdue` : 'Operational' },
      { label: 'Event deliveries', ok: worker.deadLetters === 0,
        note: worker.deadLetters ? `${worker.deadLetters} failed${worker.deadFinancialLetters ? ` · ${worker.deadFinancialLetters} affect money` : ''}`
          : worker.retryingDeliveries ? `${worker.retryingDeliveries} retrying` : 'Operational' },
    ] : []),
  ]
  const allOk = healthRows.length > 0 && healthRows.every((h) => h.ok)

  function exportJson() {
    downloadFile(`zoikorum-command-center-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify({
      exportedAt: new Date().toISOString(), period: periodLabel, overview, kpis, previousPeriodKpis: prev, marketplaceHealth: health, funnels,
      recentActivity: rows.map(({ r, text }) => ({ at: r.occurredAt, event: text, objectType: r.objectType, objectId: r.objectId })),
      workQueue: items.map(({ facts: _facts, ...i }) => i), paymentExceptions: openOps, worker, apiUp, checkedAt,
    }, null, 2), 'application/json')
  }

  return (
    <>
      <AdminHeader crumb="Overview / Admin dashboard" title="Command Center"
        subtitle={<>Platform activity, risk, financial operations and system health · {roles.map((r) => ROLE_LABEL[r] ?? r).join(', ')}</>}
        actions={<>
          <select className="adm-filter" aria-label="Period" value={days} onChange={(e) => setDays(e.target.value)}>
            {PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          {isOfficer && <Link className="btn btn-secondary" to="/platform-admin/verification-center">Review queue</Link>}
          {isAdmin && <Link className="btn btn-secondary" to="/platform-admin/staff-access-control">Staff &amp; roles</Link>}
          <button type="button" className="btn btn-primary" onClick={refresh}><Icon name="refresh" /> Refresh</button>
          <button type="button" className="btn btn-secondary" onClick={exportJson}><Icon name="download" /> Export</button>
        </>} />
      <ErrorAlert error={error} />

      <KpiStrip>
        <AdminKpi icon="team" tone="green" label="Total accounts" value={o?.accounts.total.toLocaleString() ?? '—'}
          sub={o ? `${o.accounts.buyers} buyers · ${o.accounts.enterprise} enterprise · ${o.accounts.firmAdmins} firm admins` : ' '}
          to={has('accounts.read') ? '/platform-admin/accounts-organizations' : undefined} />
        <AdminKpi icon="user" tone="violet" label="Verified professionals" value={k ? k.board.verifiedSupply.toLocaleString() : health ? ((health.trustTierDistribution.A ?? 0) + (health.trustTierDistribution.B ?? 0)).toLocaleString() : '—'}
          sub={o ? `Green + Amber · ${o.professionalProfiles.published} of ${o.professionalProfiles.total} profiles published` : 'Green + Amber'} />
        {k ? <>
          <AdminKpi icon="building" tone="blue" label="Active buyer organisations" value={k.board.activeBuyerOrganisations.toLocaleString()}
            sub={delta(k.board.activeBuyerOrganisations, prev?.board.activeBuyerOrganisations, n) ?? periodLabel} />
          <AdminKpi icon="contract" tone="teal" label="Engagements started" value={k.board.engagementsStarted.toLocaleString()}
            sub={delta(k.board.engagementsStarted, prev?.board.engagementsStarted, n) ?? periodLabel} />
          <AdminKpi icon="wallet" tone="amber" label="Platform revenue (fees)" value={fees.length ? fees.map((f) => formatMoney(f)).join(' + ') : '—'}
            sub={fees.length === 1 ? delta(fees[0].amountMinor, prevFee, n) ?? periodLabel : fees.length ? `${periodLabel} · per currency` : `No fees · ${periodLabel}`} />
        </> : <>
          <AdminKpi icon="building" tone="blue" label="Buyers" value={o?.accounts.buyers.toLocaleString() ?? '—'} sub="Accounts that hire" />
          <AdminKpi icon="contract" tone="teal" label="Engagements started" value={health?.activations.toLocaleString() ?? '—'} sub={periodLabel} />
        </>}
        <AdminKpi icon="shield" tone={o?.verification.overdue ? 'red' : 'amber'} label="Open verifications" value={o?.verification.open ?? '—'}
          sub={o ? (o.verification.overdue ? `${o.verification.overdue} past service level` : 'None overdue') : ' '} to={isOfficer ? '/platform-admin/verification-center' : undefined} />
      </KpiStrip>

      <PanelRow cols={2}>
        <Panel title="Engagement activity" meta={periodLabel} action={<Link className="small" to="/platform-admin/analytics-insights">Analytics</Link>}>
          {!series ? <Loading lines={3} /> : <TrendChart kind="bar" labels={series.labels} series={[
            { label: 'Proposals submitted', values: series.days.map((d) => d.proposalsSubmitted) },
            { label: 'Engagements started', values: series.days.map((d) => d.activations) },
            { label: 'Milestone releases', values: series.days.map((d) => d.releases) },
          ]} />}
          {health && <p className="adm-foot-note">{health.searches.toLocaleString()} searches
            {health.searches ? ` (${Math.round((health.zeroResultSearches / health.searches) * 100)}% with no results)` : ''} · proposal → contract{' '}
            {health.proposalContractConversionBps == null ? '—' : `${(health.proposalContractConversionBps / 100).toFixed(1)}%`} · disputes opened / resolved {health.disputesOpened} / {health.disputesResolved}</p>}
        </Panel>
        <Panel title="Professionals by trust light" meta="Current snapshot">
          {!health ? <Loading lines={3} /> : tiered ? <Donut segments={tiers.map(([t, x]) => ({ label: lightName(t), value: x, color: lightColor(t) }))}
            center={tiered.toLocaleString()} caption="with a light" /> : <p className="muted small">No trust lights assigned yet.</p>}
        </Panel>
      </PanelRow>

      {(k || o) && (
        <PanelRow cols={2}>
          <Panel title="Risk & compliance overview" meta={k ? 'Open now' : undefined}>
            <div className="adm-mini-stats">
              {k && <MiniStat icon="shield" tone="red" label="Safety cases undecided" value={k.enforcement.openNow} sub={`${k.enforcement.casesOpened} opened · ${periodLabel.toLowerCase()}`} to="/platform-admin/trust-safety" />}
              {o && <MiniStat icon="clock" tone="amber" label="Verifications due for review" value={o.verification.open} sub={o.verification.overdue ? `${o.verification.overdue} overdue` : 'None overdue'} />}
              {k && <MiniStat icon="alert" tone="red" label="Platform incidents" value={k.enforcement.incidentsOpenNow} sub={`${k.board.seriousIncidents} SEV1–2 in period`} to="/platform-admin/incident-command" />}
              {k && <MiniStat icon="scale" tone="violet" label="Open disputes" value={k.disputes.openNow} sub={`${k.disputes.opened} opened in period`} />}
            </div>
          </Panel>
          {k && (
            <Panel title="Financial operations" meta={pay ? pay.currency : periodLabel}
              action={currencies.length > 1 && <select className="adm-filter" aria-label="Currency" value={pay?.currency ?? ''} onChange={(e) => setCurrency(e.target.value)}>
                {currencies.map((c) => <option key={c.currency} value={c.currency}>{c.currency}</option>)}</select>}>
              {!pay ? <p className="muted small">No payments in this period.</p> : (
                <div className="adm-mini-stats">
                  <MiniStat icon="lock" tone="green" label="Held in escrow" value={formatMoney({ amountMinor: pay.heldNowMinor, currency: pay.currency })} sub="Now" />
                  <MiniStat icon="arrow" tone="blue" label="Released" value={formatMoney({ amountMinor: pay.releasedMinor, currency: pay.currency })}
                    sub={delta(pay.releasedMinor, prevPay?.releasedMinor ?? (prev ? 0 : undefined), n) ?? periodLabel} />
                  <MiniStat icon="scale" tone="amber" label="Frozen in disputes" value={formatMoney({ amountMinor: pay.frozenNowMinor, currency: pay.currency })} sub="Now" />
                  {openOps && <MiniStat icon="alert" tone="amber" label="Payment issues" value={openOps.length} sub="Open in the worklist" to="/platform-admin/financial-exceptions" />}
                  {chargebacks != null && <MiniStat icon="alert" tone="red" label="Chargeback losses" value={chargebacks} sub="Open" to="/platform-admin/financial-exceptions" />}
                </div>
              )}
            </Panel>
          )}
        </PanelRow>
      )}

      {(funnels || k) && (
        <Panel title="Funnels & flow" meta={periodLabel} action={<Link className="small" to="/platform-admin/analytics-insights">Details</Link>}>
          <div className="adm-mini-stats">
            {funnels && <MiniStat icon="user" tone="violet" label="Onboarding completion" value={pctText(funnels.onboarding.completionRatePct)}
              sub={`Median sign-up → published ${hoursText(funnels.onboarding.medianHoursSignupToPublish)}`} />}
            {funnels && <MiniStat icon="proposal" tone="amber" label="Requests abandoned" value={pctText(funnels.request.abandonmentRatePct)}
              sub={`${funnels.request.visitsAbandoned} of ${funnels.request.visitsStarted} visits`} />}
            {k?.payments.acceptance && <MiniStat icon="clock" tone="blue" label="Submit → acceptance" value={hoursText(k.payments.acceptance.medianHoursSubmitToAccept)}
              sub={`Median · ${k.payments.acceptance.milestonesAccepted} accepted`} />}
            {k && k.payments.refundsPer100Payments !== undefined && <MiniStat icon="wallet" tone="amber" label="Refunds per 100 payments" value={k.payments.refundsPer100Payments ?? '—'}
              sub={`Disputes per 100 payments ${k.payments.disputesPer100Payments ?? '—'}`} />}
            {k?.payments.approvals && <MiniStat icon="alert" tone={k.payments.approvals.pendingNow ? 'amber' : 'green'} label="Approval bottleneck"
              value={k.payments.approvals.bottleneck ? hoursText(k.payments.approvals.bottleneck.medianHoursWait) : '—'}
              sub={k.payments.approvals.bottleneck ? `Step ${k.payments.approvals.bottleneck.step} · ${label(k.payments.approvals.bottleneck.role)} · ${k.payments.approvals.pendingNow} pending` : 'No approvals in period'} />}
          </div>
        </Panel>
      )}

      <PanelRow>
        {canLedger && (
          <Panel title="Recent activity" action={<Link className="small" to="/platform-admin/audit-evidence">View all</Link>}>
            {activity === null ? <Loading lines={3} /> : rows.length === 0 ? <p className="muted small">No activity yet.</p> : (
              <table className="data">
                <thead><tr><th scope="col">Time</th><th scope="col">Event</th><th scope="col">Area</th></tr></thead>
                <tbody>{rows.map(({ r, text }) => (
                  <tr key={r.id}><td className="muted small" title={shortDateTime(r.occurredAt)}>{ago(r.occurredAt)}</td><td>{text}</td><td className="muted small">{label(r.objectType)}</td></tr>))}</tbody>
              </table>
            )}
            <p className="adm-foot-note">From the tamper-evident audit ledger.</p>
          </Panel>
        )}
        <Panel title="My work queue" action={<Link className="small" to="/platform-admin/my-work-queue">View all</Link>}>
          {work.items === null ? <Loading lines={3} /> : <>
            {queueStreams.length > 1 && <CountTabs value={queueTab} onChange={setQueueTab} tabs={[{ key: 'all' as const, label: 'All', count: items.length },
              ...queueStreams.slice(0, 3).map((s) => ({ key: s, label: STREAM_LABEL[s], count: items.filter((i) => i.stream === s).length }))]} />}
            {queueShown.length === 0 ? <p className="muted small">Nothing waiting in your queues.</p> : (
              <table className="data">
                <thead><tr><th scope="col">Priority</th><th scope="col">Item</th><th scope="col">Age</th></tr></thead>
                <tbody>{queueShown.map((i) => (
                  <tr key={i.id}><td><PriorityPill p={i.priority} /></td>
                    <td><Link to={i.to} className="cell-main">{i.subject}</Link><div className="cell-sub">{STREAM_LABEL[i.stream]} · {i.ref}</div></td>
                    <td className="muted small">{i.overdue ? <span style={{ color: 'var(--zk-danger)' }}>Overdue</span> : i.created ? ago(i.created) : '—'}</td></tr>))}</tbody>
              </table>
            )}
            {work.failed.length > 0 && <p className="adm-foot-note">Could not load: {work.failed.join(', ')}.</p>}
          </>}
        </Panel>
        <Panel title="System health" action={healthRows.length > 0 && <Pill tone={allOk ? 'green' : 'amber'}>{allOk ? 'All systems operational' : 'Needs attention'}</Pill>}>
          {healthRows.length === 0 ? <Loading lines={2} /> : (
            <ul className="adm-metrics">{healthRows.map((h) => (
              <li key={h.label}><span>{h.label}</span><Pill tone={h.ok ? 'green' : 'amber'}>{h.note}</Pill></li>))}</ul>
          )}
          {checkedAt && <p className="adm-foot-note">Last checked {shortDateTime(checkedAt.toISOString())}{!worker && ' · worker detail is visible to Platform Admins and Financial Operations'}</p>}
        </Panel>
      </PanelRow>

      <Callout tone="blue" title="Staff rules">Every decision is made by a named person and logged. Sensitive actions ask for a fresh two-step code.
        Nobody reviews their own case. AI may flag, never decide.</Callout>
    </>
  )
}
