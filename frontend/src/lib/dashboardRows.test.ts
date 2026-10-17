import { describe, expect, it } from 'vitest'
import type { Contract, ContractMilestone } from '../api/contracts'
import type { Payout } from '../api/escrow'
import type { ProposalRequest } from '../api/proposals'
import { buyerRequestBucket, deadlineOf, deadlineText, earningsRows, engagementMoney, isDisputed } from './dashboardRows'

const usd = (amountMinor: number) => ({ currency: 'USD', amountMinor })
const request = (status: ProposalRequest['status'], proposal: Partial<NonNullable<ProposalRequest['proposal']>> | null, respondBy: string | null = null) =>
  ({ status, respondBy, proposal: proposal && { id: 'p', total: usd(100), submittedAt: null, validUntil: null, status: 'SUBMITTED', ...proposal } }) as ProposalRequest
const milestone = (id: string, sequence: number, status: ContractMilestone['status'], extra: Partial<ContractMilestone> = {}) =>
  ({ id, sequence, title: `Step ${sequence}`, status, amount: usd(1000), dueDate: null, acceptanceDueAt: null, acceptedRelease: null, ...extra }) as ContractMilestone
const contract = (status: Contract['status'], milestones: ContractMilestone[]) => ({ id: 'k', title: 'Audit', status, milestones }) as Contract

describe('dashboard rows', () => {
  it('puts expired proposals in their own tab and chosen ones with accepted', () => {
    expect(buyerRequestBucket(request('CLOSED', { status: 'EXPIRED' }))).toBe('expired')
    expect(buyerRequestBucket(request('PROPOSAL_RECEIVED', { status: 'PENDING_APPROVAL' }))).toBe('accepted')
    expect(buyerRequestBucket(request('PROPOSAL_RECEIVED', { status: 'SUBMITTED' }))).toBe('proposals')
    expect(buyerRequestBucket(request('OPEN', null))).toBe('open')
    expect(buyerRequestBucket(request('DECLINED', null))).toBe('declined')
  })

  it('shows the validity of a proposal to decide on, or the answer-by date of an open request', () => {
    expect(deadlineOf(request('PROPOSAL_RECEIVED', { status: 'SUBMITTED', validUntil: '2026-11-01' }))).toBe('2026-11-01')
    expect(deadlineOf(request('OPEN', null, '2026-10-20T12:00:00Z'))).toBe('2026-10-20T12:00:00Z')
    expect(deadlineOf(request('PROPOSAL_RECEIVED', { status: 'ACCEPTED', validUntil: '2026-11-01' }))).toBeNull()
  })

  it('words deadlines and flags the close and the late ones', () => {
    const now = new Date('2026-10-17T12:00:00Z').getTime()
    expect(deadlineText(null, now)).toEqual({ text: '—', tone: '' })
    expect(deadlineText('2026-10-16T12:00:00Z', now)).toEqual({ text: '1 day overdue', tone: 'red' })
    expect(deadlineText('2026-10-18T13:00:00Z', now)).toEqual({ text: 'In 1 day', tone: 'warn' })
    expect(deadlineText('2026-10-27T13:00:00Z', now).tone).toBe('')
  })

  it('splits an engagement\'s money into held, scheduled and released, and spots a dispute', () => {
    const c = contract('ACTIVE', [milestone('a', 1, 'ACCEPTED', { acceptedRelease: usd(600) }), milestone('b', 2, 'IN_PROGRESS'),
      milestone('c', 3, 'PENDING_FUNDING')])
    const money = engagementMoney(c)
    expect([money.held, money.scheduled, money.released]).toEqual([[usd(1000)], [usd(1000)], [usd(600)]])
    expect(money.text).toContain('held')
    expect(isDisputed(c)).toBe(false)
    expect(isDisputed(contract('ACTIVE', [milestone('d', 1, 'DISPUTED')]))).toBe(true)
  })

  it('lists earnings with problems first and names the milestone behind each payout', () => {
    const c = contract('ACTIVE', [milestone('a', 1, 'ACCEPTED'), milestone('b', 2, 'SUBMITTED'), milestone('c', 3, 'PENDING_FUNDING')])
    const payouts = [
      { id: 'p1', contractId: 'k', milestoneId: 'a', net: usd(900), status: 'SETTLED', settledAt: '2026-10-01', expectedAt: null, delayReason: null, failureMessage: null },
      { id: 'p2', contractId: 'k', milestoneId: 'a', net: usd(50), status: 'QUEUED', settledAt: null, expectedAt: '2026-10-20', delayReason: 'Bank holiday', failureMessage: null },
    ] as Payout[]
    const rows = earningsRows([c], payouts)
    expect(rows.map((r) => r.status)).toEqual(['Delayed', 'Under review', 'Released'])
    expect(rows[0]).toMatchObject({ milestone: 'M1 Step 1', detail: 'Bank holiday' })
  })
})
