import { formatMoney, type Money } from '../api/orgs'

export function sumByCurrency(values: readonly Money[]): Money[] {
  const totals = new Map<string, number>()
  for (const value of values) totals.set(value.currency, (totals.get(value.currency) ?? 0) + value.amountMinor)
  return [...totals].sort(([a], [b]) => a.localeCompare(b)).map(([currency, amountMinor]) => ({ currency, amountMinor }))
}

export function formatCurrencies(values: readonly Money[]): string {
  return values.length ? sumByCurrency(values).map(value => `${value.currency} ${formatMoney(value)}`).join(' · ') : '—'
}
