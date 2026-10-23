import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { paymentsApi } from '../../api/escrow'
import { formatMoney } from '../../api/orgs'
import { adminApi, type AdminOverview } from '../../api/saved'
import { useCapabilities } from '../../auth/capabilities'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, Donut, HBars, KpiStrip, MetricList, Panel, PanelRow, TrendChart, CHART_COLORS, label,
} from '../../components/admin'
import { Icon } from '../../components/dashboard'
import { ErrorAlert, Loading, useStepUp } from '../../components/ui'
import { downloadFile } from '../../lib/exports'

/* Analytics & Insights: marketplace health (/v1/analytics/marketplace-health) and the platform KPIs (/v1/admin/kpis) for
   one period, drawn as charts. Every figure is live; money is shown per currency and never converted. */

export interface DailyHealth {
  date: string; searches: number; zeroResultSearches: number; proposalsSubmitted: number; contractsGenerated: number
  activations: number; releases: number; disputesOpened: number; disputesResolved: number
}
export interface MarketplaceHealth {
  window: { from: string | null; to: string | null }
  eventCounts: Record<string, number>
  searches: number; daily: DailyHealth[]; activations: number; disputesOpened: number; disputesResolved: number; zeroResultSearches: number
  proposalContractConversionBps: number | null; medianReleaseLatencySeconds: number | null
  trustTierDistribution: Record<string, number>; lastEventAt: string | null
}
type CurrencyAmount = { currency: string; amountMinor: number }
export interface Kpis {
  from: string; to: string
  board: { grossReleasedByCurrency: CurrencyAmount[]; feesByCurrency: CurrencyAmount[]; engagementsStarted: number; activeBuyerOrganisations: number
    disputeRatePct: number | null; verifiedSupply: number; seriousIncidents: number }
  onboarding: { profilesStarted: number; profilesPublished: number; publishedNow: number; enterpriseReadyNow: number }
  trust: { tiersNow: Record<string, number>; reachedB: number; reachedA: number; downgrades: number }
  engagements: { engagementsStarted: number; engagementsCompleted: number; runningNow: number; activeBuyerOrganisations: number; activeProfessionals: number }
  payments: { byCurrency: { currency: string; fundedMinor: number; releasedMinor: number; feesMinor: number; heldNowMinor: number; frozenNowMinor: number; takeRateBps: number | null }[]
    acceptance?: { milestonesAccepted: number; medianHoursSubmitToAccept: number | null; p90HoursSubmitToAccept: number | null }
    paymentsCaptured?: number; refunds?: number; refundsPer100Payments?: number | null; disputesPer100Payments?: number | null
    refundsByCurrency?: { currency: string; payments: number; refunds: number; refundedMinor: number; refundsPer100Payments: number | null }[]
    approvals?: ApprovalBottlenecks }
  disputes: { opened: number; decided: number; openNow: number; medianDaysToDecision: number | null; decidedWithoutPlatform: number; byDecisionPath: Record<string, number>
    escalated?: number; escalationRatePct?: number | null; evidenceCompletenessPct?: number | null; appealsFiled?: number; appealRatePct?: number | null
    organisationsWithDisputes?: number; repeatOrganisations?: number; professionalsWithDisputes?: number; repeatProfessionals?: number }
  enforcement: { casesOpened: number; openNow: number; medianHoursToFirstDecision: number | null; actionsTaken: Record<string, number>; incidentsOpenNow: number; incidentsBySeverity: Record<string, number>
    byLevel?: Record<string, number>; actionsApplied?: number; reversed?: number; reversalRatePct?: number | null; appealsFiled?: number; appealsDecided?: number
    appealsUpheld?: number; appealSuccessRatePct?: number | null; subjectsActioned?: number; recurringSubjects?: number }
}
export interface ApprovalStep { step: number; role: string; completed: number; medianHoursWait: number | null; pending: number; oldestPendingHours: number | null; expired: number }
export interface ApprovalBottlenecks { requests: number; pendingNow: number; steps: ApprovalStep[]; bottleneck: { step: number; role: string; medianHoursWait: number | null; pending: number } | null }
export interface BoardExtras {
  trustTierTrend?: { date: string; A: number; B: number; C: number }[]; enforcementReversalRatePct?: number | null; credentialExpiryIncidents?: number
  enterpriseOnboarding?: { decided: number; approved: number; pendingNow: number; medianDaysToDecision: number | null }
}
export interface FunnelStep { step: string; viewed: number; completed: number; dropOffPct: number | null; position: number | null }
export interface OnboardingFunnel { visitsStarted: number; visitsPublished: number; completionRatePct: number | null; steps: FunnelStep[]; profilesPublished: number; medianHoursSignupToPublish: number | null }
export interface RequestFunnel { visitsStarted: number; visitsAbandoned: number; abandonmentRatePct: number | null; steps: FunnelStep[]
  abandonedByStep: { step: string; visits: number }[]; requestsSent: number; proposals: { started: number; submitted: number; completionRatePct: number | null } }
export interface SearchFunnel { searches: number; actions: { event: string; count: number; visits: number; per100Searches: number | null }[]
  topFilters: { value: string; count: number }[]; topSpecializations: { value: string; count: number }[] }
export interface Funnels { onboarding: OnboardingFunnel; request: RequestFunnel; search: SearchFunnel }

/** Loads the three product funnels for a window; null when the person may not read them or the call fails. */
export async function loadFunnels(range: Record<string, string>): Promise<Funnels | null> {
  try {
    const [onboarding, request, search] = await Promise.all([
      api<OnboardingFunnel>('/v1/admin/analytics/funnels/onboarding', { query: range }),
      api<RequestFunnel>('/v1/admin/analytics/funnels/request', { query: range }),
      api<SearchFunnel>('/v1/admin/analytics/funnels/search', { query: range }),
    ])
    return { onboarding, request, search }
  } catch {
    return null
  }
}
export const pctText = (v: number | null | undefined) => (v == null ? '—' : `${v.toLocaleString()}%`)
export const hoursText = (h: number | null | undefined) => (h == null ? '—' : h < 48 ? `${h.toLocaleString()} h` : `${(h / 24).toFixed(1)} days`)
const ACTION_LABEL: Record<string, string> = {
  filter_applied: 'Filter applied', specialization_selected: 'Specialization chosen', quick_view_opened: 'Quick view opened',
  compare_opened: 'Comparison opened', service_card_opened: 'Service opened', verification_detail_viewed: 'Verification details viewed',
  enterprise_cta_clicked: 'Enterprise call to action',
}
const stepLabel = (s: string) => sentence(s.replace(/[-_]/g, ' '))
export interface WorkerBacklog { unpublishedEvents: number; oldestUnpublishedSeconds: number; overdueTimers: number; oldestOverdueTimerSeconds: number
  retryingDeliveries: number; deadLetters: number; deadFinancialLetters: number }

/** Dates are whole UTC days, matching how the server buckets the daily series. */
export const utcToday = () => new Date().toISOString().slice(0, 10)
export function addDays(date: string, days: number) {
  const d = new Date(`${date}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}
const utcDayLabel = (date: string) => new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' })
const axisLabel = (date: string) => new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { timeZone: 'UTC', day: 'numeric', month: 'short' })

/** The server lists only days with activity: fill the gaps with zeros so the chart's x axis is continuous. */
export function fillDaily(daily: DailyHealth[], since?: string, until?: string) {
  const first = since ?? daily[0]?.date
  const last = until ?? daily[daily.length - 1]?.date
  if (!first || !last || first > last) return { labels: [] as string[], days: [] as DailyHealth[] }
  const byDate = new Map(daily.map((d) => [d.date.slice(0, 10), d]))
  const days: DailyHealth[] = []
  for (let d = first; d <= last && days.length < 1000; d = addDays(d, 1)) {
    days.push(byDate.get(d) ?? { date: d, searches: 0, zeroResultSearches: 0, proposalsSubmitted: 0, contractsGenerated: 0, activations: 0, releases: 0, disputesOpened: 0, disputesResolved: 0 })
  }
  return { labels: days.map((d) => axisLabel(d.date)), days }
}

const percent = (part: number, whole: number) => `${(Math.round((1000 * part) / whole) / 10).toLocaleString()}%`
const ago = (s: number) => (s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`)
const duration = (s: number) => (s < 5400 ? ago(s) : s < 172800 ? `${(s / 3600).toFixed(1)} h` : `${(s / 86400).toFixed(1)} days`)
const moneyList = (list: CurrencyAmount[]) => (list.length ? list.map((x) => formatMoney(x)).join(' + ') : '—')

const EVENT_AREAS: [string, string][] = [
  ['search', 'Search'], ['verification', 'Verification'], ['trust', 'Trust'], ['policy', 'Policy'], ['proposal', 'Proposals'],
  ['contract', 'Contracts & Milestones'], ['escrow', 'Escrow'], ['payments', 'Payments'], ['dispute', 'Disputes'], ['marketplace', 'Marketplace'],
]
const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
/** "zoikorum.escrow.account.funding_requested.v1" -> area "escrow", label "Account funding requested". */
function readableEvent(name: string) {
  const [, area = 'other', ...rest] = name.split('.')
  const words = rest.filter((part) => !/^v\d+$/.test(part)).join(' ').replaceAll('_', ' ')
  return { area, label: sentence(words || name) }
}
function groupEventCounts(counts: Record<string, number>) {
  const groups = new Map<string, { name: string; label: string; count: number }[]>()
  for (const [name, count] of Object.entries(counts)) {
    const { area, label } = readableEvent(name)
    groups.set(area, [...(groups.get(area) ?? []), { name, label, count }])
  }
  const order = EVENT_AREAS.map(([key]) => key)
  return [...groups.entries()]
    .sort(([a], [b]) => (order.indexOf(a) + 1 || order.length + 1) - (order.indexOf(b) + 1 || order.length + 1))
    .map(([area, events]) => ({ area, title: EVENT_AREAS.find(([key]) => key === area)?.[1] ?? sentence(area), events, total: events.reduce((s, e) => s + e.count, 0) }))
}

type Preset = '7' | '30' | '90' | 'all' | 'custom'
const PRESETS: [Preset, string][] = [['7', 'Last 7 days'], ['30', 'Last 30 days'], ['90', 'Last 90 days'], ['all', 'All time'], ['custom', 'Custom range']]
type Trend = 'engagements' | 'search' | 'disputes'
const TIER_COLORS: Record<string, string> = { A: '#12b76a', B: '#2f80ed', C: '#9b8afb' }

export default function Analytics() {
  const { has } = useCapabilities()
  const isPlatformAdmin = has('analytics.rebuild')
  const canKpis = has('analytics.kpis.read')
  const canMoney = has('health.read')
  const [data, setData] = useState<MarketplaceHealth | null>(null)
  const [kpis, setKpis] = useState<(Kpis & { board: Kpis['board'] & BoardExtras }) | null>(null)
  const [funnels, setFunnels] = useState<Funnels | null>(null)
  const [kpiError, setKpiError] = useState<unknown>(null)
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [worker, setWorker] = useState<WorkerBacklog | null>(null)
  const [exceptions, setExceptions] = useState<number | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [rebuilt, setRebuilt] = useState<{ projectedEvents: number; at: Date } | null>(null)
  const [preset, setPreset] = useState<Preset>('30')
  const [since, setSince] = useState(() => addDays(utcToday(), -29))
  const [until, setUntil] = useState(utcToday)
  const [trend, setTrend] = useState<Trend>('engagements')
  const [currency, setCurrency] = useState('')
  const { run, modal } = useStepUp(setError)

  const bounded = preset !== 'all'
  const invalidRange = bounded && (!since || !until || since > until)

  const reload = useCallback(async () => {
    if (invalidRange) return
    setBusy(true)
    const range: Record<string, string> = bounded ? { from: `${since}T00:00:00Z`, to: `${addDays(until, 1)}T00:00:00Z` } : {}
    try {
      // KPIs need a start date: "All time" asks from 2000, before any platform activity.
      if (canKpis) api<Kpis>('/v1/admin/kpis', { query: bounded ? range : { from: '2000-01-01T00:00:00Z', to: new Date().toISOString() } })
        .then((k) => { setKpis(k); setKpiError(null) }).catch(setKpiError)
      loadFunnels(bounded ? range : { from: '2000-01-01T00:00:00Z', to: new Date().toISOString() }).then(setFunnels)
      adminApi.overview().then(setOverview).catch(() => {})
      if (canMoney) {
        api<WorkerBacklog>('/v1/admin/worker').then(setWorker).catch(() => {})
        paymentsApi.opsWorklist().then((w) => setExceptions(w.open)).catch(() => {})
      }
      setData(await api<MarketplaceHealth>('/v1/analytics/marketplace-health', { query: range }))
      setError(null)
    } finally {
      setBusy(false)
    }
  }, [bounded, invalidRange, since, until, canKpis, canMoney])

  useEffect(() => { reload().catch(setError) }, [reload])

  function choosePreset(next: Preset) {
    setPreset(next)
    if (next === '7' || next === '30' || next === '90') {
      setUntil(utcToday())
      setSince(addDays(utcToday(), 1 - Number(next)))
    }
  }

  const windowLabel = !bounded ? 'All time' : preset === 'custom' ? `${utcDayLabel(since)} – ${utcDayLabel(until)}` : PRESETS.find(([k]) => k === preset)?.[1] ?? ''

  function downloadJson() {
    if (!data) return
    const range = bounded ? `${since}_to_${until}` : 'all-time'
    downloadFile(`zoikorum-analytics-${range}.json`, JSON.stringify({ exportedAt: new Date().toISOString(), window: windowLabel,
      marketplaceHealth: data, kpis, funnels, overview, worker, openPaymentExceptions: exceptions }, null, 2), 'application/json')
  }

  const tiers = Object.entries(data?.trustTierDistribution ?? {}).sort(([a], [b]) => a.localeCompare(b))
  const tiered = tiers.reduce((s, [, n]) => s + n, 0)
  const tierOf = (t: string) => kpis?.trust.tiersNow[t] ?? data?.trustTierDistribution[t] ?? 0
  const series = data ? fillDaily(data.daily, bounded ? since : undefined, bounded ? until : undefined) : null
  const trendSeries = !series ? [] : trend === 'engagements'
    ? [{ label: 'Proposals submitted', values: series.days.map((d) => d.proposalsSubmitted) },
      { label: 'Contracts generated', values: series.days.map((d) => d.contractsGenerated) },
      { label: 'Engagements started', values: series.days.map((d) => d.activations) },
      { label: 'Milestone releases', values: series.days.map((d) => d.releases) }]
    : trend === 'search'
      ? [{ label: 'Searches', values: series.days.map((d) => d.searches) }, { label: 'With no results', values: series.days.map((d) => d.zeroResultSearches), color: CHART_COLORS[3] }]
      : [{ label: 'Disputes opened', values: series.days.map((d) => d.disputesOpened), color: CHART_COLORS[5] }, { label: 'Disputes resolved', values: series.days.map((d) => d.disputesResolved), color: CHART_COLORS[1] }]
  const currencies = kpis?.payments.byCurrency ?? []
  const pay = currencies.find((c) => c.currency === currency) ?? currencies[0] ?? null
  const fee = pay ? kpis?.board.feesByCurrency.find((f) => f.currency === pay.currency) : undefined
  const groups = data ? groupEventCounts(data.eventCounts) : []
  const tierTrend = kpis?.board.trustTierTrend ?? []
  const approvals = kpis?.payments.approvals
  const ob = funnels?.onboarding
  const rq = funnels?.request
  const sr = funnels?.search

  const funnel = [
    overview && { label: 'Profiles created', value: overview.professionalProfiles.total },
    kpis ? { label: 'Published now', value: kpis.onboarding.publishedNow } : overview && { label: 'Published now', value: overview.professionalProfiles.published },
    (kpis || data) && { label: 'Tier A + B', value: tierOf('A') + tierOf('B') },
    (kpis || data) && { label: 'Tier A', value: tierOf('A') },
    kpis && { label: 'Enterprise Ready', value: kpis.onboarding.enterpriseReadyNow },
  ].filter((r): r is { label: string; value: number } => !!r)

  return (
    <>
      <AdminHeader crumb="Overview / Business intelligence" title="Analytics & Insights"
        subtitle="Marketplace liquidity, engagement, trust, protected payments and platform health for the period you choose."
        actions={<>
          <select className="adm-filter" aria-label="Period" value={preset} onChange={(e) => choosePreset(e.target.value as Preset)}>
            {PRESETS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          {bounded && <>
            <input type="date" className="adm-filter" aria-label="From (UTC)" value={since} max={until || undefined} onChange={(e) => { setPreset('custom'); setSince(e.target.value) }} />
            <input type="date" className="adm-filter" aria-label="To (UTC)" value={until} min={since || undefined} onChange={(e) => { setPreset('custom'); setUntil(e.target.value) }} />
          </>}
          <button type="button" className="btn btn-secondary" onClick={() => reload().catch(setError)} disabled={busy || invalidRange}><Icon name="refresh" /> Refresh</button>
          <button type="button" className="btn btn-secondary" onClick={downloadJson} disabled={!data}><Icon name="download" /> Download JSON</button>
          {isPlatformAdmin && <button type="button" className="btn btn-primary" disabled={busy} onClick={() => {
            setRebuilt(null)
            run(async () => {
              const result = await api<{ projectedEvents: number }>('/v1/admin/analytics/rebuild', { method: 'POST' })
              await reload()
              setRebuilt({ projectedEvents: result.projectedEvents, at: new Date() })
            })
          }}>Rebuild projections</button>}
        </>}
        meta={data && <>
          <span className="live">Latest event {data.lastEventAt ? new Date(data.lastEventAt).toLocaleString() : 'none recorded yet'}</span>
          <span>{windowLabel} (UTC days)</span><span>Money is shown per currency, never converted</span>
        </>} />

      {invalidRange && <Callout tone="red" title="Choose a start date on or before the end date." />}
      <ErrorAlert error={error} />
      {modal}
      {rebuilt && <Callout tone="green" title={`Projections rebuilt from the audit ledger at ${rebuilt.at.toLocaleTimeString()}`}>
        {rebuilt.projectedEvents.toLocaleString()} event{rebuilt.projectedEvents === 1 ? '' : 's'} replayed. The figures below are the rebuilt values.</Callout>}

      {!data ? <Loading lines={4} /> : (
        <>
          <KpiStrip>
            {kpis ? <>
              <AdminKpi icon="building" tone="blue" label="Active buyer organisations" value={kpis.engagements.activeBuyerOrganisations.toLocaleString()} sub={windowLabel} />
              <AdminKpi icon="user" tone="violet" label="Published professionals" value={kpis.onboarding.publishedNow.toLocaleString()} sub={`${kpis.onboarding.profilesPublished} published in period`} />
              <AdminKpi icon="contract" tone="green" label="Engagements started" value={kpis.engagements.engagementsStarted.toLocaleString()} sub={`${kpis.engagements.runningNow} running now`} />
              <AdminKpi icon="check" tone="teal" label="Engagements completed" value={kpis.engagements.engagementsCompleted.toLocaleString()} sub={`${kpis.engagements.activeProfessionals} professionals engaged`} />
              <AdminKpi icon="wallet" tone="amber" label={`Escrow funded${pay ? ` · ${pay.currency}` : ''}`} value={pay ? formatMoney({ amountMinor: pay.fundedMinor, currency: pay.currency }) : '—'} sub={pay ? windowLabel : 'No payments yet'} />
              <AdminKpi icon="chart" tone="green" label={`Fee revenue${pay ? ` · ${pay.currency}` : ''}`} value={fee ? formatMoney(fee) : '—'}
                sub={pay?.takeRateBps != null ? `Take rate ${(pay.takeRateBps / 100).toFixed(1)}%` : windowLabel} />
            </> : <>
              <AdminKpi icon="contract" tone="green" label="Engagements started" value={data.activations.toLocaleString()} sub={windowLabel} />
              <AdminKpi icon="search" tone="blue" label="Searches" value={data.searches.toLocaleString()} sub={data.searches ? `${percent(data.zeroResultSearches, data.searches)} with no results` : windowLabel} />
              <AdminKpi icon="proposal" tone="violet" label="Proposal → contract" value={data.proposalContractConversionBps == null ? '—' : percent(data.proposalContractConversionBps, 10000)} sub="Contracts per proposal submitted" />
              <AdminKpi icon="scale" tone="amber" label="Disputes opened / resolved" value={`${data.disputesOpened} / ${data.disputesResolved}`} sub={windowLabel} />
            </>}
          </KpiStrip>
          {!!kpiError && <ErrorAlert error={kpiError} />}

          <PanelRow>
            <Panel title="Engagement activity" meta="Per UTC day"
              action={<CountTabs value={trend} onChange={setTrend} tabs={[{ key: 'engagements', label: 'Engagements' }, { key: 'search', label: 'Search' }, { key: 'disputes', label: 'Disputes' }]} />}>
              {series && <TrendChart labels={series.labels} series={trendSeries} kind="line" />}
            </Panel>
            <Panel title="Professional readiness funnel" meta="Current counts">
              <HBars rows={funnel} format={(v) => v.toLocaleString()} />
              <p className="adm-foot-note">Tier A + B is a subset of published profiles. Verification and publication are separate controls.</p>
            </Panel>
            <Panel title="Professionals by trust tier" meta="Current snapshot">
              {tiered ? <Donut segments={tiers.map(([t, n]) => ({ label: `Tier ${t}`, value: n, color: TIER_COLORS[t] }))} center={tiered.toLocaleString()} caption="with a tier" />
                : <p className="muted small">No tiers assigned yet.</p>}
              <p className="adm-foot-note">Trust tiers describe platform-defined eligibility, not a guarantee of future performance.</p>
            </Panel>
          </PanelRow>

          <PanelRow>
            <Panel title="Marketplace quality" meta={windowLabel}>
              <MetricList rows={[
                { label: 'Searches with no results', value: data.searches ? `${percent(data.zeroResultSearches, data.searches)} (${data.zeroResultSearches.toLocaleString()} of ${data.searches.toLocaleString()})` : '—',
                  tone: data.searches && data.zeroResultSearches / data.searches > 0.1 ? 'amber' : undefined },
                { label: 'Proposal → contract', value: data.proposalContractConversionBps == null ? '—' : percent(data.proposalContractConversionBps, 10000) },
                { label: 'Median release time', value: data.medianReleaseLatencySeconds == null ? '—' : duration(data.medianReleaseLatencySeconds) },
                { label: 'Contract activations', value: data.activations.toLocaleString() },
                { label: 'Disputes opened / resolved', value: `${data.disputesOpened} / ${data.disputesResolved}`, tone: data.disputesOpened > data.disputesResolved ? 'amber' : undefined },
                ...(kpis ? [{ label: 'Disputes per 100 engagements', value: kpis.board.disputeRatePct ?? '—' }] : []),
              ]} />
            </Panel>
            {kpis && (
              <Panel title="Protected payment oversight" meta={pay ? `${pay.currency} · ${windowLabel}` : windowLabel}
                action={currencies.length > 1 && <select className="adm-filter" aria-label="Currency" value={pay?.currency ?? ''} onChange={(e) => setCurrency(e.target.value)}>
                  {currencies.map((c) => <option key={c.currency} value={c.currency}>{c.currency}</option>)}</select>}>
                {pay ? <div className="adm-mini-stats">
                  <div><div className="lbl">Escrow funded</div><div className="val">{formatMoney({ amountMinor: pay.fundedMinor, currency: pay.currency })}</div></div>
                  <div><div className="lbl">Released to professionals</div><div className="val">{formatMoney({ amountMinor: pay.releasedMinor, currency: pay.currency })}</div></div>
                  <div><div className="lbl">Held now</div><div className="val">{formatMoney({ amountMinor: pay.heldNowMinor, currency: pay.currency })}</div></div>
                  <div><div className="lbl">Frozen in disputes</div><div className="val">{formatMoney({ amountMinor: pay.frozenNowMinor, currency: pay.currency })}</div></div>
                  {exceptions != null && <div><div className="lbl">Payment exceptions open</div><div className="val">{exceptions}</div></div>}
                  <div><div className="lbl">Take rate</div><div className="val">{pay.takeRateBps == null ? '—' : `${(pay.takeRateBps / 100).toFixed(1)}%`}</div></div>
                </div> : <p className="muted small">No payments in this period.</p>}
                {currencies.length > 0 && <p className="adm-foot-note">All currencies: released {moneyList(kpis.board.grossReleasedByCurrency)} · fees {moneyList(kpis.board.feesByCurrency)}</p>}
              </Panel>
            )}
            <Panel title="Trust, risk & quality" meta="Actionable indicators">
              <MetricList rows={[
                ...(overview ? [{ label: 'Overdue verification decisions', value: overview.verification.overdue, tone: overview.verification.overdue ? 'red' as const : undefined, to: '/platform-admin/verification-center' },
                  { label: 'Open verification checks', value: overview.verification.open }] : []),
                ...(kpis ? [
                  { label: 'Open dispute cases', value: kpis.disputes.openNow, to: '/platform-admin/dispute-resolution' },
                  { label: 'Safety cases undecided', value: kpis.enforcement.openNow, tone: kpis.enforcement.openNow ? 'amber' as const : undefined, to: '/platform-admin/trust-safety' },
                  { label: 'Median hours to first safety decision', value: kpis.enforcement.medianHoursToFirstDecision ?? '—' },
                  { label: 'Incidents open now', value: kpis.enforcement.incidentsOpenNow, to: '/platform-admin/incident-command' },
                  { label: 'Serious incidents (SEV1–2) in period', value: kpis.board.seriousIncidents, tone: kpis.board.seriousIncidents ? 'red' as const : undefined },
                ] : []),
                ...(worker ? [{ label: 'Failed event deliveries', value: worker.deadLetters, tone: worker.deadLetters ? 'red' as const : 'green' as const, to: '/platform-admin/failed-event-deliveries' }] : []),
              ]} />
              <p className="adm-foot-note">Risk indicators prompt human review; analytics never restrict accounts or release funds.</p>
            </Panel>
          </PanelRow>

          {kpis && (
            <PanelRow>
              <Panel title="Onboarding & trust movement" meta={windowLabel}>
                <MetricList rows={[
                  { label: 'Profiles started', value: kpis.onboarding.profilesStarted }, { label: 'Profiles published', value: kpis.onboarding.profilesPublished },
                  { label: 'Reached Tier B', value: kpis.trust.reachedB }, { label: 'Reached Tier A', value: kpis.trust.reachedA },
                  { label: 'Downgraded', value: kpis.trust.downgrades, tone: kpis.trust.downgrades ? 'amber' : undefined },
                  { label: 'Verified supply (Tier A + B)', value: kpis.board.verifiedSupply },
                ]} />
              </Panel>
              <Panel title="Dispute outcomes" meta={windowLabel}>
                <MetricList rows={[
                  { label: 'Opened', value: kpis.disputes.opened }, { label: 'Decided', value: kpis.disputes.decided },
                  { label: 'Settled by the parties or mediation', value: kpis.disputes.decidedWithoutPlatform },
                  { label: 'Median days to decision', value: kpis.disputes.medianDaysToDecision ?? '—' },
                ]} />
                {Object.keys(kpis.disputes.byDecisionPath).length > 0 && <HBars rows={Object.entries(kpis.disputes.byDecisionPath).map(([k, v]) => ({ label: sentence(k.toLowerCase()), value: v }))} />}
              </Panel>
              <Panel title="Enforcement" meta={windowLabel}>
                <MetricList rows={[
                  { label: 'Cases opened', value: kpis.enforcement.casesOpened },
                  { label: 'Actions taken', value: Object.values(kpis.enforcement.actionsTaken).reduce((a, b) => a + b, 0) },
                ]} />
                {Object.keys(kpis.enforcement.incidentsBySeverity).length > 0 && <HBars rows={Object.entries(kpis.enforcement.incidentsBySeverity).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => ({ label: `Incidents ${k}`, value: v }))} />}
              </Panel>
            </PanelRow>
          )}

          {funnels && (
            <PanelRow>
              <Panel title="Professional onboarding funnel" meta={windowLabel}>
                <MetricList rows={[
                  { label: 'Visits that started onboarding', value: ob!.visitsStarted.toLocaleString() },
                  { label: 'Completion (published)', value: `${pctText(ob!.completionRatePct)} (${ob!.visitsPublished.toLocaleString()})` },
                  { label: 'Median sign-up → published', value: hoursText(ob!.medianHoursSignupToPublish) },
                ]} />
                {ob!.steps.length ? <HBars rows={ob!.steps.map((s) => ({ label: `${stepLabel(s.step)} · ${pctText(s.dropOffPct)} drop-off`, value: s.viewed }))} format={(v) => `${v.toLocaleString()} visits`} />
                  : <p className="muted small">No onboarding steps recorded in this period.</p>}
                <p className="adm-foot-note">Steps from the web app; the median time comes from profile records ({ob!.profilesPublished.toLocaleString()} published).</p>
              </Panel>
              <Panel title="Request & proposal funnel" meta={windowLabel}>
                <MetricList rows={[
                  { label: 'Visits that started a request', value: rq!.visitsStarted.toLocaleString() },
                  { label: 'Abandoned', value: `${pctText(rq!.abandonmentRatePct)} (${rq!.visitsAbandoned.toLocaleString()})`, tone: (rq!.abandonmentRatePct ?? 0) > 50 ? 'amber' : undefined },
                  { label: 'Requests sent', value: rq!.requestsSent.toLocaleString() },
                  { label: 'Proposals submitted / started', value: `${rq!.proposals.submitted} / ${rq!.proposals.started} (${pctText(rq!.proposals.completionRatePct)})` },
                ]} />
                {rq!.abandonedByStep.length > 0 && <HBars rows={rq!.abandonedByStep.map((a) => ({ label: `Left at ${stepLabel(a.step)}`, value: a.visits, color: CHART_COLORS[3] }))} />}
                {rq!.steps.length > 0 && <details style={{ marginTop: 10 }}><summary className="small">Per-step completion</summary>
                  <MetricList rows={rq!.steps.map((s) => ({ label: stepLabel(s.step), value: `${s.completed} of ${s.viewed} · ${pctText(s.dropOffPct)} drop-off` }))} /></details>}
              </Panel>
              <Panel title="Search micro-conversions" meta={`${sr!.searches.toLocaleString()} searches`}>
                <HBars rows={sr!.actions.map((a) => ({ label: ACTION_LABEL[a.event] ?? a.event, value: a.count }))}
                  format={(v) => (sr!.searches ? `${v.toLocaleString()} · ${(Math.round((1000 * v) / sr!.searches) / 10).toLocaleString()} per 100` : v.toLocaleString())} />
                {sr!.topFilters.length > 0 && <p className="adm-foot-note">Top filters: {sr!.topFilters.slice(0, 5).map((f) => `${stepLabel(f.value)} (${f.count})`).join(', ')}</p>}
                {sr!.topSpecializations.length > 0 && <p className="adm-foot-note">Top specializations: {sr!.topSpecializations.slice(0, 5).map((f) => `${stepLabel(f.value)} (${f.count})`).join(', ')}</p>}
              </Panel>
            </PanelRow>
          )}

          {kpis && (
            <PanelRow>
              <Panel title="Payment flow" meta={windowLabel}>
                <MetricList rows={[
                  { label: 'Median submit → acceptance', value: hoursText(kpis.payments.acceptance?.medianHoursSubmitToAccept) },
                  { label: '90th percentile submit → acceptance', value: hoursText(kpis.payments.acceptance?.p90HoursSubmitToAccept) },
                  { label: 'Payments captured', value: (kpis.payments.paymentsCaptured ?? 0).toLocaleString() },
                  { label: 'Refunds per 100 payments', value: kpis.payments.refundsPer100Payments ?? '—', tone: (kpis.payments.refundsPer100Payments ?? 0) > 10 ? 'amber' : undefined },
                  { label: 'Disputes per 100 payments', value: kpis.payments.disputesPer100Payments ?? '—', tone: (kpis.payments.disputesPer100Payments ?? 0) > 5 ? 'amber' : undefined },
                ]} />
                {(kpis.payments.refundsByCurrency ?? []).some((r) => r.refunds) && <p className="adm-foot-note">Refunded: {moneyList((kpis.payments.refundsByCurrency ?? []).filter((r) => r.refunds).map((r) => ({ currency: r.currency, amountMinor: r.refundedMinor })))}</p>}
              </Panel>
              <Panel title="Approval bottlenecks" meta={approvals ? `${approvals.requests} requests · ${approvals.pendingNow} pending` : windowLabel}>
                {!approvals || approvals.steps.length === 0 ? <p className="muted small">No policy approvals in this period.</p> : <>
                  <HBars rows={approvals.steps.map((s) => ({ label: `Step ${s.step} · ${label(s.role)}`, value: s.medianHoursWait ?? 0 }))} format={(v) => hoursText(v)} />
                  {approvals.bottleneck && <p className="adm-foot-note">Slowest: step {approvals.bottleneck.step} ({label(approvals.bottleneck.role)}), median {hoursText(approvals.bottleneck.medianHoursWait)}, {approvals.bottleneck.pending} waiting now.</p>}
                </>}
              </Panel>
              <Panel title="Dispute & enforcement quality" meta={windowLabel}>
                <MetricList rows={[
                  { label: 'Disputes escalated to mediation', value: pctText(kpis.disputes.escalationRatePct) },
                  { label: 'Evidence complete from both parties', value: pctText(kpis.disputes.evidenceCompletenessPct) },
                  { label: 'Appeals per decided dispute', value: pctText(kpis.disputes.appealRatePct) },
                  { label: 'Repeat disputes (organisations / professionals)', value: `${kpis.disputes.repeatOrganisations ?? 0} / ${kpis.disputes.repeatProfessionals ?? 0}`,
                    tone: (kpis.disputes.repeatOrganisations ?? 0) + (kpis.disputes.repeatProfessionals ?? 0) ? 'amber' : undefined },
                  { label: 'Enforcement reversal rate', value: pctText(kpis.enforcement.reversalRatePct) },
                  { label: 'Appeal success rate', value: `${pctText(kpis.enforcement.appealSuccessRatePct)} of ${kpis.enforcement.appealsDecided ?? 0}` },
                  { label: 'Recurring violations (subjects)', value: kpis.enforcement.recurringSubjects ?? 0, tone: kpis.enforcement.recurringSubjects ? 'red' : undefined },
                ]} />
                {Object.keys(kpis.enforcement.byLevel ?? {}).length > 0 && <HBars rows={Object.entries(kpis.enforcement.byLevel ?? {}).map(([k, v]) => ({ label: `Level ${k.slice(1)}`, value: v }))} />}
              </Panel>
            </PanelRow>
          )}

          {kpis && (
            <PanelRow cols={2}>
              <Panel title="Trust tier trend" meta="From the tier history">
                {tierTrend.length > 1 ? <TrendChart kind="line" labels={tierTrend.map((p) => axisLabel(p.date.slice(0, 10)))} series={(['A', 'B', 'C'] as const).map((t) => ({
                  label: `Tier ${t}`, values: tierTrend.map((p) => p[t]), color: TIER_COLORS[t] }))} />
                  : <p className="muted small">Not enough tier history in this period.</p>}
                <p className="adm-foot-note">Professionals with a recorded tier at the end of each interval.</p>
              </Panel>
              <Panel title="Board indicators" meta={windowLabel}>
                <MetricList rows={[
                  { label: 'Enforcement reversal rate', value: pctText(kpis.board.enforcementReversalRatePct) },
                  { label: 'Credential-expiry incidents', value: kpis.board.credentialExpiryIncidents ?? 0, tone: kpis.board.credentialExpiryIncidents ? 'amber' : undefined },
                  { label: 'Enterprise Ready decisions (approved)', value: `${kpis.board.enterpriseOnboarding?.decided ?? 0} (${kpis.board.enterpriseOnboarding?.approved ?? 0})` },
                  { label: 'Enterprise onboarding cycle (median)', value: kpis.board.enterpriseOnboarding?.medianDaysToDecision == null ? '—' : `${kpis.board.enterpriseOnboarding.medianDaysToDecision} days` },
                  { label: 'Enterprise applications waiting', value: kpis.board.enterpriseOnboarding?.pendingNow ?? 0 },
                ]} />
              </Panel>
            </PanelRow>
          )}

          <Panel title="Events by area" meta={`${Object.values(data.eventCounts).reduce((s, n) => s + n, 0).toLocaleString()} events recorded`}>
            {groups.length === 0 ? <p className="muted small">No events recorded yet.</p> : <>
              <HBars rows={groups.map((g) => ({ label: g.title, value: g.total }))} format={(v) => v.toLocaleString()} />
              <details style={{ marginTop: 10 }}>
                <summary className="small">Every event type</summary>
                <MetricList rows={groups.flatMap((g) => g.events.map((e) => ({ label: <span title={e.name}>{g.title} · {e.label}</span>, value: e.count.toLocaleString() })))} />
              </details>
            </>}
          </Panel>
          <p className="adm-foot-note">Projections of the audit ledger. Aggregates are role-scoped; money is reported per currency.</p>
        </>
      )}
    </>
  )
}
