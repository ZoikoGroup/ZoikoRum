import { useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react'
import {
  contractApi, deliveredFileUrl, draftFileUrl, LINK_PROVIDER,
  type Contract, type ContractMilestone, type Evidence, type Submission, type SubmissionDraft, type Verdict,
} from '../api/contracts'
import { DOC_ACCEPT, toUpload, type StoredFile } from '../api/files'
import { formatMoney } from '../api/orgs'
import { Icon, type IconName } from './dashboard'
import { FileLink, FileLinks } from './FileLink'
import { ErrorAlert, useDialog } from './ui'

/* Delivering milestone work deliverable by deliverable. The professional drops files or pastes links under each
   deliverable (saved as they go, private until sent), sees what still blocks sending, reviews a summary and sends. The
   buyer sees the same list next to the agreed criteria and marks each item "Looks good" or "Needs changes"; all good
   accepts and releases the payment, anything else goes back with one comment per item. */

/* ---- Small shared pieces ------------------------------------------------------------------------------------------ */

const REPO_NAMES: Record<string, string> = { 'github.com': 'GitHub', 'gitlab.com': 'GitLab', 'bitbucket.org': 'Bitbucket' }
const REPO_HOSTS = Object.keys(REPO_NAMES)
const DOC_HOSTS: [string, string][] = [['docs.google.com', 'Google Docs'], ['drive.google.com', 'Google Drive'], ['notion.so', 'Notion'],
  ['notion.site', 'Notion'], ['figma.com', 'Figma'], ['sharepoint.com', 'Microsoft 365'], ['onedrive.live.com', 'Microsoft 365'],
  ['1drv.ms', 'Microsoft 365'], ['dropbox.com', 'Dropbox'], ['airtable.com', 'Airtable']]
const GOOGLE: Record<string, string> = { document: 'Google Doc', spreadsheets: 'Google Sheet', presentation: 'Google Slides', forms: 'Google Form' }
const matches = (host: string, suffix: string) => host === suffix || host.endsWith(`.${suffix}`)

type LinkGuess = { ok: true; label: string; kind: 'DOCUMENT' | 'REPOSITORY' | 'WEBSITE' } | { ok: false; error: string }

/** What a pasted address will be recognised as, before it is added (the server applies the same rules). */
function guessLink(raw: string): LinkGuess | null {
  const text = raw.trim()
  if (!text) return null
  let url: URL
  try { url = new URL(text) } catch { return { ok: false, error: 'Paste a full link starting with https://' } }
  const host = url.hostname.toLowerCase()
  if (url.protocol !== 'https:') return { ok: false, error: 'Only secure links (https://) can be shared' }
  if (url.username || url.password) return { ok: false, error: 'Remove the username or password from the link' }
  if (!host.includes('.') || host === 'localhost' || /^[\d.]+$/.test(host) || host.startsWith('[')) {
    return { ok: false, error: 'This address only works on your network. Share one the buyer can open.' }
  }
  const repo = REPO_HOSTS.find((h) => matches(host, h))
  if (repo) return { ok: true, label: `${REPO_NAMES[repo]} repository`, kind: 'REPOSITORY' }
  const doc = DOC_HOSTS.find(([h]) => matches(host, h))
  if (doc) {
    const google = host === 'docs.google.com' ? GOOGLE[url.pathname.split('/')[1] ?? ''] : undefined
    return { ok: true, label: google ?? doc[1], kind: 'DOCUMENT' }
  }
  return { ok: true, label: `Website · ${host}`, kind: 'WEBSITE' }
}

const KIND_ICON: Record<string, IconName> = { DOCUMENT: 'request', REPOSITORY: 'folder', WEBSITE: 'globe' }
const fmtSize = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

function savedLabel(at: string | null, now: number): string {
  if (!at) return 'Changes save automatically'
  const s = Math.max(0, Math.round((now - new Date(at).getTime()) / 1000))
  return s < 45 ? 'Saved just now' : s < 3600 ? `Saved ${Math.round(s / 60)} min ago` : `Saved ${new Date(at).toLocaleString()}`
}

/** One piece of evidence: a file opens in the in-app viewer, a link opens in a new tab. */
export function EvidenceLink({ e, fileUrl }: { e: Evidence; fileUrl: (sha256: string) => string }) {
  if (e.type === 'FILE' && e.file) return <FileLink file={e.file} url={fileUrl(e.file.sha256)} />
  const name = e.label || `${LINK_PROVIDER[e.provider ?? 'WEBSITE'] ?? 'Link'} · ${e.host}`
  return <a className="file-link" href={e.url ?? undefined} target="_blank" rel="noopener noreferrer nofollow" title={e.url ?? undefined}>{name} ↗</a>
}

function EvidenceChip({ e, fileUrl, onRemove, busy }: { e: Evidence; fileUrl: (sha: string) => string; onRemove?: () => void; busy?: boolean }) {
  const meta = e.type === 'FILE' ? (e.file ? fmtSize(e.file.size) : '') : LINK_PROVIDER[e.provider ?? 'WEBSITE'] ?? 'Link'
  return (
    <li className="evidence-chip">
      <span className="evidence-icon"><Icon name={e.type === 'FILE' ? 'request' : KIND_ICON[e.kind ?? 'WEBSITE']} /></span>
      <span className="evidence-main"><EvidenceLink e={e} fileUrl={fileUrl} />
        {e.type === 'LINK' && e.url && <span className="evidence-url">{e.url}</span>}
        <span className="muted small">{meta}{e.version && ` · version ${e.version}`}</span></span>
      {e.type === 'LINK' && e.url && <button type="button" className="btn btn-ghost btn-sm" title="Copy the address"
        onClick={() => { void navigator.clipboard?.writeText(e.url!) }}>Copy</button>}
      {onRemove && <button type="button" className="icon-btn evidence-remove" aria-label="Remove" title="Remove" disabled={busy} onClick={onRemove}>
        <Icon name="trash" /></button>}
    </li>
  )
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useDialog(onClose)
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className="card modal delivery-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head"><h2 style={{ margin: 0 }}>{title}</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>×</button></div>
        {children}
      </div>
    </div>
  )
}

/** Deliverables a milestone covers, from the contract (one item for the whole milestone when it lists none). */
function deliverablesOf(c: Contract, m: ContractMilestone) {
  const found = m.deliverableKeys.flatMap((k) => c.terms.deliverables.filter((d) => d.key === k))
    .map((d) => ({ key: d.key, title: d.title, acceptanceCriteria: d.acceptanceCriteria }))
  return found.length ? found : [{ key: '_milestone', title: m.title, acceptanceCriteria: m.description }]
}

/* ---- Professional: prepare and send ------------------------------------------------------------------------------- */

type Upload = { id: string; name: string; error?: string }

export function DeliveryForm({ m, onSent }: { m: ContractMilestone; onSent: (c: Contract) => void }) {
  const [draft, setDraft] = useState<SubmissionDraft | null>(null)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [links, setLinks] = useState<Record<string, { url: string; version: string }>>({})
  const [uploads, setUploads] = useState<Record<string, Upload[]>>({})
  const [open, setOpen] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const [saving, setSaving] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [reviewing, setReviewing] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const seq = useRef(0)
  const timers = useRef<Record<string, number>>({})

  useEffect(() => {
    contractApi.draft(m.id).then((d) => {
      setDraft(d); setMessage(d.note); setNotes(Object.fromEntries(d.items.map((i) => [i.deliverableKey, i.note])))
      setOpen((d.items.find((i) => !i.ready || i.changesRequested) ?? d.items[0])?.deliverableKey ?? null)
    }).catch(setError)
    const tick = window.setInterval(() => setNow(Date.now()), 30_000)
    const pending = timers.current
    return () => { window.clearInterval(tick); Object.values(pending).forEach((t) => window.clearTimeout(t)) }
  }, [m.id])

  /** Runs a change; only the newest answer is shown, so a slow save never overwrites a newer state. */
  const apply = async (fn: () => Promise<SubmissionDraft>, blocking = true) => {
    const mine = ++seq.current
    if (blocking) setBusy(true)
    setSaving((n) => n + 1); setError(null)
    try { const d = await fn(); if (mine === seq.current) setDraft(d); return d }
    catch (err) { setError(err); return null }
    finally { setSaving((n) => n - 1); if (blocking) setBusy(false) }
  }
  if (!draft) return error ? <ErrorAlert error={error} /> : <div className="delivery"><p className="muted small">Loading your delivery…</p></div>

  const autosave = (field: string, value: string) => {
    window.clearTimeout(timers.current[field])
    timers.current[field] = window.setTimeout(() => {
      void apply(() => contractApi.saveDraft(m.id, field === '' ? { note: value } : { itemNotes: { [field]: value } }), false)
    }, 700)
  }
  const addFiles = async (key: string, picked: File[]) => {
    for (const f of picked.slice(0, 10)) {
      const id = crypto.randomUUID()
      setUploads((u) => ({ ...u, [key]: [...(u[key] ?? []), { id, name: f.name }] }))
      const fail = (error: string) => setUploads((u) => ({ ...u, [key]: (u[key] ?? []).map((x) => x.id === id ? { ...x, error } : x) }))
      try {
        const file = await toUpload(f)
        if (await apply(() => contractApi.addEvidence(m.id, key, { file }))) {
          setUploads((u) => ({ ...u, [key]: (u[key] ?? []).filter((x) => x.id !== id) }))
        } else fail('Upload failed. Try again.')
      } catch (err) {
        fail(err instanceof Error ? err.message : 'Could not read this file')
      }
    }
  }
  /** Adds the link typed for a deliverable. A pasted link is never left behind: this runs on paste, when the box loses
      focus (unless a commit can still be typed) and before sending. */
  const addLink = async (key: string, url = links[key]?.url ?? '', version = links[key]?.version ?? '') => {
    if (!guessLink(url)?.ok) return false
    const d = await apply(() => contractApi.addEvidence(m.id, key, { url: url.trim(), ...(version.trim() ? { version: version.trim() } : {}) }))
    if (d) setLinks((l) => ({ ...l, [key]: { url: '', version: '' } }))
    return !!d
  }
  const reviewAndSend = async () => {
    const typed = Object.entries(links).filter(([, l]) => l.url.trim())
    const bad = typed.find(([, l]) => !guessLink(l.url)?.ok)
    if (bad) { jump(bad[0]); setError(new Error('One of the links you typed is not valid. Fix it or clear the box, then send.')); return }
    for (const [key] of typed) if (!(await addLink(key))) return
    setReviewing(true)
  }
  const jump = (key: string | null) => {
    if (!key) return
    setOpen(key)
    window.setTimeout(() => document.getElementById(`dl-${m.id}-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50)
  }

  const ready = draft.items.filter((i) => i.ready).length
  const total = draft.items.length
  const allReady = ready === total
  const issues = [...draft.blockers.map((b) => ({ ...b, blocking: true })), ...draft.warnings.map((w) => ({ ...w, blocking: false }))]
  const step = !allReady ? 0 : draft.blockers.length ? 1 : 2

  return (
    <div className="delivery">
      <div className="delivery-top">
        <div>
          <h3 style={{ margin: 0 }}>{draft.revisionNumber ? `Revised delivery · revision ${draft.revisionNumber}` : 'Deliver your work'}</h3>
          <p className="muted small" style={{ margin: '2px 0 0' }}>Private until you send it. The buyer reviews each deliverable against the agreed criteria.</p>
        </div>
        <span className={`save-state ${saving ? 'saving' : ''}`} aria-live="polite">{saving ? 'Saving…' : savedLabel(draft.savedAt, now)}</span>
      </div>

      <ol className="delivery-steps" aria-label="Progress">
        {['Add your work', 'Check', 'Send'].map((label, i) => (
          <li key={label} className={i < step ? 'done' : i === step ? 'current' : ''}><span className="n">{i < step ? '✓' : i + 1}</span>{label}</li>
        ))}
      </ol>
      <div className="bar big" title={`${ready} of ${total} deliverables ready`}><span style={{ width: `${total ? (ready / total) * 100 : 0}%` }} /></div>

      {draft.items.map((it, index) => {
        const key = it.deliverableKey
        const isOpen = open === key
        const link = links[key] ?? { url: '', version: '' }
        const guess = guessLink(link.url)
        const hints = draft.warnings.filter((w) => w.deliverableKey === key)
        const pending = uploads[key] ?? []
        const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(null); void addFiles(key, Array.from(e.dataTransfer.files)) }
        return (
          <section key={key} id={`dl-${m.id}-${key}`} className={`delivery-item ${it.ready ? 'ready' : ''} ${isOpen ? 'open' : ''} ${it.changesRequested ? 'asked' : ''}`}>
            <button type="button" className="delivery-item-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : key)}>
              <span className={`step-dot ${it.ready ? 'ok' : ''}`}>{it.ready ? '✓' : index + 1}</span>
              <span className="delivery-item-title"><strong>{it.title}</strong>
                <span className="muted small">{it.evidence.length ? `${it.evidence.length} item${it.evidence.length > 1 ? 's' : ''}` : 'Nothing added yet'}
                  {it.changesRequested && ' · changes requested'}{hints.length > 0 && ` · ${hints.length} hint${hints.length > 1 ? 's' : ''}`}</span></span>
              <span className={`badge ${it.ready ? 'green' : it.changesRequested ? 'warn' : ''}`}>{it.ready ? 'Ready' : 'Needs a file or link'}</span>
              <span className={`chevron ${isOpen ? 'up' : ''}`} aria-hidden>⌄</span>
            </button>

            {isOpen && <div className="delivery-item-body">
              {it.changesRequested && <div className="tip"><Icon name="message" /><span><strong>The buyer asked:</strong> {it.changesRequested}</span></div>}
              {it.acceptanceCriteria && <div className="criteria-box"><Icon name="check" /><span><strong>The buyer will check:</strong> {it.acceptanceCriteria}</span></div>}

              {(it.evidence.length > 0 || pending.length > 0) && <ul className="evidence-list">
                {it.evidence.map((e) => <EvidenceChip key={e.id} e={e} busy={busy} fileUrl={(sha) => draftFileUrl(m.id, sha)}
                  onRemove={() => { void apply(() => contractApi.removeEvidence(m.id, key, e.id)) }} />)}
                {pending.map((u) => <li key={u.id} className={`evidence-chip ${u.error ? 'failed' : 'uploading'}`}>
                  <span className="evidence-icon">{u.error ? '!' : <span className="spinner" aria-hidden />}</span>
                  <span className="evidence-main"><span>{u.name}</span><span className="small">{u.error ?? 'Uploading…'}</span></span>
                  {u.error && <button type="button" className="icon-btn evidence-remove" aria-label="Dismiss"
                    onClick={() => setUploads((x) => ({ ...x, [key]: (x[key] ?? []).filter((y) => y.id !== u.id) }))}>×</button>}
                </li>)}
              </ul>}

              <label className={`drop-zone ${over === key ? 'over' : ''}`} onDragOver={(e) => { e.preventDefault(); setOver(key) }}
                onDragLeave={() => setOver(null)} onDrop={onDrop}>
                <input type="file" multiple hidden accept={DOC_ACCEPT} disabled={busy} onChange={(e) => {
                  const picked = Array.from(e.target.files ?? []); e.target.value = ''; void addFiles(key, picked)
                }} />
                <Icon name="download" />
                <span><strong>Drop files here</strong> or <span className="link-like">browse</span>
                  <span className="muted small"> · PDF, Word, Excel, CSV, JPG, PNG up to 10 MB</span></span>
              </label>

              <div className="link-row">
                <input className="input" type="url" placeholder="…or paste a link: website, Google Sheet, Notion, GitHub" value={link.url}
                  aria-label={`Link for ${it.title}`}
                  onChange={(e) => setLinks({ ...links, [key]: { ...link, url: e.target.value } })}
                  onPaste={(e) => {
                    const pasted = e.clipboardData.getData('text').trim()
                    const g = guessLink(pasted)
                    if (g?.ok && g.kind !== 'REPOSITORY' && !link.url.trim()) { e.preventDefault(); void addLink(key, pasted, '') }
                  }}
                  onBlur={() => { if (guess?.ok && guess.kind !== 'REPOSITORY') void addLink(key) }}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void addLink(key) } }} />
                {guess?.ok && guess.kind === 'REPOSITORY' && <input className="input version" placeholder="e.g. a1b2c3d or v1.0" value={link.version}
                  aria-label="Commit or tag" onChange={(e) => setLinks({ ...links, [key]: { ...link, version: e.target.value } })} />}
                <button type="button" className="btn btn-secondary btn-sm" disabled={busy || !guess?.ok} onClick={() => { void addLink(key) }}>Add link</button>
              </div>
              {guess && <p className={`small link-guess ${guess.ok ? 'ok' : 'bad'}`}>{guess.ok
                ? <>✓ Recognised as <strong>{guess.label}</strong>{guess.kind === 'DOCUMENT' && ' · make sure the buyer can open it'}
                  {guess.kind === 'REPOSITORY' && !link.version.trim() && <> · optional: add the commit ID or tag you delivered
                    (GitHub → Commits, copy the short ID) so later changes don't alter what the buyer reviews. Private repository?
                    Give the buyer access too.</>}</>
                : guess.error}</p>}

              <label className="filter-box" style={{ marginTop: 10 }}><span>What should the buyer look at? <span className="muted">(optional)</span></span>
                <textarea rows={2} maxLength={2000} value={notes[key] ?? ''} placeholder="e.g. The summary is on page 2; the model is in the 'Output' tab"
                  onChange={(e) => { setNotes({ ...notes, [key]: e.target.value }); autosave(key, e.target.value) }} /></label>
              {hints.map((w) => <p key={w.code + w.message} className="small hint-warn">⚠ {w.message}</p>)}

              {index < total - 1 && <div className="row" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => jump(draft.items[index + 1].deliverableKey)}>Next: {draft.items[index + 1].title} →</button></div>}
            </div>}
          </section>
        )
      })}

      <label className="filter-box" style={{ marginTop: 4 }}><span>Message to the buyer <span className="muted">(optional)</span></span>
        <textarea rows={2} maxLength={2000} value={message} placeholder="Anything they should know about this delivery"
          onChange={(e) => { setMessage(e.target.value); autosave('', e.target.value) }} /></label>

      {issues.length > 0 && <div className="delivery-issues">
        <strong className="small">Before you send</strong>
        <ul>{issues.map((i) => <li key={i.code + (i.deliverableKey ?? '') + i.message} className={i.blocking ? 'block' : 'warn'}>
          <span aria-hidden>{i.blocking ? '●' : '⚠'}</span>
          {i.deliverableKey ? <button type="button" className="link-like" onClick={() => jump(i.deliverableKey)}>{i.message}</button> : <span>{i.message}</span>}
        </li>)}</ul>
      </div>}
      <ErrorAlert error={error} />

      <div className="delivery-send">
        <span className="small"><strong>{ready} of {total}</strong> deliverable{total > 1 ? 's' : ''} ready
          {draft.blockers.length > 0 && <span className="muted"> · {draft.blockers.length} thing{draft.blockers.length > 1 ? 's' : ''} to fix</span>}</span>
        <span className="row" style={{ flexWrap: 'nowrap' }}>
          {draft.savedAt && <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
            onClick={() => { if (confirm('Discard this delivery? Files and links you added here are removed from it.')) void apply(() => contractApi.discardDraft(m.id)) }}>Discard</button>}
          <button type="button" className="btn btn-primary"
            disabled={busy || saving > 0 || (!draft.canSubmit && !Object.values(links).some((l) => guessLink(l.url)?.ok))}
            title={draft.canSubmit ? undefined : 'Add a file or link to every deliverable first'} onClick={() => { void reviewAndSend() }}>Review &amp; send</button>
        </span>
      </div>

      {reviewing && <SendDialog m={m} draft={draft} onClose={() => setReviewing(false)} onSent={onSent} />}
    </div>
  )
}

function SendDialog({ m, draft, onClose, onSent }: { m: ContractMilestone; draft: SubmissionDraft; onClose: () => void; onSent: (c: Contract) => void }) {
  const [confirmed, setConfirmed] = useState(false)
  const [lateReason, setLateReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const late = draft.warnings.some((w) => w.code === 'LATE')
  const send = async () => {
    setBusy(true); setError(null)
    try { onSent(await contractApi.sendDraft(m.id, lateReason.trim() || undefined)) } catch (err) { setError(err); setBusy(false) }
  }
  return (
    <Modal title={`Send M${m.sequence} to the buyer`} onClose={onClose}>
      <p className="muted small" style={{ marginTop: 0 }}>{formatMoney(m.amount)} · the buyer gets a review window and is notified straight away.</p>
      <ul className="send-summary">{draft.items.map((i) => (
        <li key={i.deliverableKey}><span className="ok-text">✓</span><span><strong>{i.title}</strong>
          <span className="muted small"> · {i.evidence.map((e) => e.type === 'FILE' ? e.file?.name : (LINK_PROVIDER[e.provider ?? 'WEBSITE'] ?? 'Link')).join(', ')}</span></span></li>))}</ul>
      {draft.warnings.filter((w) => w.code !== 'LATE').length > 0 && <p className="small hint-warn">
        ⚠ {draft.warnings.filter((w) => w.code !== 'LATE').length} hint(s) not addressed. You can still send.</p>}
      {late && <label className="filter-box"><span>This is after the due date. Tell the buyer why</span>
        <input className="input" maxLength={500} value={lateReason} onChange={(e) => setLateReason(e.target.value)} /></label>}
      <label className="checkbox" style={{ margin: '12px 0' }}><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        <span className="small">{draft.declaration}</span></label>
      <ErrorAlert error={error} />
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button type="button" className="btn btn-ghost" onClick={onClose}>Keep editing</button>
        <button type="button" className="btn btn-primary" disabled={busy || !confirmed || (late && !lateReason.trim())} onClick={() => { void send() }}>
          {busy ? 'Sending…' : 'Send to buyer'}</button>
      </div>
    </Modal>
  )
}

/* ---- What was delivered (both sides) ------------------------------------------------------------------------------ */

export function SubmissionView({ s, c }: { s: Submission; c: Contract }) {
  const verdicts = Object.fromEntries((s.review?.verdicts ?? []).map((v) => [v.deliverableKey, v]))
  const fileUrl = (sha: string) => deliveredFileUrl(c.id, sha)
  return (
    <div className="submission">
      <div className="submission-head">
        <span className="badge">{s.revisionNumber ? `Revision ${s.revisionNumber}` : 'First delivery'}</span>
        <span className="muted small">{new Date(s.submittedAt).toLocaleString()}{s.declaredAt && ' · confirmed against the criteria'}</span>
        {s.review && <span className={`badge ${s.review.outcome === 'ACCEPTED' ? 'green' : 'warn'}`}>{s.review.outcome === 'ACCEPTED' ? 'Accepted' : 'Changes requested'}</span>}
      </div>
      {s.lateReason && <p className="small" style={{ margin: '6px 0 0' }}><strong>Late:</strong> {s.lateReason}</p>}
      {s.note && <p className="submission-note">{s.note}</p>}
      {s.items.length === 0 ? <>{!s.note && <em className="muted small">No note</em>}
        {s.files.length > 0 && <FileLinks files={s.files} url={(f: StoredFile) => fileUrl(f.sha256)} />}</>
        : <ul className="evidence-items">{s.items.map((i) => {
          const v = verdicts[i.deliverableKey]
          return <li key={i.deliverableKey} className={v ? (v.verdict === 'MET' ? 'met' : 'changes') : ''}>
            <div className="delivery-item-title-row"><strong>{i.title}</strong>
              {s.revisionNumber > 0 && <span className={`badge ${i.carriedOver ? '' : 'green'}`}>{i.carriedOver ? 'Unchanged' : 'Updated'}</span>}
              {v && <span className={`badge ${v.verdict === 'MET' ? 'green' : 'warn'}`}>{v.verdict === 'MET' ? '👍 Looks good' : '👎 Needs changes'}</span>}</div>
            <ul className="evidence-list compact">{i.evidence.map((e) => <EvidenceChip key={e.id} e={e} fileUrl={fileUrl} />)}</ul>
            {i.note && <p className="small quote">{i.note}</p>}
            {v?.comment && <p className="small hint-warn" style={{ margin: '4px 0 0' }}>Buyer: {v.comment}</p>}
          </li>
        })}</ul>}
    </div>
  )
}

/* ---- Buyer: review each deliverable ------------------------------------------------------------------------------- */

const QUICK = ['Something is missing', 'Does not meet the agreed criteria', 'Please explain', 'I cannot open the file or link']

export function ReviewPanel({ m, c, busy, onDecide, onPartial }: {
  m: ContractMilestone; c: Contract; busy: boolean
  onDecide: (verdicts: { deliverableKey: string; verdict: Verdict; comment: string }[]) => void; onPartial?: () => void
}) {
  const latest = m.submissions[0]
  const byKey = Object.fromEntries((latest?.items ?? []).map((i) => [i.deliverableKey, i]))
  const items = latest?.items.length
    ? latest.items.map((i) => ({ key: i.deliverableKey, title: i.title, acceptanceCriteria: i.acceptanceCriteria }))
    : deliverablesOf(c, m)
  const [picked, setPicked] = useState<Record<string, { verdict: Verdict; comment: string }>>({})
  const [confirming, setConfirming] = useState(false)
  const fileUrl = (sha: string) => deliveredFileUrl(c.id, sha)
  const changes = items.filter((i) => picked[i.key]?.verdict === 'CHANGES_REQUESTED')
  const missing = changes.filter((i) => (picked[i.key]?.comment ?? '').trim().length < 5)
  const reviewed = items.filter((i) => picked[i.key]).length
  const set = (key: string, verdict: Verdict) =>
    setPicked((p) => (p[key]?.verdict === verdict ? Object.fromEntries(Object.entries(p).filter(([k]) => k !== key)) : { ...p, [key]: { verdict, comment: p[key]?.comment ?? '' } }))
  const comment = (key: string, text: string) => setPicked((p) => ({ ...p, [key]: { verdict: 'CHANGES_REQUESTED', comment: text } }))
  const verdicts = () => items.map((i) => ({ deliverableKey: i.key, verdict: picked[i.key]?.verdict ?? 'MET' as Verdict, comment: (picked[i.key]?.comment ?? '').trim() }))

  return (
    <div className="review-panel">
      <div className="delivery-top">
        <div><h3 style={{ margin: 0 }}>Review {latest?.revisionNumber ? `revision ${latest.revisionNumber}` : 'the delivery'}</h3>
          <p className="muted small" style={{ margin: '2px 0 0' }}>{latest ? `Delivered ${new Date(latest.submittedAt).toLocaleString()}` : ''}
            {m.acceptanceDueAt && ` · review by ${new Date(m.acceptanceDueAt).toLocaleDateString()}`}</p></div>
        <span className="save-state">{reviewed} of {items.length} reviewed</span>
      </div>
      <div className="bar big"><span style={{ width: `${items.length ? (reviewed / items.length) * 100 : 0}%` }} /></div>
      {latest?.lateReason && <div className="tip" style={{ marginBottom: 8 }}><Icon name="clock" /><span><strong>Delivered late:</strong> {latest.lateReason}</span></div>}
      {latest?.note && <p className="submission-note">“{latest.note}”</p>}
      {latest && latest.items.length === 0 && latest.files.length > 0 && <p className="small"><FileLinks files={latest.files} url={(f: StoredFile) => fileUrl(f.sha256)} /></p>}

      {items.map((i, index) => {
        const p = picked[i.key]
        const item = byKey[i.key]
        return <section key={i.key} className={`review-item ${p?.verdict === 'MET' ? 'met' : p?.verdict === 'CHANGES_REQUESTED' ? 'changes' : ''}`}>
          <div className="review-item-head">
            <span className={`step-dot ${p?.verdict === 'MET' ? 'ok' : p ? 'warn' : ''}`}>{p?.verdict === 'MET' ? '✓' : p ? '!' : index + 1}</span>
            <span className="delivery-item-title"><strong>{i.title}</strong>
              {item && (latest?.revisionNumber ?? 0) > 0 && <span className={`badge ${item.carriedOver ? '' : 'green'}`} style={{ marginLeft: 6 }}>{item.carriedOver ? 'Unchanged' : 'Updated'}</span>}</span>
            <span className="seg" role="group" aria-label={`Verdict for ${i.title}`}>
              <button type="button" aria-pressed={p?.verdict === 'MET'} className={p?.verdict === 'MET' ? 'on good' : ''} onClick={() => set(i.key, 'MET')}>👍 Looks good</button>
              <button type="button" aria-pressed={p?.verdict === 'CHANGES_REQUESTED'} className={p?.verdict === 'CHANGES_REQUESTED' ? 'on bad' : ''} onClick={() => set(i.key, 'CHANGES_REQUESTED')}>👎 Needs changes</button>
            </span>
          </div>
          {i.acceptanceCriteria && <div className="criteria-box"><Icon name="check" /><span><strong>Agreed:</strong> {i.acceptanceCriteria}</span></div>}
          {item && item.evidence.length > 0 && <ul className="evidence-list compact">{item.evidence.map((e) => <EvidenceChip key={e.id} e={e} fileUrl={fileUrl} />)}</ul>}
          {item?.note && <p className="small quote">{item.note}</p>}
          {p?.verdict === 'CHANGES_REQUESTED' && <div className="change-request">
            <textarea rows={2} maxLength={1000} autoFocus value={p.comment} aria-label={`What needs to change in ${i.title}`}
              placeholder="What needs to change? Be specific, against the agreed criteria." onChange={(e) => comment(i.key, e.target.value)} />
            <div className="quick-chips">{QUICK.map((q) => <button key={q} type="button" className="chip pick"
              onClick={() => comment(i.key, p.comment.trim() ? `${p.comment.trim()} ${q}.` : `${q}.`)}>{q}</button>)}</div>
            {p.comment.trim().length < 5 && <p className="small hint-warn" style={{ margin: 0 }}>Add a short comment so the professional knows what to fix.</p>}
          </div>}
        </section>
      })}

      <div className="decision-bar">
        <span className="small">{changes.length
          ? <>Sending back <strong>{changes.length}</strong> item{changes.length > 1 ? 's' : ''}; items you did not mark count as good.</>
          : <>Accepting releases <strong>{formatMoney(m.amount)}</strong> from escrow to the professional.</>}</span>
        <span className="row" style={{ flexWrap: 'nowrap' }}>
          {reviewed < items.length && !changes.length && <button type="button" className="btn btn-ghost btn-sm"
            onClick={() => setPicked(Object.fromEntries(items.map((i) => [i.key, { verdict: 'MET' as Verdict, comment: '' }])))}>Mark all as good</button>}
          {onPartial && !m.partialOffer && <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={onPartial}>Accept for less…</button>}
          {changes.length
            ? <button type="button" className="btn btn-secondary" disabled={busy || missing.length > 0} onClick={() => onDecide(verdicts())}>
              Send back {changes.length} change request{changes.length > 1 ? 's' : ''}</button>
            : <button type="button" className="btn btn-primary" disabled={busy} onClick={() => setConfirming(true)}>Accept all &amp; release {formatMoney(m.amount)}</button>}
        </span>
      </div>

      {confirming && <Modal title={`Accept M${m.sequence}?`} onClose={() => setConfirming(false)}>
        <p style={{ marginTop: 0 }}>This releases <strong>{formatMoney(m.amount)}</strong> from escrow to the professional (minus the platform fee).
          It cannot be undone.</p>
        <ul className="send-summary">{items.map((i) => <li key={i.key}><span className="ok-text">✓</span><span>{i.title}</span></li>)}</ul>
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}>
          <button type="button" className="btn btn-ghost" onClick={() => setConfirming(false)}>Go back</button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => { setConfirming(false); onDecide(verdicts()) }}>Accept and release</button>
        </div>
      </Modal>}
    </div>
  )
}
