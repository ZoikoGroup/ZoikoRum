import { describe, expect, it } from 'vitest'
import type { Dispute } from '../api/disputes'
import type { Charge, Payout, Refund } from '../api/escrow'
import type { ProposalRequest } from '../api/proposals'
import { buyerPaymentActions, buyerRequestActions, disputeActions, payoutActions, professionalRequestActions, urgentCount } from './dashboardActions'

const usd = (amountMinor: number) => ({ currency: 'USD', amountMinor })
const dispute = (id: string, status: Dispute['status']) =>
  ({ id, reference: `D-${id}`, status, nextStep: 'Add your evidence', disputed: usd(5000) }) as Dispute
const charge = (id: string, contractId: string, status: Charge['status'], createdAt: string) =>
  ({ id, contractId, status, createdAt, amount: usd(1000), failureMessage: null, methodLabel: 'Visa', capturedAt: null, chargedBackAt: null }) as Charge

describe('dashboard pending actions', () => {
  it('lists only open disputes, each linking to its case', () => {
    const items = disputeActions([dispute('a', 'MEDIATION'), dispute('b', 'CLOSED'), dispute('c', 'EVIDENCE_COLLECTION')])
    expect(items.map((i) => i.to)).toEqual(['/app/disputes/a', '/app/disputes/c'])
    expect(items.every((i) => i.priority === 'High')).toBe(true)
    expect(items[0].title).toContain('in mediation')
  })

  it('flags a failed payment only while it is the latest charge for the engagement', () => {
    const retried = [charge('1', 'k1', 'FAILED', '2026-10-01T00:00:00Z'), charge('2', 'k1', 'CAPTURED', '2026-10-02T00:00:00Z')]
    expect(buyerPaymentActions(retried, [])).toEqual([])
    const failed = [charge('3', 'k2', 'CAPTURED', '2026-10-01T00:00:00Z'), charge('4', 'k2', 'FAILED', '2026-10-02T00:00:00Z')]
    expect(buyerPaymentActions(failed, []).map((a) => a.to)).toEqual(['/app/engagements/k2'])
    expect(buyerPaymentActions([charge('5', 'k3', 'CHARGED_BACK', '2026-10-01T00:00:00Z')], [])[0].title).toContain('charged back')
  })

  it('reports failed refunds and payouts, and delayed payouts with their reason', () => {
    const refunds = [{ id: 'r', status: 'FAILED', amount: usd(300), failureMessage: null } as Refund]
    expect(buyerPaymentActions([], refunds)[0].priority).toBe('Medium')
    const payouts = [
      { id: 'p1', status: 'FAILED', net: usd(900), failureMessage: 'Account closed', delayReason: null },
      { id: 'p2', status: 'QUEUED', net: usd(900), failureMessage: null, delayReason: 'Bank holiday' },
      { id: 'p3', status: 'SETTLED', net: usd(900), failureMessage: null, delayReason: 'Bank holiday' },
    ] as Payout[]
    expect(payoutActions(payouts).map((a) => a.detail)).toEqual(['Account closed · check your payout account', 'Bank holiday'])
  })

  it('flags jurisdiction conflicts and the other side going quiet', () => {
    const now = new Date('2026-10-17T12:00:00Z').getTime()
    const base = { id: 'q', service: 'Tax review', organizationName: 'Acme', professional: { displayName: 'Ana' }, jurisdictionConflict: false, proposal: null }
    const conflict = { ...base, status: 'OPEN', jurisdictionConflict: true } as unknown as ProposalRequest
    const late = { ...base, id: 'l', status: 'OPEN', respondBy: '2026-10-15T00:00:00Z' } as unknown as ProposalRequest
    const onTime = { ...base, id: 't', status: 'OPEN', respondBy: '2026-10-20T00:00:00Z' } as unknown as ProposalRequest
    expect(buyerRequestActions([conflict, late, onTime], now).map((a) => [a.priority, a.to])).toEqual([
      ['High', '/app/requests/q'], ['Medium', '/app/requests/l']])
    const quiet = { ...base, id: 's', status: 'PROPOSAL_RECEIVED', proposal: { status: 'SUBMITTED', submittedAt: '2026-10-01T00:00:00Z' } } as unknown as ProposalRequest
    const recent = { ...base, id: 'r', status: 'PROPOSAL_RECEIVED', proposal: { status: 'SUBMITTED', submittedAt: '2026-10-15T00:00:00Z' } } as unknown as ProposalRequest
    expect(professionalRequestActions([conflict, quiet, recent], now).map((a) => a.priority)).toEqual(['High', 'Low'])
  })

  it('counts urgent items, not recommendations', () => {
    const items = [...disputeActions([dispute('a', 'MEDIATION')]),
      { title: 'Add a photo', detail: '', priority: 'Low' as const, to: '/', icon: 'user' as const }]
    expect(urgentCount(items)).toBe(1)
  })
})
