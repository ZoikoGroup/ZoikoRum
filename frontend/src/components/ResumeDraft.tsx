/** "Resume where you left off?" prompt for an autosaved draft, plus the small "Draft saved" indicator. */
export function ResumeDraft({ savedAt, note, onResume, onDiscard }: { savedAt: string; note?: string; onResume: () => void; onDiscard: () => void }) {
  return (
    <div className="alert alert-info" role="status" style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ flex: 1 }}>You have an unfinished draft from {new Date(savedAt).toLocaleString()}.{note ? ` ${note}` : ''}</span>
      <button type="button" className="btn btn-primary btn-sm" onClick={onResume}>Resume draft</button>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onDiscard}>Start fresh</button>
    </div>
  )
}

export function DraftSaved({ at }: { at: string | null }) {
  return at ? <span className="muted small" aria-live="polite">Draft saved {new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span> : null
}
