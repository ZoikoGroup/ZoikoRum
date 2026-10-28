import { useState } from 'react'
import { exportAuditFile, type AuditFormat } from '../api/audit'
import { saveBlob } from '../lib/exports'
import { Icon } from './dashboard'

const FORMATS: { key: AuditFormat; label: string }[] = [{ key: 'pdf', label: 'PDF' }, { key: 'csv', label: 'CSV' }, { key: 'json', label: 'JSON' }]

/** Export of the organisation's hash-chained audit log as PDF, CSV or JSON (Org Admins and Legal Reviewers; the server
    checks the same permission for every format). */
export function AuditExportButtons({ orgId, fileStem, onError, onDone }: {
  orgId: string; fileStem: string; onError: (err: unknown) => void; onDone?: (format: AuditFormat) => void
}) {
  const [busy, setBusy] = useState<AuditFormat | null>(null)
  async function run(format: AuditFormat) {
    setBusy(format)
    try {
      saveBlob(`${fileStem}-audit.${format}`, await exportAuditFile(orgId, format))
      onDone?.(format)
    } catch (err) {
      onError(err)
    } finally {
      setBusy(null)
    }
  }
  return (
    <span className="row" style={{ gap: 6 }} role="group" aria-label="Export the audit log">
      {FORMATS.map((f) => (
        <button key={f.key} type="button" className="btn btn-secondary btn-sm" disabled={busy !== null} onClick={() => { run(f.key) }}
          aria-label={`Export audit log as ${f.label}`}>
          <Icon name="download" /> {busy === f.key ? 'Preparing…' : `Audit ${f.label}`}
        </button>
      ))}
    </span>
  )
}
