import type { Money } from '../api/orgs'
import type { PayoutStatement } from '../api/escrow'

/* Pure helpers for the professional's payout statement page (pages/PayoutStatement.tsx). */

/** Exact amount in the payout's own currency (a statement shows cents, unlike the rounded dashboard figures). */
export function formatStatementMoney(m: Money | null | undefined): string {
  if (!m) return '—'
  if (!/^[A-Z]{3}$/.test(m.currency ?? '')) return (m.amountMinor / 100).toFixed(2)
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: m.currency }).format(m.amountMinor / 100)
}

/** Basis points as a percentage label: 1000 -> "10%", 1250 -> "12.5%". */
export function feePercent(bps: number): string {
  return `${Number((bps / 100).toFixed(2))}%`
}

/** "PROJECT" / "FIXED_PRICE" -> "Project" / "Fixed price". */
export function humanize(code: string | null | undefined): string {
  if (!code) return '—'
  const s = code.replace(/_/g, ' ').toLowerCase()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export function formatDay(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00` : iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function workPeriod(start: string | null, end: string | null): string {
  if (!start && !end) return '—'
  return `${formatDay(start)} – ${end ? formatDay(end) : 'ongoing'}`
}

export const STATUS_TONE: Record<PayoutStatement['statusLabel'], string> = {
  Processing: 'warn', 'In transit': 'amber', Paid: 'green', Failed: 'red',
}

export const TRANSACTION_TYPE: Record<PayoutStatement['transactions'][number]['kind'], string> = {
  ESCROW_FUNDED: 'Escrow funded', MILESTONE_INVOICE: 'Milestone invoice', ESCROW_RELEASE: 'Escrow release', PAYOUT: 'Payout',
}

/** Where a related transaction can be opened from the professional's side, or null when there is no page for it
    (the invoice belongs to the buyer; the payout is this page). */
export function transactionLink(kind: PayoutStatement['transactions'][number]['kind'], contractId: string): string | null {
  return kind === 'ESCROW_FUNDED' || kind === 'ESCROW_RELEASE' ? `/app/professional/engagements/${contractId}` : null
}

/** The amounts on a statement must reconcile: gross - fee = net, all in one currency. */
export function amountsReconcile(s: Pick<PayoutStatement, 'gross' | 'fee' | 'net'>): boolean {
  return s.gross.currency === s.fee.currency && s.fee.currency === s.net.currency
    && s.gross.amountMinor - s.fee.amountMinor === s.net.amountMinor
}
