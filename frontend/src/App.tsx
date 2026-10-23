import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { elsewhere, PORTAL } from './portal'
import { AuthProvider } from './auth/AuthContext'
import { CapabilitiesProvider, RequireCapability } from './auth/capabilities'
import { GuestOnly, RequireAuth, RequireRole } from './auth/guards'
import { ConfirmEmail, ForgotPassword, ResetPassword } from './pages/AccountPages'
import AppShell from './pages/AppShell'
import { AccountPage, ForbiddenPage } from './pages/Dashboards'
import Join from './pages/Join'
import Legal from './pages/Legal'
import SignIn from './pages/SignIn'
import { isStaffPath, legacyOpsPath, STAFF_HOME, STAFF_PREFIX } from './staffRoutes'

// Pages load on demand (one file per page module), so signing in does not download the whole app.
const StaffAccounts = lazy(() => import('./pages/staff/Accounts'))
const StaffAnalytics = lazy(() => import('./pages/staff/Analytics'))
const StaffAuditEvidence = lazy(() => import('./pages/staff/AuditEvidence'))
const StaffCommandCenter = lazy(() => import('./pages/staff/CommandCenter'))
const StaffContractsMilestones = lazy(() => import('./pages/staff/ContractsMilestones'))
const StaffDisputeResolution = lazy(() => import('./pages/staff/DisputeResolution'))
const StaffDuplicateIdentity = lazy(() => import('./pages/staff/DuplicateIdentity'))
const StaffEngagementOversight = lazy(() => import('./pages/staff/EngagementOversight'))
const StaffEnterpriseReadinessAdmin = lazy(() => import('./pages/staff/EnterpriseReadinessAdmin'))
const StaffFailedDeliveries = lazy(() => import('./pages/staff/FailedDeliveries'))
const StaffFeatureControls = lazy(() => import('./pages/staff/FeatureControls'))
const StaffFinancialExceptions = lazy(() => import('./pages/staff/FinancialExceptions'))
const StaffIncidentCommand = lazy(() => import('./pages/staff/IncidentCommand'))
const StaffPlatformConfig = lazy(() => import('./pages/staff/PlatformConfig'))
const StaffProfessionalDirectory = lazy(() => import('./pages/staff/ProfessionalDirectory'))
const StaffProtectedPayments = lazy(() => import('./pages/staff/ProtectedPayments'))
const StaffReconciliationCenter = lazy(() => import('./pages/staff/ReconciliationCenter'))
const StaffServiceHealth = lazy(() => import('./pages/staff/ServiceHealth'))
const StaffStaffAccess = lazy(() => import('./pages/staff/StaffAccess'))
const StaffSupportCases = lazy(() => import('./pages/staff/SupportCases'))
const StaffTaxonomyStandards = lazy(() => import('./pages/staff/TaxonomyStandards'))
const StaffTrustSafety = lazy(() => import('./pages/staff/TrustSafety'))
const StaffVerificationCenter = lazy(() => import('./pages/staff/VerificationCenter'))
const StaffWorkQueue = lazy(() => import('./pages/staff/WorkQueue'))
const StaffApprovals = lazy(() => import('./pages/staff/Approvals'))
const EnterpriseAccess = lazy(() => import('./pages/EnterpriseAccess'))
const EnterpriseStructurePage = lazy(() => import('./pages/EnterprisePages').then((m) => ({ default: m.EnterpriseStructurePage })))
const EnterpriseTeamPage = lazy(() => import('./pages/EnterprisePages').then((m) => ({ default: m.EnterpriseTeamPage })))
const FirmDashboard = lazy(() => import('./pages/FirmPages').then((m) => ({ default: m.FirmDashboard })))
const FirmProfilePage = lazy(() => import('./pages/FirmPages').then((m) => ({ default: m.FirmProfilePage })))
const FirmTeamPage = lazy(() => import('./pages/FirmPages').then((m) => ({ default: m.FirmTeamPage })))
const InvitationsPage = lazy(() => import('./pages/Invitations').then((m) => ({ default: m.InvitationsPage })))
const InviteLanding = lazy(() => import('./pages/Invitations').then((m) => ({ default: m.InviteLanding })))
const BuyerBriefsPage = lazy(() => import('./pages/OpenBriefs').then((m) => ({ default: m.BuyerBriefsPage })))
const ProfessionalBriefsPage = lazy(() => import('./pages/OpenBriefs').then((m) => ({ default: m.ProfessionalBriefsPage })))
const OfferingsPage = lazy(() => import('./pages/OfferingsPage').then((m) => ({ default: m.OfferingsPage })))
const ProfessionalDashboard = lazy(() => import('./pages/ProfessionalPages').then((m) => ({ default: m.ProfessionalDashboard })))
const ProfileSetupPage = lazy(() => import('./pages/ProfessionalPages').then((m) => ({ default: m.ProfileSetupPage })))
const PublicProfilePage = lazy(() => import('./pages/PublicProfile'))
const PublicFirmPage = lazy(() => import('./pages/PublicFirm'))
const BrowseProfessionals = lazy(() => import('./pages/BrowseProfessionals'))
const CategoryPage = lazy(() => import('./pages/CategoryPage'))
const SsoCallbackPage = lazy(() => import('./components/SingleSignOn').then((m) => ({ default: m.SsoCallbackPage })))
const FirmVerificationPage = lazy(() => import('./pages/VerificationPages').then((m) => ({ default: m.FirmVerificationPage })))
const ProfessionalVerificationPage = lazy(() => import('./pages/VerificationPages').then((m) => ({ default: m.ProfessionalVerificationPage })))
const Security = lazy(() => import('./pages/Security'))
const ComparePage = lazy(() => import('./pages/customer/ComparePage'))
const SavedBuyersPage = lazy(() => import('./pages/SavedBuyers'))
const BuyerHome = lazy(() => import('./pages/WorkspaceHome').then((m) => ({ default: m.BuyerHome })))
const EnterpriseHome = lazy(() => import('./pages/WorkspaceHome').then((m) => ({ default: m.EnterpriseHome })))
const CustomerVerification = lazy(() => import('./pages/customer/CustomerVerification'))
const FindProfessionals = lazy(() => import('./pages/customer/FindProfessionals'))
const HelpPage = lazy(() => import('./pages/customer/Help'))
const OrganisationPage = lazy(() => import('./pages/customer/Organisation'))
const ProposalsPage = lazy(() => import('./pages/customer/CustomerRequests').then((m) => ({ default: m.ProposalsPage })))
const RequestDetailPage = lazy(() => import('./pages/customer/CustomerRequests').then((m) => ({ default: m.RequestDetailPage })))
const RequestsPage = lazy(() => import('./pages/customer/CustomerRequests').then((m) => ({ default: m.RequestsPage })))
const MessagesPage = lazy(() => import('./pages/customer/Pipeline').then((m) => ({ default: m.MessagesPage })))
const CustomerPaymentsPage = lazy(() => import('./pages/Money').then((m) => ({ default: m.CustomerPaymentsPage })))
const PerformanceInsights = lazy(() => import('./pages/PerformanceInsights'))
const EnterpriseReadinessPage = lazy(() => import('./pages/EnterpriseReadiness').then((m) => ({ default: m.EnterpriseReadinessPage })))
const EarningsPage = lazy(() => import('./pages/Money').then((m) => ({ default: m.EarningsPage })))
const DisputeDetail = lazy(() => import('./pages/Disputes').then((m) => ({ default: m.DisputeDetail })))
const DisputesPage = lazy(() => import('./pages/Disputes').then((m) => ({ default: m.DisputesPage })))
const EngagementDetail = lazy(() => import('./pages/Engagements').then((m) => ({ default: m.EngagementDetail })))
const EngagementsPage = lazy(() => import('./pages/Engagements').then((m) => ({ default: m.EngagementsPage })))
const RequestWizard = lazy(() => import('./pages/customer/RequestWizard'))
const ProfessionalRequestDetail = lazy(() => import('./pages/ProfessionalRequests').then((m) => ({ default: m.ProfessionalRequestDetail })))
const ProfessionalRequestsPage = lazy(() => import('./pages/ProfessionalRequests').then((m) => ({ default: m.ProfessionalRequestsPage })))
const SavedProfessionals = lazy(() => import('./pages/customer/SavedProfessionals'))
const SettingsPage = lazy(() => import('./pages/customer/Settings'))
const PoliciesPage = lazy(() => import('./pages/Policies'))
const NotificationsPage = lazy(() => import('./pages/Notifications').then((m) => ({ default: m.NotificationsPage })))
const WebhooksPage = lazy(() => import('./pages/Notifications').then((m) => ({ default: m.WebhooksPage })))
const SafetyPage = lazy(() => import('./pages/Operations').then((m) => ({ default: m.SafetyPage })))
const AIAdminPage = lazy(() => import('./pages/Operations').then((m) => ({ default: m.AIAdminPage })))
const ReportsPage = lazy(() => import('./pages/Operations').then((m) => ({ default: m.ReportsPage })))

const ENTERPRISE: ('ENTERPRISE_ADMIN' | 'ENTERPRISE_MEMBER')[] = ['ENTERPRISE_ADMIN', 'ENTERPRISE_MEMBER']
const CUSTOMER: ('BUYER' | 'ENTERPRISE_ADMIN' | 'ENTERPRISE_MEMBER')[] = ['BUYER', ...ENTERPRISE]

export default function App() {
  return (
    <AuthProvider>
      <CapabilitiesProvider>
      <BrowserRouter>
        <Suspense fallback={<p className="muted page-loading">Loading…</p>}>
        <PortalGate>
        <Routes>
          {/* Entry point is sign-in; signed-in users are sent straight to their role's dashboard. */}
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/legal/:page" element={<Legal />} />
          <Route path="/login" element={<GuestOnly><SignIn /></GuestOnly>} />
          <Route path="/staff/login" element={<GuestOnly><SignIn staff key="staff" /></GuestOnly>} />
          <Route path="/join" element={<GuestOnly><Join /></GuestOnly>} />
          <Route path="/enterprise" element={<GuestOnly><EnterpriseAccess /></GuestOnly>} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/confirm-email" element={<ConfirmEmail />} />
          <Route path="/sso/callback" element={<SsoCallbackPage />} />
          <Route path="/invite" element={<InviteLanding />} />
          <Route path="/professionals" element={<BrowseProfessionals />} />
          <Route path="/categories/:slug" element={<CategoryPage />} />
          <Route path="/finance-accounting" element={<Navigate to="/categories/finance-and-accounting" replace />} />
          <Route path="/professionals/:id" element={<PublicProfilePage />} />
          <Route path="/firms/:id" element={<PublicFirmPage />} />

          {/* Signed in: each workspace is gated by role (the API enforces the same rules). */}
          <Route path="/app" element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="webhooks" element={<RequireRole any={CUSTOMER}><WebhooksPage /></RequireRole>} />
            <Route path="policies" element={<RequireRole any={CUSTOMER}><PoliciesPage /></RequireRole>} />
            <Route path="buyer" element={<RequireRole any={['BUYER']}><BuyerHome /></RequireRole>} />
            <Route path="professional" element={<RequireRole any={['PROFESSIONAL']}><ProfessionalDashboard /></RequireRole>} />
            <Route path="professional/profile" element={<RequireRole any={['PROFESSIONAL']}><ProfileSetupPage /></RequireRole>} />
            <Route path="professional/engagements" element={<RequireRole any={['PROFESSIONAL']}><EngagementsPage side="professional" /></RequireRole>} />
            <Route path="professional/engagements/:id" element={<RequireRole any={['PROFESSIONAL']}><EngagementDetail side="professional" /></RequireRole>} />
            <Route path="professional/requests" element={<RequireRole any={['PROFESSIONAL']}><ProfessionalRequestsPage /></RequireRole>} />
            <Route path="professional/briefs" element={<RequireRole any={['PROFESSIONAL']}><ProfessionalBriefsPage /></RequireRole>} />
            <Route path="professional/requests/:id" element={<RequireRole any={['PROFESSIONAL']}><ProfessionalRequestDetail /></RequireRole>} />
            <Route path="professional/offerings" element={<RequireRole any={['PROFESSIONAL']}><OfferingsPage /></RequireRole>} />
            <Route path="professional/verification" element={<RequireRole any={['PROFESSIONAL']}><ProfessionalVerificationPage /></RequireRole>} />
            <Route path="firm" element={<RequireRole any={['FIRM_ADMIN']}><FirmDashboard /></RequireRole>} />
            <Route path="firm/team" element={<RequireRole any={['FIRM_ADMIN', 'PROFESSIONAL']}><FirmTeamPage /></RequireRole>} />
            <Route path="firm/profile" element={<RequireRole any={['FIRM_ADMIN', 'PROFESSIONAL']}><FirmProfilePage /></RequireRole>} />
            <Route path="firm/verification" element={<RequireRole any={['FIRM_ADMIN']}><FirmVerificationPage /></RequireRole>} />
            <Route path="enterprise" element={<RequireRole any={ENTERPRISE}><EnterpriseHome /></RequireRole>} />
            <Route path="enterprise/team" element={<RequireRole any={ENTERPRISE}><EnterpriseTeamPage /></RequireRole>} />
            <Route path="enterprise/structure" element={<RequireRole any={ENTERPRISE}><EnterpriseStructurePage /></RequireRole>} />
            <Route path="find" element={<RequireRole any={CUSTOMER}><FindProfessionals /></RequireRole>} />
            <Route path="saved" element={<RequireRole any={CUSTOMER}><SavedProfessionals /></RequireRole>} />
            <Route path="requests" element={<RequireRole any={CUSTOMER}><RequestsPage /></RequireRole>} />
            <Route path="requests/new" element={<RequireRole any={CUSTOMER}><RequestWizard /></RequireRole>} />
            <Route path="briefs" element={<RequireRole any={CUSTOMER}><BuyerBriefsPage /></RequireRole>} />
            <Route path="requests/:id" element={<RequireRole any={CUSTOMER}><RequestDetailPage /></RequireRole>} />
            <Route path="proposals" element={<RequireRole any={CUSTOMER}><ProposalsPage /></RequireRole>} />
            <Route path="engagements" element={<RequireRole any={CUSTOMER}><EngagementsPage side="buyer" /></RequireRole>} />
            <Route path="engagements/:id" element={<RequireRole any={CUSTOMER}><EngagementDetail side="buyer" /></RequireRole>} />
            <Route path="payments" element={<RequireRole any={CUSTOMER}><CustomerPaymentsPage /></RequireRole>} />
            <Route path="compare" element={<RequireRole any={CUSTOMER}><ComparePage /></RequireRole>} />
            <Route path="professional/earnings" element={<RequireRole any={['PROFESSIONAL']}><EarningsPage /></RequireRole>} />
            <Route path="professional/insights" element={<RequireRole any={['PROFESSIONAL']}><PerformanceInsights /></RequireRole>} />
            <Route path="professional/enterprise" element={<RequireRole any={['PROFESSIONAL']}><EnterpriseReadinessPage /></RequireRole>} />
            <Route path="professional/buyers" element={<RequireRole any={['PROFESSIONAL']}><SavedBuyersPage /></RequireRole>} />
            <Route path="messages" element={<RequireRole any={[...CUSTOMER, 'PROFESSIONAL']}><MessagesPage /></RequireRole>} />
            <Route path="disputes" element={<RequireRole any={CUSTOMER}><DisputesPage role="buyer" /></RequireRole>} />
            <Route path="professional/disputes" element={<RequireRole any={['PROFESSIONAL']}><DisputesPage role="professional" /></RequireRole>} />
            <Route path="disputes/:id" element={<DisputeDetail />} />
            <Route path="organisation" element={<RequireRole any={CUSTOMER}><OrganisationPage /></RequireRole>} />
            <Route path="verification" element={<RequireRole any={CUSTOMER}><CustomerVerification /></RequireRole>} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="help" element={<HelpPage />} />
            <Route path="invitations" element={<InvitationsPage />} />
            <Route path="account" element={<AccountPage />} />
            <Route path="safety" element={<SafetyPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="security" element={<Security />} />
            <Route path="forbidden" element={<ForbiddenPage />} />
          </Route>
          {/* Staff console (Admin Navigation Registry): each page needs its read capability (GET /v1/admin/me/capabilities). */}
          <Route path={STAFF_PREFIX} element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route index element={<Navigate to={STAFF_HOME} replace />} />
            <Route path="command-center" element={<RequireCapability cap="dashboard.read"><StaffCommandCenter /></RequireCapability>} />
            <Route path="my-work-queue" element={<RequireCapability cap="work.read"><StaffWorkQueue /></RequireCapability>} />
            <Route path="analytics-insights" element={<RequireCapability cap="analytics.read"><StaffAnalytics /></RequireCapability>} />
            <Route path="accounts-organizations" element={<RequireCapability cap="accounts.read"><StaffAccounts /></RequireCapability>} />
            <Route path="professional-directory" element={<RequireCapability cap="professionals.read"><StaffProfessionalDirectory /></RequireCapability>} />
            <Route path="enterprise-readiness" element={<RequireCapability cap="enterprise.read"><StaffEnterpriseReadinessAdmin /></RequireCapability>} />
            <Route path="duplicate-identity-cases" element={<RequireCapability cap="identity_cases.read"><StaffDuplicateIdentity /></RequireCapability>} />
            <Route path="verification-center" element={<RequireCapability cap="verification.read"><StaffVerificationCenter /></RequireCapability>} />
            <Route path="trust-safety" element={<RequireCapability cap="safety.read"><StaffTrustSafety /></RequireCapability>} />
            <Route path="dispute-resolution" element={<RequireCapability cap="disputes.read"><StaffDisputeResolution /></RequireCapability>} />
            <Route path="audit-evidence" element={<RequireCapability cap="audit.read"><StaffAuditEvidence /></RequireCapability>} />
            <Route path="engagement-oversight" element={<RequireCapability cap="engagements.read"><StaffEngagementOversight /></RequireCapability>} />
            <Route path="contracts-milestones" element={<RequireCapability cap="contracts.read"><StaffContractsMilestones /></RequireCapability>} />
            <Route path="taxonomy-standards" element={<RequireCapability cap="taxonomy.read"><StaffTaxonomyStandards /></RequireCapability>} />
            <Route path="protected-payments" element={<RequireCapability cap="payments.read"><StaffProtectedPayments /></RequireCapability>} />
            <Route path="reconciliation" element={<RequireCapability cap="recon.read"><StaffReconciliationCenter /></RequireCapability>} />
            <Route path="financial-exceptions" element={<RequireCapability cap="finexceptions.read"><StaffFinancialExceptions /></RequireCapability>} />
            <Route path="incident-command" element={<RequireCapability cap="incidents.read"><StaffIncidentCommand /></RequireCapability>} />
            <Route path="service-health-workers" element={<RequireCapability cap="health.read"><StaffServiceHealth /></RequireCapability>} />
            <Route path="feature-controls" element={<RequireCapability cap="switches.read"><StaffFeatureControls /></RequireCapability>} />
            <Route path="failed-event-deliveries" element={<RequireCapability cap="dlq.read"><StaffFailedDeliveries /></RequireCapability>} />
            <Route path="approvals" element={<RequireCapability cap="approvals.read"><StaffApprovals /></RequireCapability>} />
            <Route path="staff-access-control" element={<RequireCapability cap="iam.read"><StaffStaffAccess /></RequireCapability>} />
            <Route path="support-cases" element={<RequireCapability cap="support.read"><StaffSupportCases /></RequireCapability>} />
            <Route path="platform-configuration" element={<RequireCapability cap="configuration.read"><StaffPlatformConfig /></RequireCapability>} />
            <Route path="ai-governance" element={<RequireCapability cap="ai.read"><AIAdminPage /></RequireCapability>} />
          </Route>
          {/* Old staff console addresses (bookmarks, older emails) open the same page at its new address. */}
          <Route path="/app/ops/*" element={<LegacyOpsRedirect />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
        </PortalGate>
        </Suspense>
      </BrowserRouter>
      </CapabilitiesProvider>
    </AuthProvider>
  )
}

const CUSTOMER_ONLY = /^\/(join|enterprise|invite|professionals|firms)(\/|$)/

/** Staff and customers use separate web apps (portal.ts): each sends the other's pages to the other address. */
function PortalGate({ children }: { children: ReactNode }) {
  const { pathname, search, state } = useLocation()
  if (PORTAL === 'staff') {
    if (pathname === '/' || pathname === '/login') return <Navigate to={`/staff/login${search}`} replace state={state} />
    if (CUSTOMER_ONLY.test(pathname)) return <Away to={elsewhere(pathname + search)} />
  }
  if (PORTAL === 'customer' && (pathname.startsWith('/staff') || isStaffPath(pathname))) {
    return <Away to={elsewhere(pathname + search)} />
  }
  return <>{children}</>
}

/** /app/ops/<old page>?<query>#<hash> -> /platform-admin/<registry slug>?<query>#<hash> */
function LegacyOpsRedirect() {
  const { pathname, search, hash } = useLocation()
  return <Navigate to={legacyOpsPath(pathname) + search + hash} replace />
}

function Away({ to }: { to: string | null }) {
  useEffect(() => { if (to) window.location.replace(to) }, [to])
  if (!to) return <Navigate to="/" replace />  // the other address is not configured: stay on this app
  return <p className="muted page-loading">Redirecting…</p>
}
