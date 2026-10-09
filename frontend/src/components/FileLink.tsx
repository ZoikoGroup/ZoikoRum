import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { StoredFile } from '../api/files'

/** A stored document's name; clicking opens it in a viewer inside the dashboard (every opening is audited).
 *  Older records only have a fingerprint. */
export function FileLink({ file, url }: { file: Pick<StoredFile, 'name' | 'hasFile'>; url: string }) {
  const [open, setOpen] = useState(false)
  if (!file.hasFile) return <span title="Recorded before uploads were stored: fingerprint only">{file.name} <span className="muted small">(fingerprint only)</span></span>
  return (
    <>
      <button type="button" className="file-link" onClick={() => setOpen(true)}>{file.name}</button>
      {open && <DocumentViewer name={file.name} url={url} onClose={() => setOpen(false)} />}
    </>
  )
}

/** Comma-free list of file links. */
export function FileLinks({ files, url }: { files: StoredFile[]; url: (f: StoredFile) => string }) {
  return <span className="small file-links">{files.map((f) => <FileLink key={f.sha256} file={f} url={url(f)} />)}</span>
}

/** In-dashboard document viewer: PDFs and images display inline; other types (Word, Excel, CSV) offer a download. */
export function DocumentViewer({ name, url, onClose }: { name: string; url: string; onClose: () => void }) {
  const [doc, setDoc] = useState<{ href: string; type: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose }, [onClose])
  useEffect(() => {  // loads once per document (each load is an audited opening)
    let href: string | null = null
    let live = true
    api<Blob>(url, { blob: true })
      .then((blob) => { href = URL.createObjectURL(blob); if (live) setDoc({ href, type: blob.type }) })
      .catch((err) => { if (live) setError(err instanceof Error ? err.message : 'The document could not be opened') })
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') close.current() }
    window.addEventListener('keydown', esc)
    return () => { live = false; window.removeEventListener('keydown', esc); if (href) URL.revokeObjectURL(href) }
  }, [url])

  const pdf = doc?.type === 'application/pdf'
  const image = doc?.type.startsWith('image/')
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={name} onClick={onClose}>
      <div className="card modal doc-viewer" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <h2 style={{ margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</h2>
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            {doc && <a className="btn btn-ghost btn-sm" href={doc.href} download={name}>Download</a>}
            {doc && <a className="btn btn-ghost btn-sm" href={doc.href} target="_blank" rel="noopener noreferrer">Open in new tab</a>}
            <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>×</button>
          </div>
        </div>
        <div className="doc-frame">
          {error ? <p className="small" style={{ color: 'var(--zk-danger)' }}>{error}</p>
            : !doc ? <p className="muted">Loading…</p>
              : pdf ? <iframe title={name} src={doc.href} />
                : image ? <img src={doc.href} alt={name} />
                  : <p className="muted">This file type can't be previewed here. Use <strong>Download</strong> to open it.</p>}
        </div>
        <p className="muted small" style={{ margin: '8px 0 0' }}>Opening this document is recorded in the audit log.</p>
      </div>
    </div>
  )
}
