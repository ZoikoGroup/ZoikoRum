import { Link } from 'react-router-dom'
import { AuthLayout } from '../components/ui'

const ROLES = [
  ['Enterprise Admin', 'Sets up the organization, policy profiles and team access.'],
  ['Requester', 'Raises engagement requests for their business unit.'],
  ['Approver', 'Approves engagements and releases within their authority.'],
  ['Budget Owner', 'Owns cost-center spend and milestone release thresholds.'],
  ['Legal Reviewer', 'Reviews contracts and audit exports.'],
  ['Exception Authority', 'The only role that may approve policy exceptions.'],
]

/** Target of the "Enterprise Access" button on zoikorum.com. */
export default function EnterpriseAccess() {
  return (
    <AuthLayout
      aside={
        <>
          <h3>Roles in an enterprise account</h3>
          <ul>
            {ROLES.map(([r, d]) => (
              <li key={r}><span className="check" aria-hidden>✓</span><span><strong>{r}</strong><br /><span className="muted small">{d}</span></span></li>
            ))}
          </ul>
        </>
      }
    >
      <h1>Enterprise Access</h1>
      <p className="sub">
        Engage external professionals under your own policy profiles, approval chains and audit exports,
        before work begins.
      </p>
      <div className="grid-cards" style={{ gridTemplateColumns: '1fr' }}>
        <div className="card panel" style={{ boxShadow: 'none' }}>
          <h3>My organization already uses Zoikorum</h3>
          <p className="muted small">Sign in with your work email. Your role decides what you can see and approve.</p>
          <Link className="btn btn-primary" to="/login">Sign in</Link>
        </div>
        <div className="card panel" style={{ boxShadow: 'none' }}>
          <h3>Set up a new enterprise account</h3>
          <p className="muted small">You become the Enterprise Admin. Two-step verification is required for admins.</p>
          <Link className="btn btn-secondary" to="/join?type=ENTERPRISE">Create enterprise account</Link>
        </div>
      </div>
      <p className="small muted">
        Need a procurement pack or security review first? <a href="https://zoikorum.com/#contact">Contact sales</a>.
      </p>
    </AuthLayout>
  )
}
