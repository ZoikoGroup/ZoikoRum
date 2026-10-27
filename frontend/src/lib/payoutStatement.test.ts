import { describe, expect, it } from 'vitest'
import { amountsReconcile, feePercent, formatStatementMoney, humanize, transactionLink, workPeriod } from './payoutStatement'

describe('payout statement helpers', () => {
  it('shows exact amounts in the payout currency', () => {
    const text = formatStatementMoney({ currency: 'USD', amountMinor: 123456 })
    expect(text).toContain('1,234.56')
    expect(formatStatementMoney(null)).toBe('—')
  })
  it('turns basis points into a percentage', () => {
    expect(feePercent(1000)).toBe('10%')
    expect(feePercent(1250)).toBe('12.5%')
    expect(feePercent(0)).toBe('0%')
  })
  it('humanizes codes', () => {
    expect(humanize('FIXED_PRICE')).toBe('Fixed price')
    expect(humanize(null)).toBe('—')
  })
  it('links only transactions that have a page', () => {
    expect(transactionLink('ESCROW_RELEASE', 'c1')).toBe('/app/professional/engagements/c1')
    expect(transactionLink('MILESTONE_INVOICE', 'c1')).toBeNull()
    expect(transactionLink('PAYOUT', 'c1')).toBeNull()
  })
  it('checks gross - fee = net in one currency', () => {
    const m = (amountMinor: number, currency = 'USD') => ({ amountMinor, currency })
    expect(amountsReconcile({ gross: m(1000), fee: m(100), net: m(900) })).toBe(true)
    expect(amountsReconcile({ gross: m(1000), fee: m(100), net: m(901) })).toBe(false)
    expect(amountsReconcile({ gross: m(1000), fee: m(100, 'EUR'), net: m(900) })).toBe(false)
  })
  it('describes the work period', () => {
    expect(workPeriod(null, null)).toBe('—')
    expect(workPeriod('2026-01-05', null)).toMatch(/ongoing$/)
  })
})
