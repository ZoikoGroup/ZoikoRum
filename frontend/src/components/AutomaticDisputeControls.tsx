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

const ROLES = ['ORG_ADMIN', 'REQUESTER', 'APPROVER', 'BUDGET_OWNER', 'LEGAL_REVIEWER', 'EXCEPTION_AUTHORITY'] as const

/** Enterprise dispute controls: thresholds are whole currency units here and minor units in the policy. */
export function DisputeSettlementControls({ settings, onChange, disabled }: Props) {
  let parsed: Record<string, unknown>
  try { parsed = JSON.parse(settings); if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return null } catch { return null }
  function change(key: string, value: unknown) { onChange(JSON.stringify({ ...parsed, [key]: value }, null, 2)) }
  const units = (key: string) => typeof parsed[key] === 'number' ? String(Number(parsed[key]) / 100) : ''
  const setUnits = (key: string, v: string) => change(key, v.trim() === '' ? null : Math.max(0, Math.round(Number(v) * 100)))
  const roles = Array.isArray(parsed.disputeEscalationRoles) ? parsed.disputeEscalationRoles as string[] : []
  return <fieldset disabled={disabled} className="panel"><legend>Dispute settlement controls</legend>
    <label>A mediator handles settlements above (engagement currency, leave empty for none)
      <input className="input" type="number" min={0} value={units('disputeMediationAboveMinor')} onChange={e => setUnits('disputeMediationAboveMinor', e.target.value)} /></label>
    <label>Your Legal Reviewer must agree to settlements above
      <input className="input" type="number" min={0} value={units('disputeLegalReviewAboveMinor')} onChange={e => setUnits('disputeLegalReviewAboveMinor', e.target.value)} /></label>
    <label>Keep closed dispute records at least (years; empty: platform default or the law, whichever is longer)
      <input className="input" type="number" min={1} max={25} value={typeof parsed.disputeRetentionYears === 'number' ? String(parsed.disputeRetentionYears) : ''}
        onChange={e => change('disputeRetentionYears', e.target.value ? Math.min(25, Math.max(1, Math.round(Number(e.target.value)))) : null)} /></label>
    <p className="small">Who may escalate a dispute to mediation for your organisation (none ticked: any Requester or Approver)</p>
    {ROLES.map(r => <label key={r} style={{ marginRight: 12 }}><input type="checkbox" checked={roles.includes(r)}
      onChange={e => { const next = e.target.checked ? [...roles, r] : roles.filter(x => x !== r); change('disputeEscalationRoles', next.length ? next : null) }} /> {r.replace('_', ' ').toLowerCase()}</label>)}
  </fieldset>
}
