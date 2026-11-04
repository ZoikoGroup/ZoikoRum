import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { clearDraft, readDraft, useAutosave } from '../lib/autosave'
import { Icon, type IconName } from './dashboard'
import { useDialog } from './ui'
import AssistantAnswer, { type AssistantReply } from './AssistantAnswer'

type Message =
  | { kind: 'user'; text: string }
  | { kind: 'assistant'; reply: AssistantReply }

type Retry = { text: string; key: string }

const DRAFT_KEY = 'assistant.widget'

const WELCOME_INTENTS: { icon: IconName; title: string; text: string; prompt: string }[] = [
  { icon: 'building', title: 'For enterprises', text: 'Find professionals and explore engagement pathways', prompt: 'How can my company find and engage the right professional?' },
  { icon: 'user', title: 'For professionals', text: 'Learn about joining, verification and opportunities', prompt: 'How do I join Zoikorum as a professional and get verified?' },
  { icon: 'shield', title: 'Trust, contracts & payments', text: 'Understand published processes and protections', prompt: 'How do protected payments, milestones and contracts work?' },
  { icon: 'help', title: 'Help & support', text: 'Find the right route for help with your account', prompt: 'How can I contact support about my account?' },
]

export default function AssistantWidget() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState(() => readDraft<string>(DRAFT_KEY)?.value ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState<Retry | null>(null)
  const launcherRef = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const threadRef = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const panelRef = useDialog<HTMLElement>(close, open)

  useAutosave(DRAFT_KEY, input, input.trim().length > 0)
  useEffect(() => { if (!input.trim()) clearDraft(DRAFT_KEY) }, [input])

  useEffect(() => {
    if (open && atBottom.current) threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight })
  }, [messages, busy, open, error])

  function close() {
    setOpen(false)
  }

  function reset() {
    setMessages([]); setError(''); setRetry(null); setInput(''); clearDraft(DRAFT_KEY)
    inputRef.current?.focus()
  }

  async function submitText(raw: string, opts: { key?: string; appendUser?: boolean } = {}) {
    const text = raw.trim()
    if (!text || busy) return
    const key = opts.key ?? crypto.randomUUID()
    setError(''); setRetry(null); setBusy(true); setInput(''); clearDraft(DRAFT_KEY); atBottom.current = true
    if (opts.appendUser !== false) setMessages((m) => [...m, { kind: 'user', text }])
    try {
      const reply = await api<AssistantReply>('/v1/ai/chat', {
        method: 'POST',
        body: { message: text },
        headers: { 'Idempotency-Key': key },
      })
      setMessages((m) => [...m, { kind: 'assistant', reply }])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The assistant could not answer. Please try again.')
      setRetry({ text, key })
    } finally {
      setBusy(false)
    }
  }

  function send(event: FormEvent) {
    event.preventDefault()
    if (input.trim()) void submitText(input)
  }

  function pickIntent(prompt: string) {
    setInput(prompt)
    clearDraft(DRAFT_KEY)
    inputRef.current?.focus()
  }

  return (
    <>
      <button ref={launcherRef} type="button"
        className={`assistant-launcher${open ? ' is-open' : ''}`}
        aria-label={open ? 'Close Zoikorum AI assistant' : 'Open Zoikorum AI assistant'}
        aria-expanded={open} aria-controls="assistant-panel" onClick={() => (open ? close() : setOpen(true))}>
        <span className="assistant-launcher-mark"><img src="/icon-192.png" alt="" width={24} height={24} /></span>
        <span className="assistant-launcher-label">Chat with Zoikorum</span>
      </button>

      {open && (
        <section ref={panelRef} id="assistant-panel" className="assistant-panel" role="dialog"
          aria-labelledby="assistant-title">
          <header className="assistant-header">
            <img src="/icon-192.png" alt="" width={36} height={36} />
            <div className="assistant-title">
              <strong id="assistant-title">Zoikorum AI Concierge</strong>
              <span>AI assistant · Public information</span>
            </div>
            <button type="button" className="assistant-icon-btn" aria-label="Start a new chat" onClick={reset}>
              <Icon name="refresh" />
            </button>
            <button type="button" className="assistant-icon-btn" aria-label="Close assistant" onClick={close}>
              <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden fill="none" stroke="currentColor"
                strokeWidth="1.8" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
          </header>

          <div ref={threadRef} className="assistant-thread" role="log" aria-live="polite"
            onScroll={(e) => {
              const el = e.currentTarget
              atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
            }}>
            {messages.length === 0 ? (
              <div className="assistant-welcome">
                <h2>Find the right professional. Engage with confidence.</h2>
                <p>Explore professional services, engagement steps, verification processes, contracts and platform policies.</p>
                <h3>What would you like to explore?</h3>
                <div className="assistant-intents">
                  {WELCOME_INTENTS.map((item) => (
                    <button key={item.title} type="button" className="assistant-intent" onClick={() => pickIntent(item.prompt)}>
                      <span className="assistant-intent-icon"><Icon name={item.icon} /></span>
                      <span><strong>{item.title}</strong><small>{item.text}</small></span>
                      <Icon name="arrow" />
                    </button>
                  ))}
                </div>
              </div>
            ) : messages.map((message, index) => message.kind === 'user' ? (
              <div key={index} className="assistant-row user"><p>{message.text}</p></div>
            ) : (
              <article key={index} className="assistant-row assistant">
                <AssistantAnswer reply={message.reply} onSuggest={(suggestion) => void submitText(suggestion)} onNavigate={close} />
              </article>
            ))}
            {busy && <div className="assistant-thinking" role="status"><span /><span /><span />Finding relevant information…</div>}
            {error && (
              <div className="assistant-error" role="alert">
                <p>{error}</p>
                {retry && <button type="button" className="btn btn-secondary btn-sm"
                  onClick={() => void submitText(retry.text, { key: retry.key, appendUser: false })}>Retry</button>}
              </div>
            )}
          </div>

          <form className="assistant-composer" onSubmit={send}>
            <label className="sr-only" htmlFor="assistant-message">Ask about Zoikorum</label>
            <input id="assistant-message" ref={inputRef} value={input} maxLength={4000}
              placeholder="Ask about Zoikorum..." onChange={(e) => setInput(e.target.value)} disabled={busy}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  if ((e.nativeEvent as KeyboardEvent).isComposing) return
                  e.preventDefault()
                  if (input.trim()) void submitText(input)
                }
              }} />
            <button type="submit" aria-label="Send message" disabled={busy || !input.trim()}>
              <Icon name="arrow" />
            </button>
          </form>
          <footer className="assistant-footer">
            <span>AI-generated responses may be inaccurate. Do not share confidential information.</span>
            <span><Link to="/legal/privacy" onClick={close}>Privacy</Link> · <Link to="/app/help" onClick={close}>Help</Link></span>
          </footer>
        </section>
      )}
    </>
  )
}
