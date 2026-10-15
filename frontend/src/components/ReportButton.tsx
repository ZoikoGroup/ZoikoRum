import { useState } from 'react'
import { REPORT_CATEGORIES, reportApi, type ReportCategory, type ReportSubject } from '../api/reports'
import { ErrorAlert, useDialog } from './ui'

/** "Report" for a profile, account, organisation, review or message. Trust & Safety reviews every report; the person
    reported is never told who reported. */
export function ReportButton({ subjectType, subjectId, what, className = 'btn btn-ghost btn-sm' }: {
  subjectType: ReportSubject; subjectId: string; what: string; className?: string
}) {
  const [open, setOpen] = useState(false)
  const [sent, setSent] = useState(false)
  if (sent) return <span className="muted small" role="status">Reported. Thank you.</span>
  return <>
    <button type="button" className={className} onClick={() => setOpen(true)}>Report</button>
    {open && <ReportDialog subjectType={subjectType} subjectId={subjectId} what={what} onClose={() => setOpen(false)}
      onSent={() => { setOpen(false); setSent(true) }} />}
  </>
}

function ReportDialog({ subjectType, subjectId, what, onClose, onSent }: {
  subjectType: ReportSubject; subjectId: string; what: string; onClose: () => void; onSent: () => void
}) {
  const dialog = useDialog(onClose)
  const [category, setCategory] = useState<ReportCategory>(subjectType === 'REVIEW' ? 'FAKE_REVIEW' : 'OFF_PLATFORM_PAYMENT')
  const [description, setDescription] = useState('')
  const [confidential, setConfidential] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  return (
    <div ref={dialog} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="report-title" onClick={onClose}>
      <form className="card modal fund-modal" onClick={(e) => e.stopPropagation()} onSubmit={async (e) => {
        e.preventDefault(); setBusy(true); setError(null)
        try { await reportApi.submit({ subjectType, subjectId, category, description: description.trim(), confidential }); onSent() }
        catch (err) { setError(err) } finally { setBusy(false) }
      }}>
        <h2 id="report-title">Report {what}</h2>
        <p className="muted small">Our Trust &amp; Safety team reviews every report. The person you report is never told who reported
          them, and a report alone never restricts anyone. Use a dispute for disagreements about delivered work.</p>
        <ErrorAlert error={error} />
        <label className="label" htmlFor="report-category">What is the problem?</label>
        <select id="report-category" className="input" value={category} onChange={(e) => setCategory(e.target.value as ReportCategory)}>
          {REPORT_CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <label className="label" htmlFor="report-description" style={{ marginTop: 10 }}>What happened? (at least 20 characters)</label>
        <textarea id="report-description" className="input" rows={4} maxLength={2000} value={description}
          onChange={(e) => setDescription(e.target.value)} required />
        <label className="checkbox" style={{ marginTop: 10 }}><input type="checkbox" checked={confidential} onChange={(e) => setConfidential(e.target.checked)} />
          <span>Keep my name from the case handler too (only senior Trust &amp; Safety and Legal can see it)</span></label>
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}>
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || description.trim().length < 20}>{busy ? 'Sending…' : 'Send report'}</button>
        </div>
      </form>
    </div>
  )
}
