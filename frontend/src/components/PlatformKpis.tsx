import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { formatMoney } from '../api/orgs'
import { ErrorAlert } from './ui'

interface Kpis {
  from: string; to: string
  board: { grossReleasedByCurrency: { currency: string; amountMinor: number }[]; feesByCurrency: { currency: string; amountMinor: number }[]
    engagementsStarted: number; activeBuyerOrganisations: number; disputeRatePct: number | null; verifiedSupply: number; seriousIncidents: number }
  onboarding: { profilesStarted: number; profilesPublished: number; publishedNow: number; enterpriseReadyNow: number }
  trust: { tiersNow: Record<string, number>; reachedB: number; reachedA: number; downgrades: number }
  engagements: { engagementsStarted: number; engagementsCompleted: number; runningNow: number; activeBuyerOrganisations: number; activeProfessionals: number }
  payments: { byCurrency: { currency: string; fundedMinor: number; releasedMinor: number; feesMinor: number; heldNowMinor: number; frozenNowMinor: number; takeRateBps: number | null }[] }
  disputes: { opened: number; decided: number; openNow: number; medianDaysToDecision: number | null; decidedWithoutPlatform: number; byDecisionPath: Record<string, number> }
  enforcement: { casesOpened: number; openNow: number; medianHoursToFirstDecision: number | null; actionsTaken: Record<string, number>; incidentsOpenNow: number; incidentsBySeverity: Record<string, number> }
}

const money = (list: { currency: string; amountMinor: number }[]) =>
  list.length ? list.map((x) => formatMoney({ amountMinor: x.amountMinor, currency: x.currency })).join(' + ') : '—'

function Block({ title, rows }: { title: string; rows: [string, React.ReactNode][] }) {
  return (
    <div className="card panel" style={{ flex: 1, minWidth: 240 }}>
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      <ul className="checklist small">{rows.map(([k, v]) => <li key={k}><span>{k}</span><strong>{v}</strong></li>)}</ul>
    </div>
  )
}

/** Platform KPIs for staff and the board, for a chosen period. */
export function PlatformKpis() {
  const [days, setDays] = useState(30)
  const [k, setK] = useState<Kpis | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    const to = new Date()
    const from = new Date(to.getTime() - days * 86400_000)
    api<Kpis>('/v1/admin/kpis', { query: { from: from.toISOString(), to: to.toISOString() } }).then(setK).catch(setError)
  }, [days])
  if (error) return <ErrorAlert error={error} />
  if (!k) return <div className="card panel skeleton" style={{ height: 160 }} aria-busy="true" />
  const tiers = k.trust.tiersNow
  return (
    <section style={{ marginBottom: 20 }}>
      <div className="panel-head"><h2>Key figures</h2>
        <select className="input" aria-label="Period" style={{ maxWidth: 170 }} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90, 365].map((n) => <option key={n} value={n}>Last {n} days</option>)}</select></div>
      <div className="row" style={{ alignItems: 'stretch', flexWrap: 'wrap' }}>
        <Block title="Board" rows={[['Released to professionals', money(k.board.grossReleasedByCurrency)], ['Platform fees', money(k.board.feesByCurrency)],
          ['Engagements started', k.board.engagementsStarted], ['Active buyer organisations', k.board.activeBuyerOrganisations],
          ['Disputes per 100 engagements', k.board.disputeRatePct ?? '—'], ['Verified professionals (Green + Amber)', k.board.verifiedSupply],
          ['Serious incidents (SEV1–2)', k.board.seriousIncidents]]} />
        <Block title="Onboarding" rows={[['Profiles started', k.onboarding.profilesStarted], ['Profiles published', k.onboarding.profilesPublished],
          ['Reached Amber', k.trust.reachedB], ['Reached Green', k.trust.reachedA], ['Downgraded', k.trust.downgrades],
          ['Live now', k.onboarding.publishedNow], ['Enterprise Ready now', k.onboarding.enterpriseReadyNow],
          ['Trust lights now (Green / Amber / Red)', `${tiers.A ?? 0} / ${tiers.B ?? 0} / ${tiers.C ?? 0}`]]} />
        <Block title="Engagements" rows={[['Started', k.engagements.engagementsStarted], ['Completed', k.engagements.engagementsCompleted],
          ['Running now', k.engagements.runningNow], ['Professionals engaged', k.engagements.activeProfessionals]]} />
      </div>
      <div className="row" style={{ alignItems: 'stretch', flexWrap: 'wrap', marginTop: 12 }}>
        <Block title="Money through escrow" rows={k.payments.byCurrency.length ? k.payments.byCurrency.flatMap((r) => [
          [`Funded (${r.currency})`, formatMoney({ amountMinor: r.fundedMinor, currency: r.currency })],
          [`Released (${r.currency})`, formatMoney({ amountMinor: r.releasedMinor, currency: r.currency })],
          [`Held now (${r.currency})`, formatMoney({ amountMinor: r.heldNowMinor, currency: r.currency })],
          [`Frozen in disputes (${r.currency})`, formatMoney({ amountMinor: r.frozenNowMinor, currency: r.currency })],
          [`Take rate (${r.currency})`, r.takeRateBps == null ? '—' : `${(r.takeRateBps / 100).toFixed(1)}%`]] as [string, string][]) : [['No payments yet', '—']]} />
        <Block title="Disputes" rows={[['Opened', k.disputes.opened], ['Decided', k.disputes.decided], ['Open now', k.disputes.openNow],
          ['Settled by the parties or mediation', k.disputes.decidedWithoutPlatform], ['Median days to decision', k.disputes.medianDaysToDecision ?? '—']]} />
        <Block title="Trust & safety" rows={[['Cases opened', k.enforcement.casesOpened], ['Undecided now', k.enforcement.openNow],
          ['Median hours to first decision', k.enforcement.medianHoursToFirstDecision ?? '—'],
          ['Actions taken', Object.values(k.enforcement.actionsTaken).reduce((a, b) => a + b, 0)], ['Incidents open now', k.enforcement.incidentsOpenNow]]} />
      </div>
      <p className="muted small">{new Date(k.from).toLocaleDateString()} to {new Date(k.to).toLocaleDateString()}. Money is shown per currency, never converted.</p>
    </section>
  )
}
