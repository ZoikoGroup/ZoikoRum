import { useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi } from '../api/auth'
import { ApiError } from '../api/client'

/** "Resend confirmation email": one new link a minute. In local development (no email service) the link is shown here. */
export function ResendConfirmation() {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [devToken, setDevToken] = useState<string | null>(null)

  async function resend() {
    setBusy(true)
    setMessage(null)
    try {
      const result = await authApi.resendConfirmation()
      setMessage(result.message)
      setDevToken(result.emailConfirmationToken)
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : 'Could not send the link. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="resend-confirmation">
      <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={resend}>{busy ? 'Sending…' : 'Resend confirmation email'}</button>
      {message && <span className="small muted" role="status"> {message}</span>}
      {devToken && <span className="small"> Development mode: <Link to={`/confirm-email?token=${encodeURIComponent(devToken)}`}>confirm now</Link>.</span>}
    </span>
  )
}
