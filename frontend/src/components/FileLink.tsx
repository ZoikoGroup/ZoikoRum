import { useState } from 'react'
import { openStoredFile, type StoredFile } from '../api/files'

/** A stored document's name; clicking opens it (audited). Older records only have a fingerprint. */
export function FileLink({ file, url }: { file: Pick<StoredFile, 'name' | 'hasFile'>; url: string }) {
  const [error, setError] = useState('')
  if (!file.hasFile) return <span title="Recorded before uploads were stored: fingerprint only">{file.name} <span className="muted small">(fingerprint only)</span></span>
  return (
    <>
      <button type="button" className="file-link" onClick={() => openStoredFile(url).catch((err) => setError(err instanceof Error ? err.message : 'Could not open the file'))}>
        {file.name}</button>
      {error && <span className="small" style={{ color: 'var(--zk-danger)' }}> {error}</span>}
    </>
  )
}

/** Comma-free list of file links. */
export function FileLinks({ files, url }: { files: StoredFile[]; url: (f: StoredFile) => string }) {
  return <span className="small file-links">{files.map((f) => <FileLink key={f.sha256} file={f} url={url(f)} />)}</span>
}
