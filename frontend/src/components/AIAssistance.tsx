import { useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert } from './ui'

export function AIAssistance({ purpose, subjectId }: { purpose: 'proposal-draft' | 'contract-summary' | 'dispute-summary'; subjectId: string }) {
  const [result, setResult] = useState<{ text: string; disclaimer: string; fallbackUsed: boolean; documentHash?: string } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  return <section className="card panel"><h2>Drafting and summary assistance</h2><ErrorAlert error={error} />
    <button className="btn" disabled={busy} onClick={async () => { setBusy(true); setError(null); try { setResult(await api(`/v1/ai/${purpose}`, { method: 'POST', body: { [purpose === 'proposal-draft' ? 'requestId' : purpose === 'contract-summary' ? 'contractId' : 'disputeId']: subjectId } })) } catch (err) { setError(err) } finally { setBusy(false) } }}>{busy ? 'Preparing…' : purpose === 'proposal-draft' ? 'Prepare proposal draft' : 'Summarise source records'}</button>
    {result && <><p className="muted">{result.disclaimer}</p><p className="small">{result.fallbackUsed ? 'Deterministic fallback from source records' : 'Approved prompt output'}</p><pre style={{ whiteSpace: 'pre-wrap' }}>{result.text}</pre>{result.documentHash && <p className="small">Document hash: {result.documentHash}</p>}<button className="btn" onClick={() => navigator.clipboard.writeText(result.text).catch(setError)}>Copy working draft</button></>}
  </section>
}
