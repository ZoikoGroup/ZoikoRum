import { useState } from 'react'
import { saveBlob } from '../lib/exports'
import { Icon } from './dashboard'

export type PackFormat = 'pdf' | 'csv' | 'json'
const FORMATS: { key: PackFormat; label: string }[] = [{ key: 'pdf', label: 'PDF' }, { key: 'csv', label: 'CSV' }, { key: 'json', label: 'JSON' }]

/** Export Pack: one button with a format choice. The server checks the same permission for every format and prints the
    SHA-256 of the exported record in the file; each download is recorded in the audit trail. */
export function ExportPack({ label = 'Export Pack', fileStem, fetchPack, onError, formats }: {
  label?: string; fileStem: string; fetchPack: (format: PackFormat) => Promise<Blob>; onError: (err: unknown) => void
  formats?: PackFormat[]  // the formats the server offers for this record (all three when omitted)
}) {
  const [format, setFormat] = useState<PackFormat>('pdf')
  const [busy, setBusy] = useState(false)
  async function run() {
    setBusy(true)
    try { saveBlob(`${fileStem}.${format}`, await fetchPack(format)) } catch (err) { onError(err) } finally { setBusy(false) }
  }
  return (
    <span className="row" style={{ gap: 6, flexWrap: 'nowrap' }} role="group" aria-label={label}>
      <select className="input" style={{ width: 'auto' }} value={format} aria-label={`${label} format`} disabled={busy}
        onChange={(e) => setFormat(e.target.value as PackFormat)}>
        {FORMATS.filter((f) => !formats || formats.includes(f.key)).map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
      </select>
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => { run() }}>
        <Icon name="download" /> {busy ? 'Preparing…' : label}
      </button>
    </span>
  )
}
