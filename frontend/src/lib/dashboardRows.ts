import type { Contract, MilestoneStatus } from '../api/contracts'
import type { Payout } from '../api/escrow'
import type { Money } from '../api/orgs'
import type { ProposalRequest } from '../api/proposals'
import { formatCurrencies } from './money'

/* What the dashboard tables show per row: request buckets and deadlines, an engagement's money, the earnings breakdown. */

export type ReqTab = 'all' | 'open' | 'proposals' | 'accepted' | 'expired' | 'declined'

/** Buyer Dashboard s.10: sent requests, received proposals and expired proposals, each in its own tab. */
export function buyerRequestBucket(r: ProposalRequest): Exclude<ReqTab, 'all'> {
  const s = r.proposal?.status
  if (s === 'ACCEPTED' || s === 'PENDING_APPROVAL') return 'accepted'
  if (s === 'EXPIRED') return 'expired'
  if (s && ['SUBMITTED', 'UNDER_REVIEW', 'REVISION_REQUESTED'].includes(s)) return 'proposals'
  if (['DRAFT', 'OPEN', 'PROPOSAL_RECEIVED'].includes(r.status)) return 'open'
  return 'declined'
}

/** A proposal the buyer can decide on from the dashboard. */
export const decidable = (r: ProposalRequest) => !!r.proposal && ['SUBMITTED', 'UNDER_REVIEW'].includes(r.proposal.status)

/** The date that matters next: how long a proposal stays valid for the buyer, or when the professional should answer. */
export function deadlineOf(r: ProposalRequest): string | null {
  if (decidable(r)) return r.proposal!.validUntil
  if (r.status === 'OPEN' && (!r.proposal || r.proposal.status === 'DRAFT')) return r.respondBy ?? null
  return null
}

/** "Today", "In 3 days", "2 days overdue"; soon (≤2 days) and overdue are flagged for emphasis. */
export function deadlineText(iso: string | null, now: number): { text: string; tone: '' | 'warn' | 'red' } {
  if (!iso) return { text: '—', tone: '' }
  const day = 86400_000
  const due = new Date(iso.length === 10 ? `${iso}T23:59:59` : iso).getTime()
  const days = Math.floor((due - now) / day)
  if (due < now) {
    const late = Math.max(1, Math.ceil((now - due) / day))
    return { text: `${late} day${late > 1 ? 's' : ''} overdue`, tone: 'red' }
  }
  if (days === 0) return { text: 'Today', tone: 'warn' }
  return { text: `In ${days} day${days > 1 ? 's' : ''}`, tone: days <= 2 ? 'warn' : '' }
}

const HELD: MilestoneStatus[] = ['IN_PROGRESS', 'SUBMITTED', 'REVISION_REQUESTED', 'ACCEPTANCE_PENDING_APPROVAL', 'DISPUTED']

/** Buyer Dashboard s.9: an engagement's money as held, scheduled (still to fund) and released, per currency. */
export function engagementMoney(c: Contract): { held: Money[]; scheduled: Money[]; released: Money[]; text: string } {
  // an accepted milestone counts what was actually released (a partial acceptance releases less than the full amount)
  const pick = (ok: (s: MilestoneStatus) => boolean) =>
    c.milestones.filter((m) => ok(m.status)).map((m) => (m.status === 'ACCEPTED' && m.acceptedRelease) || m.amount)
  const held = pick((s) => HELD.includes(s))
  const scheduled = c.status === 'ACTIVE' || c.status === 'PENDING_SIGNATURE' ? pick((s) => s === 'PENDING_FUNDING') : []
  const released = pick((s) => s === 'ACCEPTED')
  const parts = [held.length && `${formatCurrencies(held)} held`, scheduled.length && `${formatCurrencies(scheduled)} scheduled`,
    released.length && `${formatCurrencies(released)} released`].filter(Boolean)
  return { held, scheduled, released, text: parts.join(' · ') || '—' }
}

/** A dispute on any milestone makes the whole engagement show as disputed (rare, prominent). */
export const isDisputed = (c: Contract) => c.status === 'DISPUTED' || c.milestones.some((m) => m.status === 'DISPUTED')

export interface EarningsRow { key: string; contractId: string; engagement: string; milestone: string; amount: Money
  status: 'Held' | 'Under review' | 'On hold' | 'Paying out' | 'Released' | 'Delayed'; detail: string | null; eta: string | null }

/** Professional Dashboard s.12: money per milestone, from held in escrow to paid out, soonest first. */
export function earningsRows(contracts: Contract[], payouts: Payout[]): EarningsRow[] {
  const titles = new Map(contracts.flatMap((c) => c.milestones.map((m) => [m.id, { c, m }] as const)))
  const rows: EarningsRow[] = []
  for (const c of contracts) {
    for (const m of c.milestones) {
      const status = m.status === 'SUBMITTED' || m.status === 'ACCEPTANCE_PENDING_APPROVAL' ? 'Under review'
        : m.status === 'DISPUTED' ? 'On hold' : m.status === 'IN_PROGRESS' || m.status === 'REVISION_REQUESTED' ? 'Held' : null
      if (!status) continue
      rows.push({ key: `m:${m.id}`, contractId: c.id, engagement: c.title, milestone: `M${m.sequence} ${m.title}`, amount: m.amount, status,
        detail: status === 'On hold' ? 'Held until the dispute is resolved' : null,
        eta: status === 'Under review' ? m.acceptanceDueAt : m.dueDate })
    }
  }
  for (const p of payouts) {
    const ref = p.milestoneId ? titles.get(p.milestoneId) : undefined
    const delayed = p.status === 'FAILED' || (!!p.delayReason && p.status !== 'SETTLED')
    rows.push({ key: `p:${p.id}`, contractId: p.contractId, engagement: ref?.c.title ?? contracts.find((c) => c.id === p.contractId)?.title ?? 'Engagement',
      milestone: ref ? `M${ref.m.sequence} ${ref.m.title}` : '—', amount: p.net,
      status: delayed ? 'Delayed' : p.status === 'SETTLED' ? 'Released' : 'Paying out',
      detail: delayed ? p.failureMessage ?? p.delayReason : null, eta: p.status === 'SETTLED' ? p.settledAt : p.expectedAt })
  }
  // Problems first, then what is still moving (soonest first), then money already paid out (newest first).
  const rank = { Delayed: 0, 'On hold': 1, 'Under review': 2, 'Paying out': 3, Held: 4, Released: 5 } as const
  return rows.sort((a, b) => rank[a.status] - rank[b.status]
    || (a.status === 'Released' ? (b.eta ?? '').localeCompare(a.eta ?? '') : (a.eta ?? '9999').localeCompare(b.eta ?? '9999')))
}
