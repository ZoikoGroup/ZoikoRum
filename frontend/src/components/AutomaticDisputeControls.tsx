interface Props { settings: string; onChange: (value: string) => void; disabled: boolean }

export default function AutomaticDisputeControls({ settings, onChange, disabled }: Props) {
  let parsed: Record<string, unknown>
  try { parsed = JSON.parse(settings); if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return null } catch { return null }
  function change(key: string, value: unknown) { onChange(JSON.stringify({ ...parsed, [key]: value }, null, 2)) }
  const repeated = typeof parsed.autoDisputeRejectionCount === 'number'
  return <fieldset disabled={disabled} className="panel"><legend>Automatic dispute intake</legend>
    <p className="muted">These controls apply to the policy version agreed for each engagement. Intake freezes eligible funded work for human review.</p>
    <label><input type="checkbox" checked={parsed.autoDisputeMissedDeadline === true} onChange={e => change('autoDisputeMissedDeadline', e.target.checked)} /> Open a case when a funded milestone misses its deadline</label><br />
    <label><input type="checkbox" checked={repeated} onChange={e => change('autoDisputeRejectionCount', e.target.checked ? 2 : null)} /> Open a case after repeated revision requests</label>
    {repeated && <label>Revision requests before intake<input className="input" type="number" min={2} max={20} value={Number(parsed.autoDisputeRejectionCount)} onChange={e => { const value = Number(e.target.value); if (Number.isInteger(value) && value >= 2 && value <= 20) change('autoDisputeRejectionCount', value) }} /></label>}<br />
    <label><input type="checkbox" checked={parsed.autoDisputeComplianceFlag === true} onChange={e => change('autoDisputeComplianceFlag', e.target.checked)} /> Open a case after a confirmed compliance restriction or verification revocation</label>
    <p className="muted">An AI flag alone never opens a case or imposes a sanction. Save and activate the draft to use these controls for new agreements.</p>
  </fieldset>
}
