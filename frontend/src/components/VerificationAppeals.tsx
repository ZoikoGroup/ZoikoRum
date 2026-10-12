import { useCallback, useEffect, useState } from 'react'
import { verificationApi, type AppealQueueItem, type VerificationCase } from '../api/verification'
import { FileLink } from './FileLink'
import { evidenceFileUrl } from '../api/verification'
import { ErrorAlert, useStepUp } from './ui'
export function VerificationAppeals() {
  const [items, setItems] = useState<AppealQueueItem[]>([])
  const [error, setError] = useState<unknown>(null)
  const [selected, setSelected] = useState<AppealQueueItem | null>(null)
  const [c, setC] = useState<VerificationCase | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => verificationApi.appeals().then(setItems).catch(setError), [])
  useEffect(() => { load() }, [load])
  function decide(outcome: 'UPHELD' | 'OVERTURNED') {
    if (!selected || busy) return
    run(async () => {
      setBusy(true)
      try { await verificationApi.decideAppeal(selected.id, { outcome, note: note.trim() }); setSelected(null); setC(null); setNote(''); await load() }
      finally { setBusy(false) }
    })
  }
  return <section className="card panel"><h2>Verification appeals</h2>{modal}<ErrorAlert error={error} />
    {items.length === 0 && <p>No open appeals.</p>}
    {items.map(a => <article className="case" key={a.id}><h3>{a.caseLabel} · {a.subjectName ?? 'Subject'}</h3>
      <p>Original decision: {a.originalReason ?? 'No public reason'}</p><p>{a.statement}</p>
      <button className="btn btn-secondary" onClick={async () => { setError(null); setNote(''); setC(null); setSelected(a); try { setC(await verificationApi.get(a.caseId)) } catch (err) { setError(err) } }}>Review evidence</button>
    </article>)}
    {selected && c && <div className="case"><h3>{selected.caseLabel}</h3>
      {c.evidence.map(e => <FileLink key={e.id} file={{ name: e.fileName, hasFile: e.hasFile }} url={evidenceFileUrl(e.id)} />)}
      {!selected.canDecide ? <p>An independent reviewer must decide this appeal.</p> : <>
        <label className="filter-box">Decision explanation, shared with the owner
          <textarea minLength={10} maxLength={1000} value={note} onChange={e => setNote(e.target.value)} /></label>
        <button className="btn btn-secondary" disabled={busy || note.trim().length < 10} onClick={() => decide('UPHELD')}>Uphold decision</button>
        <button className="btn btn-primary" disabled={busy || note.trim().length < 10} onClick={() => decide('OVERTURNED')}>Overturn decision</button>
      </>}
    </div>}
  </section>
}
