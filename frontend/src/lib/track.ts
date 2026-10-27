/* Product-funnel events (Onboarding & Category wireframes, Request flow, search): fire-and-forget calls to
   POST /v1/analytics/events. Events are batched, sent after a short pause or when the page is hidden (sendBeacon, so a
   closing tab still delivers them), and tracking can never break a page: every failure is swallowed.
   No personal data: only the event name and short slugs (a step, a filter, a specialization) or small numbers. The visit
   id is random, lives in sessionStorage for this tab only and is never an account id; the server stores only its hash. */

export type TrackEvent =
  | 'onboarding_step_viewed' | 'onboarding_step_completed' | 'profile_published'
  | 'request_step_viewed' | 'request_step_completed' | 'request_abandoned' | 'proposal_started' | 'proposal_submitted'
  | 'filter_applied' | 'specialization_selected' | 'compare_opened' | 'quick_view_opened' | 'enterprise_cta_clicked'
  | 'verification_detail_viewed' | 'service_card_opened'

/** The only properties the server keeps: step / filter / specialization / source (short slugs) and position (a number). */
export interface TrackProps { step?: string; filter?: string; specialization?: string; source?: string; position?: number }

export const TRACK_URL = '/v1/analytics/events'
export const BATCH_SIZE = 25  // the server's maximum per request
const FLUSH_DELAY_MS = 2000
const MAX_QUEUED = 100  // if the server is unreachable, keep the newest events only
const VISIT_KEY = 'zk.visit'

let queue: { name: TrackEvent; props: TrackProps }[] = []
let timer: ReturnType<typeof setTimeout> | null = null
let memoryVisit: string | null = null
let listening = false

function visitId(): string {
  try {
    const stored = sessionStorage.getItem(VISIT_KEY)
    if (stored) return stored
  } catch { /* storage unavailable: keep the id in memory */ }
  if (!memoryVisit) {
    memoryVisit = typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().replace(/-/g, '')
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`
  }
  try { sessionStorage.setItem(VISIT_KEY, memoryVisit) } catch { /* ignore */ }
  return memoryVisit
}

const slug = (v: unknown) => (typeof v === 'string' ? v.trim().toLowerCase().replace(/\s+/g, '-').slice(0, 60) : undefined)

function clean(props: TrackProps): TrackProps {
  const out: TrackProps = {}
  for (const key of ['step', 'filter', 'specialization', 'source'] as const) {
    const value = slug(props[key])
    if (value) out[key] = value
  }
  if (typeof props.position === 'number' && Number.isInteger(props.position) && props.position >= 0) out.position = props.position
  return out
}

function send(useBeacon: boolean) {
  while (queue.length) {
    const body = JSON.stringify({ sessionId: visitId(), events: queue.splice(0, BATCH_SIZE) })
    try {
      if (useBeacon && typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function'
        && navigator.sendBeacon(TRACK_URL, new Blob([body], { type: 'application/json' }))) continue
      if (typeof fetch === 'function') {
        void fetch(TRACK_URL, { method: 'POST', keepalive: true, credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-Zk-Client': 'web' }, body }).catch(() => {})
      }
    } catch { /* never let analytics break a page */ }
  }
}

/** Sends everything queued now. ``useBeacon`` for page hide or unload, where a normal request may be cancelled. */
export function flush(useBeacon = false) {
  try {
    if (timer) { clearTimeout(timer); timer = null }
    send(useBeacon)
  } catch { /* ignore */ }
}

function listen() {
  if (listening || typeof window === 'undefined') return
  listening = true
  try {
    window.addEventListener('pagehide', () => flush(true))
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(true) })
  } catch { /* ignore */ }
}

/** Records one funnel event. Fire-and-forget: returns at once and never throws. */
export function track(name: TrackEvent, props: TrackProps = {}): void {
  try {
    listen()
    queue.push({ name, props: clean(props ?? {}) })
    if (queue.length > MAX_QUEUED) queue = queue.slice(-MAX_QUEUED)
    if (queue.length >= BATCH_SIZE) flush()
    else if (!timer) timer = setTimeout(() => flush(), FLUSH_DELAY_MS)
  } catch { /* never let analytics break a page */ }
}

/** Test helper: forget queued events and the visit id. */
export function resetTracking() {
  if (timer) clearTimeout(timer)
  timer = null
  queue = []
  memoryVisit = null
  try { sessionStorage.removeItem(VISIT_KEY) } catch { /* ignore */ }
}
