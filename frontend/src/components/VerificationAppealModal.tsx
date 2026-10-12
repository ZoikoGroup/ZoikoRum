import { useState, type FormEvent } from 'react'
import { verificationApi, type VerificationCase } from '../api/verification'
import { ErrorAlert } from './ui'
export function VerificationAppealModal({ verificationId, onClose, onSuccess }: {
  verificationId: string; onClose: () => void; onSuccess: (c: VerificationCase) => void
}) {
  const [statement, setStatement] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null)
    try { onSuccess(await verificationApi.appeal(verificationId, statement.trim())); onClose() }
    catch (err) { setError(err) } finally { setBusy(false) }
  }
  return <section className="card panel" role="dialog" aria-modal="true" aria-label="Appeal verification decision">
    <h2>Appeal verification decision</h2><ErrorAlert error={error} />
    <form onSubmit={submit}><label className="filter-box">Why should this decision be reviewed?
      <textarea required minLength={20} maxLength={2000} value={statement} onChange={e => setStatement(e.target.value)} /></label>
      <p>After submitting, add supporting documents to the case. An independent compliance officer reviews the appeal.</p>
      <button className="btn btn-primary" disabled={busy || statement.trim().length < 20}>Submit appeal</button>
      <button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>Cancel</button>
    </form>
  </section>
}
