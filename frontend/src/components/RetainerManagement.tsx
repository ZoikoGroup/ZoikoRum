import { useState } from 'react'
import { contractApi, MILESTONE_STATUS, type Contract } from '../api/contracts'
import { formatMoney } from '../api/orgs'
import { ErrorAlert } from './ui'

export function RetainerManagement({ contract, onChange, controlsOnly = false }: { contract: Contract; onChange: (c: Contract) => void; controlsOnly?: boolean }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  if (contract.pricingModel !== 'RETAINER' && contract.engagementType !== 'RETAINER') return null
  const unfunded = contract.milestones.filter(m => m.status === 'PENDING_FUNDING')
  return <section className="card panel"><h2>{controlsOnly ? 'Future funding' : 'Retainer cycles'}</h2><ErrorAlert error={error} />
    <p role="status">Future cycle funding: {contract.retainerPaused ? 'Paused' : 'Active'}</p>
    <p>Each signed cycle is funded separately and accepted manually. Cancelling remaining cycles leaves funded work and signed terms intact.</p>
    {!controlsOnly && <ul>{contract.milestones.map(m => <li key={m.id}>Cycle {m.sequence}: {m.title} · {m.dueDate ?? 'No due date'} · {formatMoney(m.amount)} · {MILESTONE_STATUS[m.status].label}</li>)}</ul>}
    {contract.viewerRole === 'BUYER' && contract.status === 'ACTIVE' && unfunded.length > 0 && <>
      <label className="filter-box">Reason for changing the {unfunded.length} unfunded cycles
        <textarea minLength={5} maxLength={500} value={reason} onChange={e => setReason(e.target.value)} /></label>
      <button className="btn btn-secondary" disabled={busy || reason.trim().length < 5} onClick={async () => {
        setBusy(true); setError(null)
        try { onChange(await contractApi.setRetainerPause(contract.id, !contract.retainerPaused, reason.trim())) }
        catch (err) { setError(err) } finally { setBusy(false) }
      }}>{contract.retainerPaused ? 'Resume future cycle funding' : 'Pause future cycle funding'}</button>
      {!controlsOnly && <button className="btn btn-secondary" disabled={busy || reason.trim().length < 5} onClick={async () => {
        if (!confirm('Cancel all remaining unfunded cycles? Funded cycles will continue.')) return
        setBusy(true); setError(null)
        try { onChange(await contractApi.cancelRemainingCycles(contract.id, reason.trim())); setReason('') }
        catch (err) { setError(err) } finally { setBusy(false) }
      }}>Cancel unfunded cycles</button>}
    </>}
  </section>
}
