import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('react-router-dom', () => ({ Link: ({ children }: { children: unknown }) => children, useNavigate: () => () => {} }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: null }) }))
import { EnterpriseDashboard, sumMoney } from './EnterprisePages'

describe('enterprise dashboard', () => {
  it('adds spend exposure per currency and never across currencies', () => {
    expect(sumMoney([[{ currency: 'USD', amountMinor: 100 }], [{ currency: 'EUR', amountMinor: 50 }, { currency: 'USD', amountMinor: 25 }]]))
      .toEqual([{ currency: 'EUR', amountMinor: 50 }, { currency: 'USD', amountMinor: 125 }])
    expect(sumMoney([])).toEqual([])
  })

  it('renders nothing for a signed-out visitor', () => {
    expect(renderToStaticMarkup(<EnterpriseDashboard />)).toBe('')
  })
})
