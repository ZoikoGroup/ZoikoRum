import { useEffect, useState } from 'react'
import type { User } from '../api/auth'
import { contractApi } from '../api/contracts'
import { disputeApi, OPEN_PHASES } from '../api/disputes'
import { duplicatesApi } from '../api/duplicates'
import { paymentsApi } from '../api/escrow'
import { firmApi, orgApi } from '../api/orgs'
import { taxonomyApi } from '../api/professional'
import { proposalApi } from '../api/proposals'
import { verificationApi } from '../api/verification'

/* "Waiting for you" counts per sidebar tab, and the bell's total (until full notifications arrive with Step 10).
   Each count is work that needs THIS person's action, not just activity. Failures count as 0 - never block the shell. */

export interface ActionItem { to: string; label: string; count: number }

const safe = async (fn: () => Promise<number>) => { try { return await fn() } catch { return 0 } }
const has = (user: User, ...roles: string[]) => user.platformRoles.some((r) => roles.includes(r))

async function collect(user: User): Promise<ActionItem[]> {
  const items: Promise<ActionItem>[] = []
  const add = (to: string, label: string, fn: () => Promise<number>) => items.push(safe(fn).then((count) => ({ to, label, count })))

  add('/app/invitations', 'Invitations to accept', async () => {
    const [o, f] = await Promise.all([orgApi.myInvitations(), firmApi.myInvitations()])
    return o.length + f.length
  })

  // Staff queues
  if (has(user, 'COMPLIANCE_OFFICER')) add('/app/ops/verification', 'Verification checks to review', async () => {
    const [q, appeals] = await Promise.all([verificationApi.queue(), verificationApi.appeals()])
    return q.items.length + appeals.filter((a) => a.canDecide).length
  })
  if (has(user, 'TS_ANALYST', 'PLATFORM_ADMIN')) add('/app/ops/duplicates', 'Possible duplicate accounts', async () => (await duplicatesApi.queue()).length)
  if (has(user, 'PLATFORM_ADMIN')) add('/app/ops/taxonomy', 'Specialization suggestions', async () => (await taxonomyApi.queue()).length)
  if (has(user, 'FINANCIAL_OPS', 'PLATFORM_ADMIN')) add('/app/ops/reconciliation', 'Reconciliation mismatches', async () =>
    (await paymentsApi.reconciliations()).filter((r) => r.status === 'MISMATCH').length)
  if (has(user, 'MEDIATOR', 'LEGAL', 'PLATFORM_ADMIN')) add('/app/ops/disputes', 'Disputes in mediation', async () =>
    (await disputeApi.list('operator')).filter((d) => d.status === 'MEDIATION').length)

  // Professional
  if (user.personas.includes('PROFESSIONAL')) {
    add('/app/professional/requests', 'New requests to answer', async () => (await proposalApi.summary('professional')).requests.OPEN ?? 0)
    const engagements = contractApi.list('professional')
    add('/app/professional/engagements', 'Engagements needing you', async () => (await engagements).filter((c) => c.canSign
      || c.milestones.some((m) => m.status === 'REVISION_REQUESTED' || (m.status === 'SUBMITTED' && m.partialOffer))).length)
    // Payouts only exist after engagements: no call (and no "no profile yet" error) before the first one.
    add('/app/professional/earnings', 'Payouts needing attention', async () => (await engagements).length === 0 ? 0 :
      (await paymentsApi.earnings()).payouts.filter((p) => p.status === 'QUEUED' || p.status === 'FAILED').length)
    add('/app/professional/disputes', 'Open disputes', async () =>
      (await disputeApi.list('professional')).filter((d) => OPEN_PHASES.includes(d.status)).length)
  }

  // Customer (buyer / enterprise)
  if (user.personas.some((p) => p === 'BUYER' || p === 'ENTERPRISE_ADMIN' || p === 'ENTERPRISE_MEMBER')) {
    add('/app/proposals', 'Proposals to review', async () => (await proposalApi.summary('buyer')).proposals.SUBMITTED ?? 0)
    add('/app/engagements', 'Engagements needing you', async () => (await contractApi.list('buyer')).filter((c) => c.canSign
      || c.milestones.some((m) => m.status === 'SUBMITTED')).length)
    add('/app/disputes', 'Open disputes', async () => (await disputeApi.list('buyer')).filter((d) => OPEN_PHASES.includes(d.status)).length)
  }
  return Promise.all(items)
}

/** Reloads on every page change and every minute. */
export function useActionCounts(user: User | null, pathname: string): { byPath: Record<string, number>; items: ActionItem[]; total: number } {
  const [items, setItems] = useState<ActionItem[]>([])
  useEffect(() => {
    if (!user) return
    let live = true
    const load = () => collect(user).then((x) => { if (live) setItems(x) })
    load()
    let timer: number | undefined
    const changed = () => { window.clearTimeout(timer); timer = window.setTimeout(load, 750) }
    const t = window.setInterval(load, 60_000)
    window.addEventListener('zk:activity', changed)
    return () => { live = false; window.clearInterval(t); window.clearTimeout(timer); window.removeEventListener('zk:activity', changed) }
  }, [user, pathname])
  const shown = items.filter((i) => i.count > 0)
  return { byPath: Object.fromEntries(items.map((i) => [i.to, i.count])), items: shown, total: shown.reduce((s, i) => s + i.count, 0) }
}
