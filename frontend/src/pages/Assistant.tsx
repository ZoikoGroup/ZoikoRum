import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { ErrorAlert } from '../components/ui'
import AssistantAnswer, { type AssistantReply } from '../components/AssistantAnswer'
import { clearDraft, readDraft, useAutosave } from '../lib/autosave'

type Message = { kind: 'user'; text: string } | { kind: 'assistant'; reply: AssistantReply }
type Retry = { text: string; key: string }

const DRAFT_KEY = 'assistant.page'

const GREETING: Message = {
  kind: 'assistant',
  reply: {
    answerId: 'welcome',
    intent: 'general',
    answer: 'Hello. I am the Zoikorum AI Concierge.',
    sections: [{ title: 'Ask me about', items: [
      'Finding, comparing and engaging professionals',
      'Requests, briefs, proposals and contracts',
      'Protected payments, milestones and delivery',
      'Verification, reviews, disputes and account help',
    ] }],
    suggestions: ['How do I find the right professional?', 'How are payments protected?', 'How does verification work?'],
    limitations: 'I explain published information only and cannot approve, verify, execute or decide anything.',
    related: [{ label: 'Help Center', to: '/app/help' }, { label: 'Privacy Policy', to: '/legal/privacy' }],
    disclaimer: 'Advisory assistance only.',
    fallbackUsed: false,
    model: 'welcome',
  },
}

export default function Assistant() {
  const [messages, setMessages] = useState<Message[]>([GREETING])
  const [input, setInput] = useState(() => readDraft<string>(DRAFT_KEY)?.value ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState<Retry | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useAutosave(DRAFT_KEY, input, input.trim().length > 0)
  useEffect(() => { if (!input.trim()) clearDraft(DRAFT_KEY) }, [input])

  async function submitText(raw: string, opts: { key?: string; appendUser?: boolean } = {}) {
    const text = raw.trim()
    if (!text || busy) return
    const key = opts.key ?? crypto.randomUUID()
    setError(null); setRetry(null); setBusy(true); setInput(''); clearDraft(DRAFT_KEY)
    if (opts.appendUser !== false) setMessages((m) => [...m, { kind: 'user', text }])
    try {
      const reply = await api<AssistantReply>('/v1/ai/chat', {
        method: 'POST',
        body: { message: text },
        headers: { 'Idempotency-Key': key },
      })
      setMessages((m) => [...m, { kind: 'assistant', reply }])
    } catch (err) {
      setError(err)
      setRetry({ text, key })
    } finally {
      setBusy(false)
      requestAnimationFrame(() => endRef.current?.scrollIntoView({ block: 'end' }))
    }
  }

  function send(event: FormEvent) {
    event.preventDefault()
    if (input.trim()) void submitText(input)
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>AI Assistant</h1>
          <p className="muted">Advisory help with the marketplace. It cannot see your account or perform actions.</p>
        </div>
      </div>
      <ErrorAlert error={error} />
      {retry && (
        <div className="row" style={{ justifyContent: 'flex-end', marginBottom: 8 }}>
          <button type="button" className="btn btn-secondary btn-sm"
            onClick={() => void submitText(retry.text, { key: retry.key, appendUser: false })}>Retry</button>
        </div>
      )}
      <section className="card panel" aria-label="Chat">
        <div role="log" aria-live="polite"
          style={{ display: 'flex', flexDirection: 'column', gap: 12, maxHeight: '58vh', overflowY: 'auto', paddingBottom: 8 }}>
          {messages.map((message, index) => message.kind === 'user' ? (
            <div key={index} className="assistant-row user"><p>{message.text}</p></div>
          ) : (
            <div key={index} className="assistant-row assistant">
              <AssistantAnswer reply={message.reply} onSuggest={(suggestion) => void submitText(suggestion)} />
            </div>
          ))}
          {busy && <p className="muted small" role="status">Finding relevant information…</p>}
          <div ref={endRef} />
        </div>
        <form onSubmit={send} style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <label className="sr-only" htmlFor="assistant-page-message">Your question</label>
          <input id="assistant-page-message" className="input" value={input} maxLength={4000}
            placeholder="Ask about requests, contracts, protected payments, disputes…"
            onChange={(e) => setInput(e.target.value)} disabled={busy} />
          <button className="btn btn-primary" disabled={busy || !input.trim()}>{busy ? 'Sending…' : 'Send'}</button>
        </form>
      </section>
      <p className="muted small">Advisory assistance only. It does not approve terms, execute contracts, release funds or decide disputes.</p>
    </div>
  )
}
