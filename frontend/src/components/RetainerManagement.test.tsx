import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { RetainerManagement } from './RetainerManagement'
import type { Contract } from '../api/contracts'

const contract = {
  id: 'retainer', pricingModel: 'RETAINER', engagementType: 'RETAINER', status: 'ACTIVE', viewerRole: 'BUYER',
  milestones: [
    { id: 'funded', sequence: 1, title: 'Funded cycle', dueDate: '2026-10-10', amount: { amountMinor: 10000, currency: 'USD' }, status: 'IN_PROGRESS' },
    { id: 'future', sequence: 2, title: 'Future cycle', dueDate: '2026-11-10', amount: { amountMinor: 10000, currency: 'USD' }, status: 'PENDING_FUNDING' },
  ],
} as Contract

describe('retainer financial controls', () => {
  it('shows funded and future cycles but offers cancellation only for the one unfunded cycle', () => {
    const html = renderToStaticMarkup(<RetainerManagement contract={contract} onChange={() => {}} />)
    expect(html).toContain('Funded cycle')
    expect(html).toContain('Future cycle')
    expect(html).toContain('the 1 unfunded cycles')
    expect(html).toContain('accepted manually')
    expect(html).not.toContain('Pause Cycle')
  })
  it('does not offer buyer cancellation to the professional or on an inactive agreement', () => {
    for (const patch of [{ viewerRole: 'PROFESSIONAL' }, { status: 'COMPLETED' }]) {
      const html = renderToStaticMarkup(<RetainerManagement contract={{ ...contract, ...patch } as Contract} onChange={() => {}} />)
      expect(html).not.toContain('Cancel unfunded cycles')
    }
  })
  it('does not render controls for a fixed fee engagement', () => {
    expect(renderToStaticMarkup(<RetainerManagement contract={{ ...contract, engagementType: 'PROJECT', pricingModel: 'FIXED' }} onChange={() => {}} />)).toBe('')
  })
})
