import { useState } from 'react'
import { SUPPORT_STATUS, type SupportRequest } from '../api/support'
import { ErrorAlert } from './ui'

/** One help request: what was asked, the conversation, and a reply box (customer or support agent). */
export function SupportThread({ request, agent = false, onReply, onResolve }: {
  request: SupportRequest; agent?: boolean
  onReply: (message: string, resolve: boolean) => Promise<void>; onResolve?: () => Promise<void>
}) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const st = SUPPORT_STATUS[request.status]
  const send = async (resolve: boolean) => {
    setBusy(true); setError(null)
    try { await onReply(message.trim(), resolve); setMessage('') } catch (err) { setError(err) } finally { setBusy(false) }
  }
  return (
    <section className="card panel">
      <div className="panel-head"><h2>{request.subject}</h2><span className={`badge ${st.tone}`}>{st.label}</span></div>
      <p className="muted small" style={{ marginTop: 0 }}><code>{request.reference}</code>
        {request.context.engagement && <> · engagement <code>{request.context.engagement}</code></>}
        {request.context.errorReference && <> · error reference <code>{request.context.errorReference}</code></>}
        {agent && request.requesterName && <> · from {request.requesterName}</>}
        {!request.firstRespondedAt && request.status !== 'RESOLVED' && <> · first answer by {new Date(request.firstResponseDueAt).toLocaleString()}</>}</p>
      <ol className="support-thread">{request.messages.map((m) => (
        <li key={m.id} className={m.fromStaff ? 'staff' : ''}><strong>{m.authorName}</strong> <span className="muted small">{new Date(m.createdAt).toLocaleString()}</span>
          <p style={{ whiteSpace: 'pre-wrap', margin: '4px 0 0' }}>{m.body}</p></li>))}</ol>
      <ErrorAlert error={error} />
      <label className="label" htmlFor={`support-reply-${request.id}`}>{agent ? 'Answer' : 'Add a reply'}</label>
      <textarea id={`support-reply-${request.id}`} className="input" rows={3} maxLength={5000} value={message} onChange={(e) => setMessage(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn btn-primary" disabled={busy || message.trim().length < 2} onClick={() => send(false)}>Send</button>
        {agent && <button className="btn btn-secondary" disabled={busy || message.trim().length < 2} onClick={() => send(true)}>Send and mark resolved</button>}
        {!agent && onResolve && request.status !== 'RESOLVED' && <button className="btn btn-ghost" disabled={busy} onClick={() => { void onResolve() }}>My problem is solved</button>}
      </div>
    </section>
  )
}
