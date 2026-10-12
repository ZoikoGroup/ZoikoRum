import { useState } from 'react'
import { searchApi, type IntentFilters } from '../api/search'
import { Icon } from './dashboard'
import { ErrorAlert } from './ui'

/* "Describe what you need": the buyer writes their need in their own words; AI (or keyword rules) turns it into the
   ordinary filters on this page, each with the reason it was chosen. AI assists, the buyer decides: every filter shows
   in the active-filter bar and can be removed or changed. */

export function DescribeNeed({ onApply }: { onApply: (filters: IntentFilters) => void }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [read, setRead] = useState<{ reasons: string[]; ai: boolean } | null>(null)

  async function find() {
    setBusy(true); setError(null)
    try {
      const r = await searchApi.intent(text.trim())
      setRead({ reasons: r.reasons, ai: r.source.startsWith('ai:') })
      onApply(r.filters)
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  if (!open) return (
    <p className="small" style={{ margin: '0 0 12px' }}>Not sure what to search for?{' '}
      <button type="button" className="link-btn small" style={{ display: 'inline', padding: 0 }} onClick={() => setOpen(true)}>Describe what you need</button></p>
  )
  return (
    <div className="describe-need" style={{ marginBottom: 14 }}>
      <label className="filter-label" htmlFor="describe-need">Describe what you need</label>
      <ErrorAlert error={error} />
      <textarea id="describe-need" className="input" rows={2} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="e.g. An ongoing fractional CFO in Germany who can start now, remote is fine" />
      <div className="row" style={{ marginTop: 8 }}>
        <button type="button" className="btn btn-secondary btn-sm" disabled={busy || text.trim().length < 3} onClick={find}>
          {busy ? 'Reading…' : 'Find matches'}</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setOpen(false); setRead(null) }}>Close</button>
      </div>
      {read && <div className="tip" role="status" style={{ marginTop: 10 }}><Icon name="search" /><span>
        {read.reasons.length > 0 ? <>
          <strong>{read.ai ? 'We read your request with AI as:' : 'We read your request as:'}</strong>
          <ul style={{ margin: '4px 0', paddingLeft: 18 }}>{read.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          These are ordinary filters. Check them, and remove or change any that are wrong.</>
          : <>We couldn't pick out filters from that. Try naming the expertise (for example “transfer pricing”) or use the filters below.</>}
      </span></div>}
    </div>
  )
}
