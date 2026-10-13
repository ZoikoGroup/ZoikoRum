import { createHash } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import { MAX_FILE_BYTES, sha256OfFile, toUpload } from './files'

const pdfBytes = new TextEncoder().encode('%PDF-1.4\nmaster file')
const pdf = (name = 'master.pdf') => new File([pdfBytes], name, { type: 'application/pdf' })

describe('toUpload', () => {
  it('sends the bytes, the type and a SHA-256 the server can check', async () => {
    const up = await toUpload(pdf())
    expect(up.contentType).toBe('application/pdf')
    expect(up.size).toBe(pdfBytes.length)
    expect(atob(up.dataBase64)).toBe('%PDF-1.4\nmaster file')
    expect(up.sha256).toBe(createHash('sha256').update(pdfBytes).digest('hex'))
  })

  it('maps Office and image extensions, case-insensitively', async () => {
    expect((await toUpload(new File(['x'], 'Ledger.XLSX'))).contentType).toBe('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    expect((await toUpload(new File(['x'], 'scan.jpeg'))).contentType).toBe('image/jpeg')
  })

  it('refuses unsupported types and types outside the allowed list', async () => {
    await expect(toUpload(new File(['x'], 'setup.exe'))).rejects.toThrow(/setup\.exe/)
    await expect(toUpload(new File(['x'], 'notes.docx'), ['pdf', 'jpg', 'jpeg', 'png'])).rejects.toThrow(/PDF, JPG, JPEG, PNG/)
  })

  it('refuses files over 10 MB before reading them', async () => {
    const big = new File([new Uint8Array(MAX_FILE_BYTES + 1)], 'big.pdf')
    await expect(toUpload(big)).rejects.toThrow(/larger than 10 MB/)
  })

  it('encodes large files without overflowing the call stack', async () => {
    const bytes = new Uint8Array(200_000).fill(65)
    const up = await toUpload(new File([bytes], 'large.csv'))
    expect(atob(up.dataBase64).length).toBe(200_000)
  })
})

describe('sha256OfFile', () => {
  it('matches the standard SHA-256', async () => {
    expect(await sha256OfFile(pdf())).toBe(createHash('sha256').update(pdfBytes).digest('hex'))
  })
})
