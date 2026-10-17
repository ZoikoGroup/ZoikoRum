import { describe, expect, it } from 'vitest'
import type { Contract } from './contracts'
import type { Escrow } from './escrow'
import { disputableMilestones, paymentStuck, releaseAfterWindow } from './disputes'

const contract = { milestones: [
  { id: 'm1', status: 'ACCEPTED' }, { id: 'm2', status: 'ACCEPTED' }, { id: 'm3', status: 'IN_PROGRESS' }, { id: 'm4', status: 'PENDING_FUNDING' },
] } as unknown as Contract
const escrow = { allocations: [
  { milestoneId: 'm1', state: 'RELEASE_PENDING_APPROVAL' }, { milestoneId: 'm2', state: 'RELEASED' },
  { milestoneId: 'm3', state: 'HELD' }, { milestoneId: 'm4', state: 'UNFUNDED' },
] } as unknown as Escrow

describe('disputes', () => {
  it('treats accepted work whose payment is still held as stuck', () => {
    expect([...paymentStuck(contract, escrow)]).toEqual(['m1'])
    expect(paymentStuck(contract, null).size).toBe(0)
  })
  it('offers unaccepted funded work and stuck accepted work for a dispute', () => {
    expect(disputableMilestones(contract, escrow).map((m) => m.id)).toEqual(['m1', 'm3'])
    expect(disputableMilestones(contract).map((m) => m.id)).toEqual(['m3'])
  })
})

describe('challenge window', () => {
  const accepted = '2026-10-01T10:00:00Z'
  const withWindow = (days: number | null) => ({ terms: { policySettings: { challengeWindowDays: days } },
    milestones: [{ id: 'm1', status: 'ACCEPTED', acceptedAt: accepted }] }) as unknown as Contract
  it('gives the release date while the window is open', () => {
    expect(releaseAfterWindow(withWindow(7), 'm1', Date.parse('2026-10-05T00:00:00Z'))?.toISOString()).toBe('2026-10-08T10:00:00.000Z')
  })
  it('is null without a window or once it has ended', () => {
    expect(releaseAfterWindow(withWindow(null), 'm1', Date.parse('2026-10-05T00:00:00Z'))).toBeNull()
    expect(releaseAfterWindow(withWindow(7), 'm1', Date.parse('2026-10-09T00:00:00Z'))).toBeNull()
  })
})
