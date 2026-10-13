/** Weekly availability slider (Professional Dashboard s.13): hours a week open for Zoikorum work. Empty = not stated. */
export function HoursSlider({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  return (
    <div className="field">
      <label htmlFor="weekly-hours">Hours a week available for new work</label>
      <div className="row" style={{ alignItems: 'center', gap: 12 }}>
        <input id="weekly-hours" type="range" min={0} max={60} step={5} value={value ?? 0} style={{ flex: 1 }}
          aria-valuetext={value === null ? 'Not stated' : `${value} hours a week`} onChange={(e) => onChange(Number(e.target.value))} />
        <strong style={{ minWidth: 90 }}>{value === null ? 'Not stated' : value === 0 ? 'None' : `${value} h / week`}</strong>
        {value !== null && <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange(null)}>Clear</button>}
      </div>
      <span className="hint">Shown on your profile so buyers can plan; it does not limit how many requests you get.</span>
    </div>
  )
}
