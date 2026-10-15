// Single HTTP client for the Zoikorum API.
// - Attaches the access token, refreshes it once on 401, and retries.
// - Turns RFC 9457 Problem Details responses into ApiError.

export class ApiError extends Error {
  status: number
  code: string
  correlationId?: string
  extra?: Record<string, unknown>

  constructor(status: number, code: string, detail: string, correlationId?: string, extra?: Record<string, unknown>) {
    super(detail)
    this.status = status
    this.code = code
    this.correlationId = correlationId
    this.extra = extra
  }
}

export interface TokenPair {
  accessToken: string
  refreshToken: string  // empty for the web app: the server keeps it in an HttpOnly cookie
  tokenType: string
  expiresIn: number
}

// The access token (15 minutes) lives in memory only. The refresh token is an HttpOnly cookie set by the server, which
// page scripts cannot read; localStorage only remembers that a session exists, so a reload knows to ask for a new
// access token. Every request says X-Zk-Client: web so the server uses the cookie.
const SESSION_KEY = 'zk.session'
const LEGACY_REFRESH_KEY = 'zk.refresh'  // stored by earlier versions; used once, then removed
const WEB = { 'X-Zk-Client': 'web' }
let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null
let onSessionLost: () => void = () => {}

export const tokens = {
  set(pair: TokenPair) {
    accessToken = pair.accessToken
    localStorage.setItem(SESSION_KEY, '1')
    localStorage.removeItem(LEGACY_REFRESH_KEY)
  },
  clear() {
    accessToken = null
    localStorage.removeItem(SESSION_KEY)
    localStorage.removeItem(LEGACY_REFRESH_KEY)
  },
  hasRefresh: () => !!localStorage.getItem(SESSION_KEY) || !!localStorage.getItem(LEGACY_REFRESH_KEY),
  onSessionLost(fn: () => void) {
    onSessionLost = fn
  },
}

const UNREACHABLE = 'We can’t reach the Zoikorum server right now. Please try again in a moment.'

async function toError(res: Response): Promise<ApiError> {
  // 502/503/504 come from the proxy/gateway when the API itself is down.
  let body: Record<string, unknown> = {}
  try {
    body = await res.json()
  } catch {
    /* non-JSON error */
  }
  if ([502, 503, 504].includes(res.status) && !body.code) {
    return new ApiError(res.status, 'SERVER_UNREACHABLE', UNREACHABLE)
  }
  const detail = (body.detail as string) || res.statusText || 'Something went wrong'
  return new ApiError(res.status, (body.code as string) || 'HTTP_' + res.status, detail,
    body.correlationId as string | undefined, body.extra as Record<string, unknown> | undefined)
}

export async function refreshSession(): Promise<boolean> {
  if (!tokens.hasRefresh()) return false
  const legacy = localStorage.getItem(LEGACY_REFRESH_KEY)
  if (!refreshing) {
    refreshing = (async () => {
      const res = await fetch('/v1/auth/refresh', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...WEB },
        body: JSON.stringify(legacy ? { refreshToken: legacy } : {}),
      }).catch(() => null)
      if (!res) return false  // server unreachable: keep the session and try again later
      if (!res.ok) {
        tokens.clear()
        return false
      }
      tokens.set(await res.json())
      return true
    })().finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

interface RequestOptions {
  method?: string
  body?: unknown
  auth?: boolean
  query?: Record<string, string>
  headers?: Record<string, string>
  text?: boolean  // return the body as text (file downloads) instead of JSON
  blob?: boolean  // return a binary response (authenticated file downloads)
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, query, headers: extra = {}, text = false, blob = false } = opts
  const url = query ? `${path}?${new URLSearchParams(query)}` : path
  // Every change carries an Idempotency-Key (one per call, reused if the request is resent after a token refresh), so
  // the server never applies the same change twice.
  const idem: Record<string, string> = method !== 'GET' && !extra['Idempotency-Key'] ? { 'Idempotency-Key': crypto.randomUUID() } : {}

  const send = () =>
    fetch(url, {
      method,
      credentials: 'same-origin',
      headers: {
        ...WEB,
        ...idem,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(auth && accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...extra,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }).catch(() => {
      throw new ApiError(0, 'SERVER_UNREACHABLE', UNREACHABLE) // network down / server not running
    })

  let res = await send()
  if (res.status === 401 && auth && tokens.hasRefresh()) {
    const err = await toError(res.clone())
    // Step-up and MFA errors are answered by the user, not by a token refresh.
    if (!['STEP_UP_REQUIRED', 'MFA_REQUIRED', 'MFA_INVALID'].includes(err.code)) {
      if (await refreshSession()) res = await send()
      else onSessionLost()
    }
  }
  if (!res.ok) throw await toError(res)
  // Refresh dependent badges after successful commands; read receipts have their own updates.
  if (typeof window !== 'undefined' && method !== 'GET' && !path.startsWith('/v1/auth/') && !path.endsWith('/read')) {
    window.dispatchEvent(new Event('zk:activity'))
  }
  if (res.status === 204) return undefined as T
  if (text) return (await res.text()) as T
  if (blob) return (await res.blob()) as T
  return res.json() as Promise<T>
}

/** Every page of a paged list, in the endpoint's order, following nextCursor (at most maxPages of 100 rows). */
export async function allPages<T>(path: string, query: Record<string, string> = {}, maxPages = 50): Promise<T[]> {
  const out: T[] = []
  let cursor: string | null = null
  for (let i = 0; i < maxPages; i++) {
    const page: { items: T[]; nextCursor: string | null } =
      await api(path, { query: { ...query, limit: '100', ...(cursor ? { cursor } : {}) } })
    out.push(...page.items)
    cursor = page.nextCursor
    if (!cursor) break
  }
  return out
}

/** The server's answer when a professional page is opened before the professional profile exists. */
export const isNoProfile = (err: unknown) => err instanceof ApiError && err.code === 'PROFILE_NOT_FOUND'
