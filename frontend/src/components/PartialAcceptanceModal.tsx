import { useState, type FormEvent } from 'react'
import { contractApi, type Contract, type ContractMilestone } from '../api/contracts'
import { formatMoney } from '../api/orgs'
import { ErrorAlert } from './ui'

export function PartialAcceptanceModal({ milestone, onClose, onSuccess }: {
  milestone: ContractMilestone; onClose: () => void; onSuccess: (contract: Contract) => void
}) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const minor = Number(amount)
  const valid = Number.isSafeInteger(minor) && minor > 0 && minor < milestone.amount.amountMinor && reason.trim().length >= 10
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!valid || busy) return
    setBusy(true); setError(null)
    try { onSuccess(await contractApi.offerPartial(milestone.id, minor, reason.trim())); onClose() }
    catch (err) { setError(err) } finally { setBusy(false) }
  }
  return <section className="card panel" role="dialog" aria-modal="true" aria-label="Offer partial acceptance">
    <h2>Offer partial acceptance</h2><ErrorAlert error={error} />
    <p>The professional must agree before funds move. The remaining amount is refunded to the buyer.</p>
    <form onSubmit={submit}>
      <label className="filter-box">Release amount in minor currency units ({milestone.amount.currency})
        <input type="number" min="1" max={milestone.amount.amountMinor - 1} step="1" required value={amount} onChange={e => setAmount(e.target.value)} /></label>
      {valid && <p>Release: {formatMoney({ ...milestone.amount, amountMinor: minor })} · Refund: {formatMoney({ ...milestone.amount, amountMinor: milestone.amount.amountMinor - minor })}</p>}
      <label className="filter-box">Reason against the acceptance criteria
        <textarea required minLength={10} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /></label>
      <button className="btn btn-primary" disabled={busy || !valid}>Offer</button>
      <button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>Cancel</button>
    </form>
  </section>
}
