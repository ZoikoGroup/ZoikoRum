import { useCallback, useEffect, useState } from 'react'
import type { AdminContract, AdminMilestone, Page } from '../../api/adminConsole'

/* Helpers shared by the engagement and financial staff screens. Everything here only reshapes live API data. */

/** Cursor-paged list: loads the first page whenever `load` changes, then appends pages on demand. */
export function useCursorList<T>(load: (cursor: string | null) => Promise<Page<T>>, onError: (e: unknown) => void) {
  const [rows, setRows] = useState<T[] | null>(null)
  const [next, setNext] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const reload = useCallback(() => load(null).then((p) => { setRows(p.items); setNext(p.nextCursor) }).catch(onError), [load, onError])
  useEffect(() => {
    let live = true  // ignore a slower response for filters that have since changed
    load(null).then((p) => { if (live) { setRows(p.items); setNext(p.nextCursor) } }).catch((e) => { if (live) onError(e) })
    return () => { live = false }
  }, [load, onError])
  const more = async () => {
    if (!next) return
    setBusy(true)
    try {
      const p = await load(next)
      setRows((r) => [...(r ?? []), ...p.items]); setNext(p.nextCursor)
    } catch (e) { onError(e) } finally { setBusy(false) }
  }
  return { rows, hasMore: !!next, more, busy, reload }
}

/** Debounced copy of a value (for server-side search). */
export function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export const CONTRACT_LABEL: Record<string, string> = {
  PENDING_SIGNATURE: 'Awaiting signatures', ACTIVE: 'Active', COMPLETED: 'Completed', TERMINATED: 'Terminated', DISPUTED: 'Disputed',
}
export const CONTRACT_ORDER = ['PENDING_SIGNATURE', 'ACTIVE', 'DISPUTED', 'COMPLETED', 'TERMINATED']
export const CONTRACT_COLOR: Record<string, string> = {
  PENDING_SIGNATURE: '#f79009', ACTIVE: '#12b76a', DISPUTED: '#f04438', COMPLETED: '#2f80ed', TERMINATED: '#667085',
}

export const MILESTONE_LABEL: Record<string, string> = {
  PENDING_FUNDING: 'Awaiting funding', IN_PROGRESS: 'In progress', SUBMITTED: 'Submitted', REVISION_REQUESTED: 'Revision requested',
  ACCEPTANCE_PENDING_APPROVAL: 'Acceptance awaiting approval', ACCEPTED: 'Accepted', DISPUTED: 'Disputed', CANCELLED: 'Cancelled',
}
export const MILESTONE_ORDER = ['PENDING_FUNDING', 'IN_PROGRESS', 'SUBMITTED', 'REVISION_REQUESTED', 'ACCEPTANCE_PENDING_APPROVAL', 'ACCEPTED', 'DISPUTED', 'CANCELLED']
export const MILESTONE_COLOR: Record<string, string> = {
  PENDING_FUNDING: '#98a2b3', IN_PROGRESS: '#2f80ed', SUBMITTED: '#f79009', REVISION_REQUESTED: '#9b8afb',
  ACCEPTANCE_PENDING_APPROVAL: '#0e9384', ACCEPTED: '#12b76a', DISPUTED: '#f04438', CANCELLED: '#667085',
}

const DONE = new Set(['ACCEPTED', 'CANCELLED'])

/** Known keys first in their usual order, then any status the API adds later. */
export function orderedEntries(rec: Record<string, number> | undefined, order: string[]): [string, number][] {
  const r = rec ?? {}
  return [...order.filter((k) => k in r), ...Object.keys(r).filter((k) => !order.includes(k)).sort()].map((k) => [k, r[k]])
}

export const msLabel = (m: AdminMilestone) => `M-${String(m.sequence).padStart(2, '0')}`
export const sortedMilestones = (c: AdminContract) => [...c.milestones].sort((a, b) => a.sequence - b.sequence)

/** The first milestone that is neither accepted nor cancelled. */
export const currentMilestone = (c: AdminContract) => sortedMilestones(c).find((m) => !DONE.has(m.status)) ?? null

/** What has to happen next, read from the contract and milestone states. */
export function nextAction(c: AdminContract): { text: string; due: string | null } {
  if (c.status === 'PENDING_SIGNATURE') return { text: 'Signatures pending', due: null }
  if (c.status === 'TERMINATED') return { text: 'Terminated', due: null }
  const m = currentMilestone(c)
  if (c.hasOpenDispute) return { text: 'Dispute open', due: m?.dueDate ?? null }
  if (!m) return { text: c.milestones.length ? 'All milestones closed' : 'No milestones defined', due: null }
  const id = msLabel(m)
  const text: Record<string, string> = {
    PENDING_FUNDING: `Buyer to fund ${id}`, IN_PROGRESS: `${id} in delivery`, SUBMITTED: `Buyer review of ${id}`,
    REVISION_REQUESTED: `Revision of ${id}`, ACCEPTANCE_PENDING_APPROVAL: `Approval of ${id} acceptance`, DISPUTED: `${id} disputed`,
  }
  return { text: text[m.status] ?? `${id} · ${MILESTONE_LABEL[m.status] ?? m.status}`, due: m.dueDate }
}

/** Funding position of one contract (single currency, so totals are safe to compare). */
export function fundingState(c: AdminContract): { text: string; tone: 'green' | 'amber' | 'grey' | 'red' } {
  if (c.totalMinor <= 0) return { text: 'Nothing to fund', tone: 'grey' }
  if (c.releasedMinor >= c.totalMinor) return { text: 'Fully released', tone: 'green' }
  if (c.fundedMinor >= c.totalMinor) return { text: 'Fully funded', tone: 'green' }
  if (c.fundedMinor > 0) return { text: 'Partly funded', tone: 'amber' }
  return { text: 'Not funded', tone: c.status === 'ACTIVE' ? 'red' : 'grey' }
}

export const route = (c: AdminContract) => `${c.buyer.country ?? '—'} → ${c.professional.country ?? '—'}`
