import { useEffect, useState } from 'react'

/* Autosave (Onboarding s.20/s.22, RFP flow s.19: "autosave within 1s of pause in typing"; "user abandons mid-flow ->
   autosave + resume prompt on return"). Drafts live in this browser only, keyed per signed-in user, and are cleared
   once the form is submitted. Storage can be unavailable (private windows), so every access is guarded. */

export interface Draft<T> { value: T; savedAt: string }
const PREFIX = 'zk.draft.'
export const AUTOSAVE_DELAY_MS = 800

export function readDraft<T>(key: string | null): Draft<T> | null {
  if (!key) return null
  try {
    const raw = localStorage.getItem(PREFIX + key)
    return raw ? (JSON.parse(raw) as Draft<T>) : null
  } catch { return null }
}

export function clearDraft(key: string | null) {
  if (!key) return
  try { localStorage.removeItem(PREFIX + key) } catch { /* nothing to clear */ }
}

/** Saves `value` shortly after it stops changing, while `dirty` is true. Returns when it was last saved. */
export function useAutosave<T>(key: string | null, value: T, dirty: boolean): string | null {
  const [savedAt, setSavedAt] = useState<string | null>(null)
  useEffect(() => {
    if (!key || !dirty) return
    const t = window.setTimeout(() => {
      const at = new Date().toISOString()
      try {
        localStorage.setItem(PREFIX + key, JSON.stringify({ value, savedAt: at }))
        setSavedAt(at)
      } catch { /* storage full or blocked: the form still works, it just is not saved */ }
    }, AUTOSAVE_DELAY_MS)
    return () => window.clearTimeout(t)
  }, [key, value, dirty])
  return savedAt
}
