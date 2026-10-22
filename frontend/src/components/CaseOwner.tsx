import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { assignmentKey, assignmentsApi, type AssignableStaff, type Assignment, type CaseKind } from '../api/assignments'
import { useAuth } from '../auth/AuthContext'
import { Initials, Pill, shortDateTime } from './admin'
import { ErrorAlert } from './ui'

/* Case owners on staff screens. `useAssignments` loads who owns which case for a page's table (Owner column);
   `CaseOwner` is the inline control in a detail panel: assign to me, reassign, release, escalate, de-escalate.
   Every change is audited by the server and the new owner is notified. */

export type AssignmentMap = Record<string, Assignment>

/** Owners and escalations for these kinds, keyed `${kind}:${caseId}`. `put` patches one entry after a change. */
export function useAssignments(kinds: CaseKind[]) {
  const key = kinds.join(',')
  const [map, setMap] = useState<AssignmentMap | null>(null)
  const [failed, setFailed] = useState(false)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    assignmentsApi.list({ kinds: key.split(',').filter(Boolean) as CaseKind[] })
      .then((rows) => { if (live) { setMap(Object.fromEntries(rows.map((a) => [assignmentKey(a.kind, a.caseId), a]))); setFailed(false) } })
      .catch(() => { if (live) { setMap({}); setFailed(true) } })
    return () => { live = false }
  }, [key, tick])
  const reload = useCallback(() => setTick((t) => t + 1), [])
  const put = useCallback((a: Assignment) => setMap((m) => ({ ...(m ?? {}), [assignmentKey(a.kind, a.caseId)]: a })), [])
  const get = useCallback((kind: CaseKind, id: string) => map?.[assignmentKey(kind, id)], [map])
  return { map, get, put, reload, failed }
}

/** Table cell: initials + name, or "Unassigned"; escalations are flagged. */
export function OwnerCell({ assignment, name }: { assignment?: Assignment | null; name?: string | null }) {
  const owner = name ?? assignment?.ownerName ?? null
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      {owner ? <><Initials name={owner} /><span className="small">{owner}</span></> : <span className="muted small">Unassigned</span>}
      {assignment?.escalated && <Pill tone="red">Escalated</Pill>}
    </span>
  )
}

type Mode = 'idle' | 'reassign' | 'escalate'

/** Inline owner control for a case's detail panel; render it with `key={caseId}` so a new case starts afresh.
    `nativeOwner` is used where the case has its own owner field (support requests) and no generic record exists yet. */
export function CaseOwner({ kind, caseId, assignment, onChange, note, nativeOwner }: {
  kind: CaseKind; caseId: string; assignment?: Assignment | null; onChange: (a: Assignment) => void; note?: ReactNode
  nativeOwner?: { id: string | null; name: string | null }
}) {
  const { user } = useAuth()
  const [mode, setMode] = useState<Mode>('idle')
  const [staff, setStaff] = useState<AssignableStaff[] | null>(null)
  const [pick, setPick] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const current = assignment && assignment.caseId === caseId ? assignment : null
  const ownerId = current ? current.ownerId : nativeOwner?.id ?? null
  const ownerName = current ? current.ownerName : nativeOwner?.name ?? null
  const mine = !!user && ownerId === user.id

  const act = async (fn: () => Promise<Assignment>) => {
    setBusy(true); setError(null)
    try { onChange(await fn()); setMode('idle'); setPick(''); setText('') } catch (e) { setError(e) } finally { setBusy(false) }
  }
  const openReassign = () => {
    setMode('reassign')
    if (!staff) assignmentsApi.assignable(kind).then(setStaff).catch((e) => { setStaff([]); setError(e) })
  }

  return (
    <section className="adm-facts" aria-label="Case owner">
      <h3>Case owner</h3>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        {ownerName ? <><Initials name={ownerName} /><strong className="small">{ownerName}{mine ? ' (you)' : ''}</strong></>
          : <span className="muted small">Unassigned</span>}
        {current?.escalated && <Pill tone="red">Escalated</Pill>}
      </div>
      {current?.escalated && <p className="small" style={{ margin: '0 0 8px' }}>
        <strong>Escalated:</strong> {current.escalationReason}{current.escalatedAt ? <span className="muted"> · {shortDateTime(current.escalatedAt)}</span> : null}</p>}
      {note && <p className="muted small" style={{ margin: '0 0 8px' }}>{note}</p>}
      <ErrorAlert error={error} />
      {mode === 'idle' && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {!mine && user && <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
          onClick={() => act(() => assignmentsApi.setOwner(kind, caseId, user.id))}>Assign to me</button>}
        <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={openReassign}>{ownerId ? 'Reassign' : 'Assign to…'}</button>
        {ownerId && <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
          onClick={() => act(() => assignmentsApi.setOwner(kind, caseId, null))}>Release</button>}
        {current?.escalated
          ? <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => act(() => assignmentsApi.deEscalate(kind, caseId))}>De-escalate</button>
          : <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setMode('escalate')}>Escalate</button>}
      </div>}
      {mode === 'reassign' && <div style={{ display: 'grid', gap: 6 }}>
        <select className="input" aria-label="New owner" value={pick} onChange={(e) => setPick(e.target.value)} disabled={!staff}>
          <option value="">{staff ? 'Choose a staff member' : 'Loading staff…'}</option>
          {(staff ?? []).filter((s) => s.id !== ownerId).map((s) => <option key={s.id} value={s.id}>{s.name}{s.you ? ' (you)' : ''}</option>)}
        </select>
        <input className="input" aria-label="Handover note" placeholder="Handover note (optional)" maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />
        <div style={{ display: 'flex', gap: 6 }}>
          <button type="button" className="btn btn-primary btn-sm" disabled={busy || !pick}
            onClick={() => act(() => assignmentsApi.setOwner(kind, caseId, pick, text.trim() || undefined))}>Assign</button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setMode('idle')}>Cancel</button>
        </div>
      </div>}
      {mode === 'escalate' && <div style={{ display: 'grid', gap: 6 }}>
        <textarea className="input" aria-label="Why it needs escalating" placeholder="Why it needs senior attention (at least 10 characters)" rows={3}
          maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} />
        <div style={{ display: 'flex', gap: 6 }}>
          <button type="button" className="btn btn-primary btn-sm" disabled={busy || text.trim().length < 10}
            onClick={() => act(() => assignmentsApi.escalate(kind, caseId, text.trim()))}>Escalate case</button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setMode('idle')}>Cancel</button>
        </div>
      </div>}
    </section>
  )
}
