import { useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert } from './ui'
interface Suggestion { slug: string; name: string }
interface Result { specializations: Suggestion[]; fallbackUsed: boolean; disclaimer: string }
export function MatchingAssistance({ query, onApply }: { query: string; onApply: (slugs: string[]) => void }) {
  const [result, setResult] = useState<{ query: string; value: Result } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const current = result?.query === query ? result.value : null
  return <div style={{ marginTop: 12 }}><ErrorAlert error={error} />
    <button type="button" className="btn btn-secondary btn-sm" disabled={busy || query.trim().length < 3 || query.length > 200} onClick={async () => {
      setBusy(true); setError(null)
      try { setResult({ query, value: await api<Result>('/v1/ai/match-intent', { method: 'POST', body: { query: query.trim() } }) }) }
      catch (err) { setError(err) } finally { setBusy(false) }
    }}>{busy ? 'Preparing suggestions…' : 'Suggest expertise for this search'}</button>
    {current && <div role="status"><p className="muted small">{current.disclaimer}</p>
      <p className="small">{current.fallbackUsed ? 'Keyword suggestions' : 'Approved AI suggestions'}: {current.specializations.map(s => s.name).join(', ') || 'No supported expertise identified. Choose filters manually.'}</p>
      {current.specializations.length > 0 && <button type="button" className="btn btn-sm" onClick={() => onApply(current.specializations.map(s => s.slug))}>Apply suggested expertise</button>}
    </div>}
  </div>
}
