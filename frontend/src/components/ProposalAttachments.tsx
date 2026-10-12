import { useState } from 'react'
import { proposalApi, type Proposal } from '../api/proposals'
import { DOC_ACCEPT, toUpload } from '../api/files'
import { FileLink } from './FileLink'
import { ErrorAlert } from './ui'
export function ProposalAttachments({ proposal, editable = false, onChange }: {
  proposal: Proposal; editable?: boolean; onChange?: (p: Proposal) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  return <section className="card panel"><h3>Proposal supporting documents</h3><ErrorAlert error={error} />
    {(proposal.attachments ?? []).map(f => <div key={f.sha256}>
      <FileLink file={f} url={`/v1/proposals/${proposal.id}/attachments/${f.sha256}`} />
      {editable && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={async () => {
        setBusy(true); setError(null)
        try { onChange?.(await proposalApi.removeProposalFile(proposal.id, f.sha256)) }
        catch (err) { setError(err) } finally { setBusy(false) }
      }}>Remove {f.name}</button>}
    </div>)}
    {editable && <label className="filter-box">Attach portfolio or supporting documents
      <input type="file" multiple accept={DOC_ACCEPT} disabled={busy} onChange={async e => {
        const files = Array.from(e.target.files ?? []); e.target.value = ''
        if (!files.length) return
        setBusy(true); setError(null)
        try { onChange?.(await proposalApi.addProposalFiles(proposal.id, await Promise.all(files.map(f => toUpload(f))))) }
        catch (err) { setError(err) } finally { setBusy(false) }
      }} /></label>}
  </section>
}
