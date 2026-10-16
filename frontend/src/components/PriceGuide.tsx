import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { formatMoney } from '../api/orgs'

interface Range { low: number; typical: number; high: number; sampleSize: number }
interface Estimate { basis: { level: string; name: string } | null; engagements: Range | null; rates: Record<string, Range>; minimumSample: number }

const UNIT: Record<string, string> = { HOUR: 'per hour', DAY: 'per day', MONTH: 'per month', PROJECT: 'per project' }

/** What engagements like this usually cost on Zoikorum (middle half of the range), to set a realistic budget. */
export function PriceGuide({ specialization, currency, engagementType }: { specialization: string | null; currency: string; engagementType?: string }) {
  const [e, setE] = useState<Estimate | null>(null)
  useEffect(() => {
    if (!specialization) return
    api<Estimate>('/v1/pricing/estimate', { query: { specialization, currency, ...(engagementType ? { engagementType } : {}) } })
      .then(setE).catch(() => setE(null))
  }, [specialization, currency, engagementType])
  if (!specialization || !e) return null
  const m = (n: number) => formatMoney({ amountMinor: n, currency })
  if (!e.basis) return <p className="muted small">Not enough engagements in {currency} yet to show a typical price for this work.</p>
  return (
    <div className="tip" role="note" style={{ marginBottom: 12 }}>
      <span><strong>Typical prices for {e.basis.name}{e.basis.level === 'category' ? ' (whole category)' : ''}</strong>
        {e.engagements && <><br />Engagements: {m(e.engagements.low)} to {m(e.engagements.high)}, usually around {m(e.engagements.typical)}
          <span className="muted"> ({e.engagements.sampleSize} accepted proposals)</span></>}
        {Object.entries(e.rates).map(([unit, r]) => <span key={unit}><br />Published rates: {m(r.low)} to {m(r.high)} {UNIT[unit] ?? ''}
          <span className="muted"> ({r.sampleSize} professionals)</span></span>)}
        <br /><span className="muted">The middle half of prices on Zoikorum, from at least {e.minimumSample} data points. A guide, not a quote.</span></span>
    </div>
  )
}
