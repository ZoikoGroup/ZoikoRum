import type { Invoice } from '../api/escrow'

/* Record exports (Payments & Escrow s.13/s.21, Request flow s.18): receipts to print or save as PDF, CSV and JSON packs.
   Everything is built in the browser from data the viewer can already see. */

export function downloadFile(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  Object.assign(document.createElement('a'), { href: url, download: name }).click()
  URL.revokeObjectURL(url)
}

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!)

export function csv(rows: (string | number | null | undefined)[][]): string {
  return rows.map((r) => r.map((v) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }).join(',')).join('\n')
}

const money = (minor: number, ccy: string) => new Intl.NumberFormat(undefined, { style: 'currency', currency: ccy }).format(minor / 100)

/** Opens a clean receipt in a new tab and the print dialog; "Save as PDF" gives the downloadable PDF receipt. */
export function printReceipt(inv: Invoice, engagement: string, buyer: string) {
  const w = window.open('', '_blank', 'noopener=no,width=760,height=900')
  if (!w) return
  const lines = inv.lines.map((l) => `<tr><td>${esc(l.description)}</td><td class="r">${money(l.amountMinor, inv.total.currency)}</td></tr>`).join('')
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(inv.number)}</title>
<style>body{font-family:Inter,Arial,sans-serif;color:#1e293b;margin:40px;max-width:640px}h1{font-size:22px;margin:0 0 4px}
table{width:100%;border-collapse:collapse;margin:20px 0}td,th{padding:10px 8px;border-bottom:1px solid #e3e4e8;text-align:left}
.r{text-align:right}.muted{color:#475569;font-size:13px}.total td{font-weight:700;border-top:2px solid #1e293b}</style></head><body>
<h1>Receipt ${esc(inv.number)}</h1><div class="muted">Issued ${new Date(inv.issuedAt).toLocaleString()}</div>
<p><strong>Billed to:</strong> ${esc(buyer)}<br><strong>Engagement:</strong> ${esc(engagement)}</p>
<table><thead><tr><th>Description</th><th class="r">Amount</th></tr></thead><tbody>${lines}
<tr><td>Tax</td><td class="r">${money(inv.tax.amountMinor, inv.tax.currency)}</td></tr>
<tr class="total"><td>Total paid</td><td class="r">${money(inv.total.amountMinor, inv.total.currency)}</td></tr></tbody></table>
<p class="muted">Paid from escrow after you accepted the work. Zoikorum provides payment orchestration and escrow infrastructure; professional services
are delivered by independent professionals.</p><script>window.onload=()=>window.print()</script></body></html>`)
  w.document.close()
}
