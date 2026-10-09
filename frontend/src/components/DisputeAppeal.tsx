import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { DOC_ACCEPT, toUpload, type StoredFile, type Upload } from '../api/files'
import { FileLinks } from './FileLink'
import { ErrorAlert, useStepUp } from './ui'

interface Appeal { id: string; grounds: string; explanation: string; evidence: StoredFile[]; status: string; reason: string | null; remediation: string | null }

export function DisputeAppealPanel({ caseId, canFile, canReview }: { caseId: string; canFile: boolean; canReview: boolean }) {
  const [appeal, setAppeal] = useState<Appeal | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [files, setFiles] = useState<Upload[]>([])
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)
  const url = `/v1/disputes/${caseId}/appeal`
  useEffect(() => { api<Appeal | null>(url).then(setAppeal).catch(setError) }, [url])
  async function submit(body: unknown, decision = false) {
    setBusy(true); setError(null)
    try {
      const action = () => api<Appeal>(url + (decision ? '/decision' : ''), { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID() } })
      if (decision) await run(async () => { setAppeal(await action()) })
      else setAppeal(await action())
    } catch (err) { setError(err) } finally { setBusy(false) }
  }
  return <section className="card panel"><h2>Independent appeal</h2><ErrorAlert error={error} />{modal}
    <p className="muted small">Appeals must be filed within 14 days of a platform decision. The original decision and payment records remain preserved.</p>
    {appeal ? <><p><strong>{appeal.status}</strong> · {appeal.grounds.replaceAll('_', ' ')}</p><p>{appeal.explanation}</p>
      <FileLinks files={appeal.evidence} url={f => `${url}/files/${f.sha256}`} />
      {appeal.reason && <p>Review: {appeal.reason}</p>}{appeal.remediation && <p>Follow-up remedy: {appeal.remediation}</p>}
      {canReview && appeal.status === 'PENDING' && <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); submit(Object.fromEntries(data), true) }}>
        <select name="outcome" className="input"><option value="REJECTED">Reject appeal</option><option value="UPHELD">Uphold appeal</option></select>
        <textarea className="input" name="reason" required minLength={20} maxLength={4000} placeholder="Reason for the independent decision" />
        <textarea className="input" name="remediation" maxLength={4000} placeholder="Follow-up remedy (required when upheld)" />
        <button className="btn btn-primary" disabled={busy}>Record appeal decision</button></form>}</> : canFile && <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); submit({ grounds: data.get('grounds'), explanation: data.get('explanation'), evidence: files }) }}>
      <select name="grounds" className="input"><option value="NEW_MATERIAL_EVIDENCE">New material evidence</option><option value="PROCEDURAL_ERROR">Procedural error</option></select>
      <textarea className="input" name="explanation" required minLength={20} maxLength={4000} placeholder="Explain the grounds for your appeal" />
      <input type="file" multiple accept={DOC_ACCEPT} aria-label="Appeal evidence" onChange={e => { Promise.all(Array.from(e.target.files ?? []).map(file => toUpload(file))).then(setFiles).catch(setError) }} />
      <button className="btn btn-primary" disabled={busy}>Submit appeal</button></form>}</section>
}
