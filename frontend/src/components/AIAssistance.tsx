import { useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert } from './ui'

type Purpose = 'proposal-draft' | 'contract-summary' | 'dispute-summary'

/** Record what a person did with an AI suggestion (the audit trail shows a human decided, never the AI). */
export const recordAIOutcome = (purpose: string, subjectId: string | null, outcome: 'USED' | 'EDITED' | 'DISCARDED') =>
  api<void>('/v1/ai/outcomes', { method: 'POST', body: { purpose, subjectId, outcome } }).catch(() => {})

export function AIAssistance({ purpose, subjectId }: { purpose: Purpose; subjectId: string }) {
  const [result, setResult] = useState<{ text: string; disclaimer: string; fallbackUsed: boolean; documentHash?: string } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [decided, setDecided] = useState<string | null>(null)
  const key = purpose === 'proposal-draft' ? 'requestId' : purpose === 'contract-summary' ? 'contractId' : 'disputeId'
  return (
    <section className="card panel">
      <h2>Drafting and summary assistance</h2>
      <ErrorAlert error={error} />
      <button className="btn" disabled={busy} onClick={async () => {
        setBusy(true); setError(null); setDecided(null)
        try { setResult(await api(`/v1/ai/${purpose}`, { method: 'POST', body: { [key]: subjectId } })) } catch (err) { setError(err) } finally { setBusy(false) }
      }}>{busy ? 'Preparing…' : purpose === 'proposal-draft' ? 'Prepare proposal draft' : 'Summarise source records'}</button>
      {result && <>
        <p className="ai-disclosure"><span className="badge">{result.fallbackUsed ? 'Generated from records (no AI)' : 'AI-assisted'}</span>
          <span className="muted small"> {result.disclaimer} You decide what to use; nothing is sent or decided automatically.</span></p>
        <pre style={{ whiteSpace: 'pre-wrap' }}>{result.text}</pre>
        {result.documentHash && <p className="small">Document hash: {result.documentHash}</p>}
        {decided ? <p className="muted small" role="status">{decided}</p> : <div className="row">
          <button className="btn btn-secondary btn-sm" onClick={() => navigator.clipboard.writeText(result.text)
            .then(() => { recordAIOutcome(purpose, subjectId, 'USED'); setDecided('Copied. Edit it before you rely on it.') }).catch(setError)}>Use (copy)</button>
          <button className="btn btn-ghost btn-sm" onClick={() => { recordAIOutcome(purpose, subjectId, 'DISCARDED'); setDecided('Discarded.'); setResult(null) }}>Discard</button>
        </div>}
      </>}
    </section>
  )
}
