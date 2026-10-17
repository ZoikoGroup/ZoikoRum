import { useState, type FormEvent, type ReactNode } from 'react'
import { useDialog } from './ui'

/** Confirmation for a decision made straight from a dashboard row (Buyer Dashboard s.8/s.10, Professional Dashboard
    s.7): plain, irreversible wording, and an optional structured reason with a private note. */
export function DecisionDialog<R extends string>({ title, children, confirmLabel, danger, reasons, busy, onConfirm, onCancel }: {
  title: string
  children: ReactNode
  confirmLabel: string
  danger?: boolean
  reasons?: [R, string][]
  busy?: boolean
  onConfirm: (reason: R | null, note: string | undefined) => void
  onCancel: () => void
}) {
  const dialog = useDialog(onCancel)
  const [reason, setReason] = useState<R | null>(reasons?.[0]?.[0] ?? null)
  const [note, setNote] = useState('')
  function submit(e: FormEvent) {
    e.preventDefault()
    onConfirm(reason, note.trim() || undefined)
  }
  return (
    <div ref={dialog} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="decision-title">
      <form className="card modal" onSubmit={submit}>
        <h2 id="decision-title">{title}</h2>
        <div className="muted">{children}</div>
        {reasons && <>
          <div className="field">
            <label htmlFor="decision-reason">Reason</label>
            <select id="decision-reason" className="input" value={reason ?? ''} onChange={(e) => setReason(e.target.value as R)}>
              {reasons.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="decision-note">Note (optional, private)</label>
            <input id="decision-note" className="input" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </>}
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} disabled={busy}>{busy ? 'Working…' : confirmLabel}</button>
        </div>
      </form>
    </div>
  )
}
