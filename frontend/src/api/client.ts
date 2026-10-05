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
  refreshToken: string
  tokenType: string
  expiresIn: number
}

// Access token lives in memory only. The refresh token is kept in localStorage so a reload
// keeps the session. (Production: move the refresh token to an httpOnly cookie.)
const REFRESH_KEY = 'zk.refresh'
let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null
let onSessionLost: () => void = () => {}

export const tokens = {
  set(pair: TokenPair) {
    accessToken = pair.accessToken
    localStorage.setItem(REFRESH_KEY, pair.refreshToken)
  },
  clear() {
    accessToken = null
    localStorage.removeItem(REFRESH_KEY)
  },
  hasRefresh: () => !!localStorage.getItem(REFRESH_KEY),
  onSessionLost(fn: () => void) {
    onSessionLost = fn
  },
}

const UNREACHABLE = 'We can’t reach the Zoikorum server right now. Please try again in a moment.'

async function toError(res: Response): Promise<ApiError> {
  // 502/503/504 come from the proxy/gateway when the API itself is down.
  if ([502, 503, 504].includes(res.status)) return new ApiError(res.status, 'SERVER_UNREACHABLE', UNREACHABLE)
  let body: Record<string, unknown> = {}
  try {
    body = await res.json()
  } catch {
    /* non-JSON error */
  }
  const detail = (body.detail as string) || res.statusText || 'Something went wrong'
  return new ApiError(res.status, (body.code as string) || 'HTTP_' + res.status, detail,
    body.correlationId as string | undefined, body.extra as Record<string, unknown> | undefined)
}

export async function refreshSession(): Promise<boolean> {
  const rt = localStorage.getItem(REFRESH_KEY)
  if (!rt) return false
  if (!refreshing) {
    refreshing = (async () => {
      const res = await fetch('/v1/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refreshToken: rt }),
      })
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
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, query } = opts
  const url = query ? `${path}?${new URLSearchParams(query)}` : path

  const send = () =>
    fetch(url, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(auth && accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
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
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}
