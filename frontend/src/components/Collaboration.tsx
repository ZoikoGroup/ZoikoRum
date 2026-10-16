import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { contractApi, type Contract, type EngagementTask } from '../api/contracts'
import { messagingApi, type Meeting } from '../api/messaging'
import { ErrorAlert, Loading } from './ui'

/* Working together inside an engagement: meetings in its conversation, and a shared task list. */

const pad = (n: number) => String(n).padStart(2, '0')
/** A datetime-local value for "tomorrow at 10:00" in the viewer's own time zone. */
function tomorrowAtTen(): string {
  const d = new Date(Date.now() + 86_400_000)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T10:00`
}

/** Meetings in the engagement's conversation: schedule one (own link or a generated video room), join or cancel. */
export function MeetingsPanel({ threadId, onChange }: { threadId: string; onChange?: () => void }) {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ title: '', startsAt: tomorrowAtTen(), duration: '30', link: '' })
  const load = useCallback(() => messagingApi.meetings(threadId).then(setMeetings).catch((e) => { setError(e); setMeetings([]) }), [threadId])
  useEffect(() => { load() }, [load])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      await messagingApi.scheduleMeeting(threadId, { title: form.title.trim(), startsAt: new Date(form.startsAt).toISOString(),
        durationMinutes: Number(form.duration), joinUrl: form.link.trim() || null })
      setOpen(false)
      setForm({ ...form, title: '', link: '' })
      await load()
      onChange?.()  // the conversation shows the new meeting message
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  const upcoming = (meetings ?? []).filter((m) => m.status === 'SCHEDULED')
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Meetings</h2>
        {!open && <button className="btn btn-secondary btn-sm" onClick={() => setOpen(true)}>Schedule a meeting</button>}</div>
      <ErrorAlert error={error} />
      {open && <form onSubmit={submit} className="stack" style={{ marginBottom: 12 }}>
        <div className="row">
          <label className="filter-box grow"><span>Title</span>
            <input required minLength={2} maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="e.g. Kick-off call" /></label>
          <label className="filter-box"><span>Starts</span>
            <input type="datetime-local" required value={form.startsAt} onChange={(e) => setForm({ ...form, startsAt: e.target.value })} /></label>
          <label className="filter-box"><span>Length</span>
            <select value={form.duration} onChange={(e) => setForm({ ...form, duration: e.target.value })}>
              {['15', '30', '45', '60', '90', '120'].map((m) => <option key={m} value={m}>{m} min</option>)}</select></label>
        </div>
        <label className="filter-box grow"><span>Your meeting link (optional)</span>
          <input type="url" maxLength={500} value={form.link} onChange={(e) => setForm({ ...form, link: e.target.value })}
            placeholder="Paste a Zoom, Teams or Google Meet link, or leave empty for a new video room" /></label>
        <div className="row">
          <button className="btn btn-primary btn-sm" disabled={busy}>Schedule</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>Cancel</button></div>
      </form>}
      {meetings === null ? <Loading lines={1} /> : upcoming.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No meetings scheduled.</p> : (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>{upcoming.map((m) => (
          <li key={m.id} className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
            <span><strong>{m.title}</strong><br /><span className="muted small">{new Date(m.startsAt).toLocaleString()} · {m.durationMinutes} min</span></span>
            <span className="row">
              <a className="btn btn-primary btn-sm" href={m.joinUrl} target="_blank" rel="noopener noreferrer">Join</a>
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => {
                if (confirm(`Cancel “${m.title}”? Both sides see it in the conversation.`)) messagingApi.cancelMeeting(m.id).then(load).then(() => onChange?.()).catch(setError)
              }}>Cancel</button></span>
          </li>))}</ul>
      )}
      <p className="muted small" style={{ margin: '8px 0 0' }}>Scheduled meetings are posted in the conversation and appear in your calendar feed (Settings).</p>
    </section>
  )
}

/** The engagement's shared task list: who does what by when. Not part of the signed terms. */
export function TasksPanel({ c, side, onError }: { c: Contract; side: 'buyer' | 'professional'; onError: (e: unknown) => void }) {
  const [tasks, setTasks] = useState<EngagementTask[] | null>(null)
  const [title, setTitle] = useState('')
  const [owner, setOwner] = useState<'BUYER' | 'PROFESSIONAL'>(side === 'buyer' ? 'BUYER' : 'PROFESSIONAL')
  const [due, setDue] = useState('')
  const [milestoneId, setMilestoneId] = useState('')
  const editable = ['PENDING_SIGNATURE', 'ACTIVE', 'DISPUTED'].includes(c.status)
  const load = useCallback(() => contractApi.tasks(c.id).then(setTasks).catch((e) => { onError(e); setTasks([]) }), [c.id, onError])
  useEffect(() => { load() }, [load])

  async function add(e: FormEvent) {
    e.preventDefault()
    try {
      await contractApi.addTask(c.id, { title: title.trim(), owner, dueDate: due || null, milestoneId: milestoneId || null })
      setTitle(''); setDue('')
      await load()
    } catch (err) { onError(err) }
  }

  const label = (o: string) => (o === 'BUYER' ? 'Buyer' : 'Professional')
  return (
    <section className="card panel">
      <h2 style={{ marginTop: 0 }}>Tasks</h2>
      <p className="muted small" style={{ marginTop: 0 }}>A shared checklist for both sides. Tasks organise the work; they do not change the agreement.</p>
      {editable && <form onSubmit={add} className="row" style={{ marginBottom: 12, alignItems: 'flex-end' }}>
        <label className="filter-box grow"><span>Task</span>
          <input required minLength={2} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Share last year's accounts" /></label>
        <label className="filter-box"><span>Who</span>
          <select value={owner} onChange={(e) => setOwner(e.target.value as 'BUYER' | 'PROFESSIONAL')}>
            <option value="BUYER">Buyer</option><option value="PROFESSIONAL">Professional</option></select></label>
        <label className="filter-box"><span>Due</span><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>
        <label className="filter-box"><span>Milestone</span>
          <select value={milestoneId} onChange={(e) => setMilestoneId(e.target.value)}><option value="">—</option>
            {c.milestones.map((m) => <option key={m.id} value={m.id}>M{m.sequence} {m.title}</option>)}</select></label>
        <button className="btn btn-primary btn-sm">Add</button>
      </form>}
      {tasks === null ? <Loading lines={2} /> : tasks.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No tasks yet.</p> : (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>{tasks.map((t) => (
          <li key={t.id} className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
            <label className="checkbox" style={{ flex: 1 }}>
              <input type="checkbox" checked={t.done} disabled={!editable}
                onChange={(e) => {  // ticked at once; the saved list replaces it (or the tick is undone if saving fails)
                  const done = e.target.checked
                  setTasks((list) => (list ?? []).map((x) => (x.id === t.id ? { ...x, done, overdue: done ? false : x.overdue } : x)))
                  contractApi.updateTask(t.id, { done }).then(load).catch((err) => { onError(err); load() })
                }} />
              <span style={t.done ? { textDecoration: 'line-through' } : undefined}>{t.title}
                <span className="muted small"> · {label(t.owner)}{t.dueDate ? ` · due ${new Date(`${t.dueDate}T00:00:00`).toLocaleDateString()}` : ''}
                  {t.milestoneId ? ` · M${c.milestones.find((m) => m.id === t.milestoneId)?.sequence ?? '?'}` : ''}</span>
                {t.overdue && <span className="badge red" style={{ marginLeft: 6 }}>Overdue</span>}</span>
            </label>
            {editable && <button className="btn btn-ghost btn-sm" aria-label={`Remove ${t.title}`}
              onClick={() => contractApi.removeTask(t.id).then(load).catch(onError)}>Remove</button>}
          </li>))}</ul>
      )}
    </section>
  )
}
