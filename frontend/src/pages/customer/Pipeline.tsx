import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { contractApi, type Contract } from '../../api/contracts'
import { ApiError } from '../../api/client'
import { messagingApi, type ConversationMessage, type MessageContextType, type MessageThread } from '../../api/messaging'
import { proposalApi, type ProposalRequest } from '../../api/proposals'
import { useAuth } from '../../auth/AuthContext'
import { Icon } from '../../components/dashboard'
import { PortalHeader } from '../../components/portal'

type Tab = 'All' | 'Engagements' | 'Requests' | 'Professionals' | 'System'
type StartOption = { key: string; contextType: MessageContextType; contextId: string; title: string; counterpart: string }

const TABS: Tab[] = ['All', 'Engagements', 'Requests', 'Professionals', 'System']
const ACCEPTED_FILE_TYPES = '.pdf,.png,.jpg,.jpeg,.docx,.xlsx,.csv,.txt'
const MAX_FILE_SIZE = 10 * 1024 * 1024

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?'
}

function timeLabel(value: string) {
  const date = new Date(value)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function mergeThreads(current: MessageThread[], incoming: MessageThread[]) {
  const incomingIds = new Set(incoming.map((thread) => thread.id))
  return [...incoming, ...current.filter((thread) => !incomingIds.has(thread.id))]
    .sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt))
}

function contextUrl(thread: MessageThread, professional: boolean) {
  if (thread.contextType === 'PROPOSAL_REQUEST') {
    return professional ? `/app/professional/requests/${thread.contextId}` : `/app/requests/${thread.contextId}`
  }
  if (thread.contextType === 'CONTRACT') {
    return professional ? `/app/professional/engagements/${thread.contextId}` : `/app/engagements/${thread.contextId}`
  }
  return null
}

function requestOptions(requests: ProposalRequest[], professional: boolean): StartOption[] {
  return requests.filter((request) => request.status !== 'DRAFT' && (!professional || !request.ndaRequired || request.ndaAccepted)).map((request) => ({
    key: `PROPOSAL_REQUEST:${request.id}`,
    contextType: 'PROPOSAL_REQUEST',
    contextId: request.id,
    title: request.service,
    counterpart: professional ? request.organizationName || request.buyerName || 'Customer' : request.professional.displayName,
  }))
}

function contractOptions(contracts: Contract[], professional: boolean): StartOption[] {
  return contracts.map((contract) => ({
    key: `CONTRACT:${contract.id}`,
    contextType: 'CONTRACT',
    contextId: contract.id,
    title: contract.title || contract.reference,
    counterpart: contract.parties.find((party) => party.role === (professional ? 'BUYER' : 'PROFESSIONAL'))?.name || 'Conversation',
  }))
}

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`))
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        reject(new Error(`Could not read ${file.name}.`))
        return
      }
      resolve(result.slice(result.indexOf(',') + 1))
    }
    reader.readAsDataURL(file)
  })
}

export function MessagesPage() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const professional = user?.personas.includes('PROFESSIONAL') ?? false
  const customer = user?.personas.some((role) => ['BUYER', 'ENTERPRISE_ADMIN', 'ENTERPRISE_MEMBER'].includes(role)) ?? false
  const [threads, setThreads] = useState<MessageThread[]>([])
  const [threadsCursor, setThreadsCursor] = useState<string | null>(null)
  const [loadingMoreThreads, setLoadingMoreThreads] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [earlierCursor, setEarlierCursor] = useState<string | null>(null)
  const [loadingEarlier, setLoadingEarlier] = useState(false)
  const [tab, setTab] = useState<Tab>('All')
  const [conversationTab, setConversationTab] = useState<'Messages' | 'Files' | 'Audit Trail'>('Messages')
  const search = searchParams.get('search') ?? ''
  const setSearch = (value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set('search', value)
    else next.delete('search')
    setSearchParams(next, { replace: true })
  }
  const [draft, setDraft] = useState('')
  const [queuedFiles, setQueuedFiles] = useState<File[]>([])
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [showStart, setShowStart] = useState(false)
  const [startOptions, setStartOptions] = useState<StartOption[]>([])
  const [loadingOptions, setLoadingOptions] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const retryRef = useRef<{ payload: string; key: string } | null>(null)
  const uploadedRef = useRef<Map<File, string>>(new Map())
  const activeThreadRef = useRef<string | null>(null)
  useEffect(() => { activeThreadRef.current = selectedId }, [selectedId])
  const cursorRef = useRef<string | null>(null)
  const historyInitializedRef = useRef(false)
  const threadsCursorRef = useRef<string | null>(null)
  const threadPagesInitializedRef = useRef(false)
  const selected = threads.find((thread) => thread.id === selectedId) ?? null
  const contextTypeParam = searchParams.get('contextType')
  const contextIdParam = searchParams.get('contextId')
  const requestedContextType: MessageContextType | null = contextTypeParam === 'PROPOSAL_REQUEST' || contextTypeParam === 'CONTRACT'
    ? contextTypeParam
    : null

  const refreshThreads = useCallback(async () => {
    const page = await messagingApi.list()
    setThreads((current) => mergeThreads(current, page.items))
    setSelectedId((current) => current ?? page.items[0]?.id ?? null)
    if (!threadPagesInitializedRef.current) {
      threadPagesInitializedRef.current = true
      threadsCursorRef.current = page.nextCursor
      setThreadsCursor(page.nextCursor)
    }
  }, [])

  const selectThread = useCallback((threadId: string) => {
    cursorRef.current = null
    historyInitializedRef.current = false
    setEarlierCursor(null)
    setMessages([])
    setConversationTab('Messages')
    setDraft('')
    setQueuedFiles([])
    retryRef.current = null
    uploadedRef.current.clear()
    setSelectedId(threadId)
  }, [])

  useEffect(() => {
    if (!contextIdParam || !requestedContextType) return
    let active = true
    void messagingApi.open(requestedContextType, contextIdParam).then((thread) => {
      if (!active) return
      setThreads((current) => [thread, ...current.filter((item) => item.id !== thread.id)])
      selectThread(thread.id)
      setSearchParams({}, { replace: true })
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Could not open this conversation.')
      setSearchParams({}, { replace: true })
    })
    return () => { active = false }
  }, [contextIdParam, requestedContextType, selectThread, setSearchParams])

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const page = await messagingApi.list()
        if (!active) return
        setThreads((current) => mergeThreads(current, page.items))
        setSelectedId((current) => current ?? page.items[0]?.id ?? null)
        if (!threadPagesInitializedRef.current) {
          threadPagesInitializedRef.current = true
          threadsCursorRef.current = page.nextCursor
          setThreadsCursor(page.nextCursor)
        }
        setError('')
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load conversations.')
      } finally {
        if (active) setLoading(false)
      }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 12000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  useEffect(() => {
    if (!selectedId) return
    let active = true
    const refresh = async () => {
      try {
        const page = await messagingApi.messages(selectedId)
        if (!active) return
        const ordered = [...page.items].reverse()
        setMessages((current) => {
          const byId = new Map(current.map((message) => [message.id, message]))
          ordered.forEach((message) => byId.set(message.id, message))
          return [...byId.values()].sort((a, b) => a.sequence - b.sequence)
        })
        if (!historyInitializedRef.current) {
          cursorRef.current = page.nextCursor
          historyInitializedRef.current = true
          setEarlierCursor(page.nextCursor)
        }
        const through = ordered.at(-1)?.sequence
        if (through && document.visibilityState === 'visible') {
          await messagingApi.markRead(selectedId, through)
          if (!active) return
          setThreads((current) => current.map((thread) => thread.id === selectedId ? { ...thread, unreadCount: 0 } : thread))
        }
      } catch (cause) {
        if (active) {
          setError(cause instanceof Error ? cause.message : 'Could not load this conversation.')
          if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
            setMessages([])
            setSelectedId(null)
            setThreads(current => current.filter(thread => thread.id !== selectedId))
          }
        }
      }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 7000)
    return () => { active = false; window.clearInterval(timer) }
  }, [selectedId])

  async function loadEarlier() {
    if (!selectedId || !earlierCursor || loadingEarlier) return
    setLoadingEarlier(true)
    try {
      const page = await messagingApi.messages(selectedId, Number(earlierCursor))
      const older = [...page.items].reverse()
      setMessages((current) => {
        const byId = new Map(older.map((message) => [message.id, message]))
        current.forEach((message) => byId.set(message.id, message))
        return [...byId.values()].sort((a, b) => a.sequence - b.sequence)
      })
      cursorRef.current = page.nextCursor
      setEarlierCursor(page.nextCursor)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load earlier messages.')
    } finally {
      setLoadingEarlier(false)
    }
  }

  async function loadMoreThreads() {
    if (!threadsCursorRef.current || loadingMoreThreads) return
    setLoadingMoreThreads(true)
    try {
      const page = await messagingApi.list(threadsCursorRef.current)
      setThreads((current) => mergeThreads(current, page.items))
      threadsCursorRef.current = page.nextCursor
      setThreadsCursor(page.nextCursor)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load more conversations.')
    } finally {
      setLoadingMoreThreads(false)
    }
  }

  const visibleThreads = useMemo(() => {
    const query = search.trim().toLocaleLowerCase()
    return threads.filter((thread) => {
      if (tab === 'Engagements' && thread.contextType !== 'CONTRACT') return false
      if (tab === 'Requests' && thread.contextType !== 'PROPOSAL_REQUEST') return false
      if (tab === 'System' && !thread.lastMessageFromSystem) return false
      if (tab === 'Professionals' && thread.contextType === 'DISPUTE') return false
      return !query || `${thread.counterpartName} ${thread.title} ${thread.contextId} ${thread.id} ${thread.lastMessage}`.toLocaleLowerCase().includes(query)
    })
  }, [threads, tab, search])

  async function startConversation() {
    setError('')
    setLoadingOptions(true)
    setShowStart(true)
    try {
      const jobs: Promise<StartOption[]>[] = []
      if (customer) {
        jobs.push(proposalApi.list('buyer').then((rows) => requestOptions(rows, false)))
        jobs.push(contractApi.list('buyer').then((rows) => contractOptions(rows, false)))
      }
      if (professional) {
        jobs.push(proposalApi.list('professional').then((rows) => requestOptions(rows, true)))
        jobs.push(contractApi.list('professional').then((rows) => contractOptions(rows, true)))
      }
      const groups = await Promise.all(jobs)
      const existing = new Set(threads.map((thread) => `${thread.contextType}:${thread.contextId}`))
      setStartOptions(groups.flat().filter((option) => !existing.has(option.key)))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load requests and engagements.')
      setShowStart(false)
    } finally {
      setLoadingOptions(false)
    }
  }

  async function openConversation(option: StartOption) {
    try {
      setError('')
      const thread = await messagingApi.open(option.contextType, option.contextId)
      setThreads((current) => [thread, ...current.filter((item) => item.id !== thread.id)])
      selectThread(thread.id)
      setShowStart(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not open this conversation.')
    }
  }

  function queueFiles(event: ChangeEvent<HTMLInputElement>) {
    const incoming = Array.from(event.target.files ?? [])
    event.target.value = ''
    const tooLarge = incoming.find((file) => file.size > MAX_FILE_SIZE)
    if (tooLarge) {
      setError(`${tooLarge.name} is larger than the 10 MB file limit.`)
      return
    }
    if (queuedFiles.length + incoming.length > 5) {
      setError('Attach up to five files per message.')
      return
    }
    setQueuedFiles((current) => [...current, ...incoming])
    setError('')
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault()
    if (!selected || selected.locked || sending) return
    const body = draft.trim()
    if (!body && queuedFiles.length === 0) return
    setSending(true)
    setError('')
    try {
      const uploaded = await Promise.all(queuedFiles.map(async (file) => {
        const existing = uploadedRef.current.get(file)
        if (existing) return { id: existing }
        const data = await readAsBase64(file)
        const result = await messagingApi.upload(selected.id, file.name, data)
        uploadedRef.current.set(file, result.id)
        return result
      }))
      const attachmentIds = uploaded.map((file) => file.id)
      const payload = JSON.stringify({ thread: selected.id, body, attachmentIds })
      if (retryRef.current?.payload !== payload) retryRef.current = { payload, key: crypto.randomUUID() }
      const sent = await messagingApi.send(selected.id, body, attachmentIds, retryRef.current.key)
      if (activeThreadRef.current !== selected.id) return
      setMessages((current) => [...current.filter(message => message.id !== sent.id), sent].sort((a, b) => a.sequence - b.sequence))
      setDraft('')
      setQueuedFiles([])
      retryRef.current = null
      uploadedRef.current.clear()
      await refreshThreads()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Message could not be sent.')
    } finally {
      setSending(false)
    }
  }

  async function downloadFile(threadId: string, attachmentId: string, name: string) {
    try {
      const blob = await messagingApi.download(threadId, attachmentId)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = name
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'File could not be downloaded.')
    }
  }

  const targetUrl = selected ? contextUrl(selected, selected.viewerRole === 'PROFESSIONAL') : null
  const sharedFiles = useMemo(() => [...new Map(messages.flatMap(message => message.attachments).map(file => [file.id, file])).values()], [messages])

  return (
    <>
      <PortalHeader
        eyebrow="Messages"
        title="Communicate with confidence."
        subtitle="Keep all conversations, files and decisions in one secure place."
        actions={<button className="btn btn-primary" onClick={() => void startConversation()}><Icon name="message" /> New message</button>}
      />
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <section className="messages message-workspace" aria-label="Messages">
        <aside className="card message-inbox">
          <div className="message-inbox-head">
            <label className="message-search"><Icon name="search" /><input aria-label="Search conversations" placeholder="Search conversations" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
            <div className="message-tabs" role="tablist" aria-label="Conversation filters">
              {TABS.map((item) => <button key={item} role="tab" aria-selected={tab === item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>{item}</button>)}
            </div>
          </div>
          <div className="message-thread-list">
            {loading ? <p className="muted small message-inbox-state">Loading conversations…</p> :
              visibleThreads.length ? visibleThreads.map((thread) => (
                <button key={thread.id} disabled={sending} className={`message-thread ${selectedId === thread.id ? 'selected' : ''}`} onClick={() => selectThread(thread.id)}>
                  <span className="message-avatar">
                    {thread.photoUrl ? <img src={thread.photoUrl} alt="" /> : initials(thread.counterpartName)}
                  </span>
                  <span className="message-thread-copy">
                    <span className="message-thread-top"><strong>{thread.counterpartName}</strong><time>{timeLabel(thread.updatedAt)}</time></span>
                    <span className="message-thread-title">{thread.title}</span>
                    <span className="message-thread-preview">{thread.lastMessageFromSystem && <span className="system-tag">System</span>}{thread.lastMessage}</span>
                  </span>
                  {thread.unreadCount > 0 && <span className="message-unread" aria-label={`${thread.unreadCount} unread messages`}>{thread.unreadCount}</span>}
                </button>
              )) : <p className="muted small message-inbox-state">{threads.length ? 'No conversations match this filter.' : 'Your request and engagement conversations will appear here.'}</p>}
            {!loading && threadsCursor && <button className="message-load-more-threads" onClick={() => void loadMoreThreads()} disabled={loadingMoreThreads}>{loadingMoreThreads ? 'Loading…' : 'Load more conversations'}</button>}
          </div>
        </aside>

        <section className="card message-conversation" aria-label="Conversation thread">
          {selected ? <>
            <header className="message-conversation-head">
              <span className="message-avatar large">
                {selected.photoUrl ? <img src={selected.photoUrl} alt="" /> : initials(selected.counterpartName)}
              </span>
              <div className="message-participant">
                <h2>{selected.counterpartName}</h2>
                <p>{selected.headline || (selected.contextType === 'CONTRACT' ? 'Engagement conversation' : 'Request conversation')}</p>
              </div>
              <span className={`message-status ${selected.locked ? 'locked' : 'open'}`}>{selected.locked ? 'Read-only' : 'On Zoikorum'}</span>
            </header>
            <div className="message-context-strip">
              <span><strong>{selected.contextType === 'CONTRACT' ? 'Engagement' : selected.contextType === 'DISPUTE' ? 'Dispute' : 'Request'}</strong> · {selected.title}</span>
              {targetUrl && <Link to={targetUrl}>View details <span aria-hidden>→</span></Link>}
            </div>
            <div className="message-history" aria-live="polite">
              <div className="message-tabs" role="tablist" aria-label="Conversation sections">{(['Messages', 'Files', 'Audit Trail'] as const).map(section => <button key={section} role="tab" aria-selected={conversationTab === section} className={conversationTab === section ? 'active' : ''} onClick={() => setConversationTab(section)}>{section}</button>)}</div>
              {earlierCursor && <button className="message-load-earlier" onClick={() => void loadEarlier()} disabled={loadingEarlier}>{loadingEarlier ? 'Loading…' : 'Load earlier messages'}</button>}
              {conversationTab === 'Files' && <><h3>Shared files</h3>{sharedFiles.map(attachment => <button key={attachment.id} className="message-file" onClick={() => void downloadFile(selected.id, attachment.id, attachment.name)}><Icon name="folder" /><span><strong>{attachment.name}</strong><small>{Math.ceil(attachment.size / 1024)} KB · v{attachment.fileVersion}</small></span><Icon name="download" /></button>)}{!sharedFiles.length && <p className="muted small">No files in the loaded conversation history.</p>}</>}
              {conversationTab === 'Audit Trail' && <><h3>Conversation record</h3><p className="muted small">Messages are immutable. Each message and file carries a server-generated content fingerprint. Load earlier messages to include older records.</p>{messages.map(message => <details key={message.id}><summary>#{message.sequence} · {message.senderName} · {timeLabel(message.sentAt)}</summary><p className="small">ID: {message.id}</p><p className="small" style={{ overflowWrap: 'anywhere' }}>SHA-256: {message.contentHash}</p>{message.attachments.map(file => <p key={file.id} className="small" style={{ overflowWrap: 'anywhere' }}>{file.name} v{file.fileVersion}: {file.sha256}</p>)}</details>)}</>}
              {conversationTab === 'Messages' && (messages.length ? messages.map((message) => {
                const own = message.senderIdentityId === user?.id
                const system = message.senderIdentityId === null
                return (
                  <article key={message.id} className={`message-bubble-row ${system ? 'system' : own ? 'own' : ''}`}>
                    {!own && <span className="message-avatar small">{system ? 'Z' : initials(message.senderName)}</span>}
                    <div className="message-bubble">
                      {!system && <strong>{own ? 'You' : message.senderName}</strong>}
                      {system && <strong>Zoikorum system</strong>}
                      {message.body && <p>{message.body}</p>}
                      {message.attachments.map((attachment) => (
                        <button key={attachment.id} className="message-file" onClick={() => void downloadFile(selected.id, attachment.id, attachment.name)}>
                          <span aria-hidden>↧</span><span><strong>{attachment.name}</strong><small>{(attachment.size / 1024).toFixed(0)} KB · v{attachment.fileVersion}</small></span>
                        </button>
                      ))}
                      <time>{timeLabel(message.sentAt)}</time>
                    </div>
                    {own && <span className="message-avatar small own-avatar">{initials(user?.displayName || 'You')}</span>}
                  </article>
                )
              }) : <div className="message-history-empty"><Icon name="message" /><p>No messages yet. Start the conversation.</p></div>)}
            </div>
            <form className="message-composer" onSubmit={(event) => void sendMessage(event)}>
              {selected.locked ? <div className="message-read-only"><Icon name="shield" /><span>{selected.lockReason || 'Messaging is paused while this conversation is read-only.'} Use the dispute workspace for dispute communication.</span></div> : <>
                {queuedFiles.length > 0 && <div className="message-queued-files">{queuedFiles.map((file, index) => (
                  <span key={`${file.name}-${index}`}>{file.name}<button type="button" aria-label={`Remove ${file.name}`} onClick={() => setQueuedFiles((current) => current.filter((_, i) => i !== index))}>×</button></span>
                ))}</div>}
                <div className="message-compose-row">
                  <button type="button" className="message-attach" aria-label="Attach files" disabled={queuedFiles.length >= 5 || sending} onClick={() => fileInput.current?.click()}>＋</button>
                  <input ref={fileInput} type="file" accept={ACCEPTED_FILE_TYPES} multiple hidden onChange={queueFiles} />
                  <textarea aria-label="Write a message" placeholder="Write a message…" value={draft} maxLength={5000} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() }
                  }} />
                  <button type="submit" className="btn btn-primary message-send" disabled={sending || (!draft.trim() && queuedFiles.length === 0)} aria-label="Send message">{sending ? 'Sending…' : 'Send'}</button>
                </div>
                <div className="message-compose-hint">Messages and files are retained in the conversation record. Files up to 10 MB.</div>
              </>}
            </form>
          </> : <div className="message-no-selection">
            <Icon name="message" />
            <h2>{loading ? 'Loading your inbox' : 'No conversation selected'}</h2>
            <p>{threads.length ? 'Choose a conversation to view its messages.' : 'Start from a request or engagement to keep the conversation connected to its work.'}</p>
            {!threads.length && <Link className="btn btn-primary" to={professional ? '/app/professional/requests' : '/app/requests'}>{professional ? 'Your requests' : 'Your requests'}</Link>}
          </div>}
        </section>

        <aside className="card message-details">
          {selected ? <>
            <div className="message-details-person">
              <span className="message-avatar profile">{selected.photoUrl ? <img src={selected.photoUrl} alt="" /> : initials(selected.counterpartName)}</span>
              <h2>{selected.counterpartName}</h2>
              <p>{selected.headline || 'Zoikorum member'}{selected.country ? ` · ${selected.country}` : ''}</p>
            </div>
            <div className="message-detail-group">
              <h3>Conversation context</h3>
              <dl className="facts">
                <dt>Type</dt><dd>{selected.contextType === 'CONTRACT' ? 'Engagement' : selected.contextType === 'DISPUTE' ? 'Dispute' : 'Request'}</dd>
                <dt>Status</dt><dd>{selected.locked ? 'Read-only' : 'Open'}</dd>
              </dl>
              {targetUrl && <Link className="message-detail-link" to={targetUrl}>Open {selected.contextType === 'CONTRACT' ? 'engagement' : 'request'} details <span aria-hidden>→</span></Link>}
            </div>
            <div className="message-detail-group">
              <h3>Quick actions</h3>
              <button className="btn btn-ghost btn-sm" disabled={!selected.canSend || sending} onClick={() => fileInput.current?.click()}><Icon name="folder" /> Share file</button>
              {selected.viewerRole === 'BUYER' && <p><Link className="message-detail-link" to={`/professionals/${selected.professionalId}`}>View professional profile ↗</Link></p>}
            </div>
            <div className="message-detail-group">
              <h3>Shared files</h3>
              {messages.flatMap((message) => message.attachments.map((attachment) => ({ attachment, sequence: message.sequence }))).length ? (
                <ul className="message-shared-files">
                  {messages.flatMap((message) => message.attachments.map((attachment) => ({ attachment, sequence: message.sequence }))).map(({ attachment, sequence }) => (
                    <li key={`${sequence}-${attachment.id}`}><button onClick={() => void downloadFile(selected.id, attachment.id, attachment.name)}><span aria-hidden>↧</span><span>{attachment.name}<small>Version {attachment.fileVersion}</small></span></button></li>
                  ))}
                </ul>
              ) : <p className="muted small">Files shared in this conversation will appear here.</p>}
            </div>
            <div className="message-safety"><Icon name="shield" /><p>During an active dispute, direct messages are read-only. Keep dispute responses in the structured dispute workspace.</p></div>
            <div className="message-detail-group"><h3>Conversation details</h3><dl className="facts"><dt>Created</dt><dd>{new Date(selected.createdAt).toLocaleString()}</dd><dt>Thread ID</dt><dd style={{ overflowWrap: 'anywhere' }}>{selected.id}</dd></dl></div>
          </> : <div className="message-details-empty"><h2>Conversation details</h2><p className="muted small">Select a conversation to see its context and shared files.</p></div>}
        </aside>
      </section>

      {showStart && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowStart(false) }}>
        <section className="modal message-start-modal" role="dialog" aria-modal="true" aria-labelledby="message-start-title">
          <header className="modal-head"><div><h2 id="message-start-title">Start a conversation</h2><p className="muted small">Choose a request or engagement to keep messages in context.</p></div><button className="icon-btn" aria-label="Close" onClick={() => setShowStart(false)}>×</button></header>
          {loadingOptions ? <p className="muted">Loading your requests and engagements…</p> : startOptions.length ? <div className="message-start-list">
            {startOptions.map((option) => <button key={option.key} onClick={() => void openConversation(option)}>
              <span className="message-avatar small">{initials(option.counterpart)}</span>
              <span><strong>{option.counterpart}</strong><small>{option.contextType === 'CONTRACT' ? 'Engagement' : 'Request'} · {option.title}</small></span>
              <span aria-hidden>→</span>
            </button>)}
          </div> : <p className="muted">No conversations to start. Create a request or open an engagement first.</p>}
        </section>
      </div>}
    </>
  )
}
