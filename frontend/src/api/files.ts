import { api } from './client'

/* Document uploads: the browser sends the file itself (base64) with its type and SHA-256 fingerprint; the server checks
   both before storing it. Stored files open only for people allowed to see them, and every opening is audited. */

export type UploadContentType = 'application/pdf' | 'image/jpeg' | 'image/png' | 'text/csv'
  | 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  | 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

export interface Upload { name: string; sha256: string; size: number; contentType: UploadContentType; dataBase64: string }
export interface StoredFile { name: string; sha256: string; size: number; contentType: string | null; hasFile: boolean }

const TYPES: Record<string, UploadContentType> = {
  pdf: 'application/pdf', jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', csv: 'text/csv',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}
export const DOC_ACCEPT = '.pdf,.docx,.xlsx,.csv,.png,.jpg,.jpeg'
export const MAX_FILE_BYTES = 10 * 1024 * 1024

export async function sha256OfFile(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** Reads a file for upload. `allowed` limits extensions (e.g. verification takes only PDF, JPG and PNG). */
export async function toUpload(file: File, allowed: string[] = Object.keys(TYPES)): Promise<Upload> {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  const contentType = TYPES[ext]
  if (!contentType || !allowed.includes(ext)) throw new Error(`${file.name}: upload a ${allowed.map((a) => a.toUpperCase()).join(', ')} file.`)
  if (file.size > MAX_FILE_BYTES) throw new Error(`${file.name} is larger than 10 MB.`)
  const bytes = new Uint8Array(await file.arrayBuffer())
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return { name: file.name, sha256: await sha256OfFile(file), size: file.size, contentType, dataBase64: btoa(bin) }
}

/** Fetches a stored file with the user's session and opens it in a new tab. */
export async function openStoredFile(url: string) {
  const blob = await api<Blob>(url, { blob: true })
  const href = URL.createObjectURL(blob)
  window.open(href, '_blank', 'noopener')
  setTimeout(() => URL.revokeObjectURL(href), 60_000)
}
