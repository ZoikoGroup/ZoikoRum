import { describe, expect, it } from 'vitest'
import { formatMoney } from './orgs'

describe('formatMoney', () => {
  it('turns minor units into a currency amount', () => {
    expect(formatMoney({ amountMinor: 1_000_000, currency: 'USD' })).toMatch(/10,000/)
  })

  it('never crashes on missing or malformed money', () => {
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
    expect(formatMoney({ amountMinor: 1234, currency: '' })).toMatch(/12\.34/)
  })
})
