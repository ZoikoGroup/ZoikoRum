/* Record exports (Payments & Escrow s.13/s.21, Request flow s.18): CSV and JSON packs built in the browser from data the
   viewer can already see, and saving PDFs the server generates (agreements, invoices). */

/** Saves a file the server generated (PDF) under the given name. */
export function saveBlob(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  Object.assign(document.createElement('a'), { href: url, download: name }).click()
  URL.revokeObjectURL(url)
}

export function downloadFile(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  Object.assign(document.createElement('a'), { href: url, download: name }).click()
  URL.revokeObjectURL(url)
}


export function csv(rows: (string | number | null | undefined)[][]): string {
  return rows.map((r) => r.map((v) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }).join(',')).join('\n')
}
