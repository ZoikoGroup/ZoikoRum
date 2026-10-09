import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { PLATFORM_ROLES } from './api/auth'
import { AuthProvider } from './auth/AuthContext'
import { GuestOnly, RequireAuth, RequireRole } from './auth/guards'
import { ConfirmEmail, ForgotPassword, ResetPassword } from './pages/AccountPages'
import AppShell from './pages/AppShell'
import { AccountPage, ForbiddenPage } from './pages/Dashboards'
import Join from './pages/Join'
import Legal from './pages/Legal'
import SignIn from './pages/SignIn'

// Pages load on demand (one file per page module), so signing in does not download the whole app.
const AuditExportsPage = lazy(() => import('./pages/AuditExports'))
const EnterpriseAccess = lazy(() => import('./pages/EnterpriseAccess'))
const EnterpriseStructurePage = lazy(() => import('./pages/EnterprisePages').then((m) => ({ default: m.EnterpriseStructurePage })))
const EnterpriseTeamPage = lazy(() => import('./pages/EnterprisePages').then((m) => ({ default: m.EnterpriseTeamPage })))
const FirmDashboard = lazy(() => import('./pages/FirmPages').then((m) => ({ default: m.FirmDashboard })))
const FirmProfilePage = lazy(() => import('./pages/FirmPages').then((m) => ({ default: m.FirmProfilePage })))
const FirmTeamPage = lazy(() => import('./pages/FirmPages').then((m) => ({ default: m.FirmTeamPage })))
const InvitationsPage = lazy(() => import('./pages/Invitations').then((m) => ({ default: m.InvitationsPage })))
const InviteLanding = lazy(() => import('./pages/Invitations').then((m) => ({ default: m.InviteLanding })))
const OfferingsPage = lazy(() => import('./pages/OfferingsPage').then((m) => ({ default: m.OfferingsPage })))
const ProfessionalDashboard = lazy(() => import('./pages/ProfessionalPages').then((m) => ({ default: m.ProfessionalDashboard })))
const ProfileSetupPage = lazy(() => import('./pages/ProfessionalPages').then((m) => ({ default: m.ProfileSetupPage })))
const PublicProfilePage = lazy(() => import('./pages/PublicProfile'))
const BrowseProfessionals = lazy(() => import('./pages/BrowseProfessionals'))
const FirmVerificationPage = lazy(() => import('./pages/VerificationPages').then((m) => ({ default: m.FirmVerificationPage })))
const ProfessionalVerificationPage = lazy(() => import('./pages/VerificationPages').then((m) => ({ default: m.ProfessionalVerificationPage })))
const ReviewQueuePage = lazy(() => import('./pages/VerificationPages').then((m) => ({ default: m.ReviewQueuePage })))
const Security = lazy(() => import('./pages/Security'))
const ComparePage = lazy(() => import('./pages/customer/ComparePage'))
const DuplicateAccountsPage = lazy(() => import('./pages/DuplicateAccounts'))
const TaxonomyAdminPage = lazy(() => import('./pages/TaxonomyAdmin'))
const ReconciliationPage = lazy(() => import('./pages/Reconciliation'))
const StaffAdmin = lazy(() => import('./pages/StaffAdmin'))
const UsersAdmin = lazy(() => import('./pages/UsersAdmin'))
const SavedBuyersPage = lazy(() => import('./pages/SavedBuyers'))
const StaffHome = lazy(() => import('./pages/StaffHome').then((m) => ({ default: m.StaffHome })))
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
const PlatformAnalyticsPage = lazy(() => import('./pages/Operations').then((m) => ({ default: m.PlatformAnalyticsPage })))
const DeadLettersPage = lazy(() => import('./pages/Operations').then((m) => ({ default: m.DeadLettersPage })))

const ENTERPRISE: ('ENTERPRISE_ADMIN' | 'ENTERPRISE_MEMBER')[] = ['ENTERPRISE_ADMIN', 'ENTERPRISE_MEMBER']
const CUSTOMER: ('BUYER' | 'ENTERPRISE_ADMIN' | 'ENTERPRISE_MEMBER')[] = ['BUYER', ...ENTERPRISE]

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Suspense fallback={<p className="muted page-loading">Loading…</p>}>
        <Routes>
          {/* Entry point is sign-in; signed-in users are sent straight to their role's dashboard. */}
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/legal/:page" element={<Legal />} />
          <Route path="/login" element={<GuestOnly><SignIn /></GuestOnly>} />
          <Route path="/join" element={<GuestOnly><Join /></GuestOnly>} />
          <Route path="/enterprise" element={<GuestOnly><EnterpriseAccess /></GuestOnly>} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/confirm-email" element={<ConfirmEmail />} />
          <Route path="/invite" element={<InviteLanding />} />
          <Route path="/professionals" element={<BrowseProfessionals />} />
          <Route path="/professionals/:id" element={<PublicProfilePage />} />

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
            <Route path="requests/:id" element={<RequireRole any={CUSTOMER}><RequestDetailPage /></RequireRole>} />
            <Route path="proposals" element={<RequireRole any={CUSTOMER}><ProposalsPage /></RequireRole>} />
            <Route path="engagements" element={<RequireRole any={CUSTOMER}><EngagementsPage side="buyer" /></RequireRole>} />
            <Route path="engagements/:id" element={<RequireRole any={CUSTOMER}><EngagementDetail side="buyer" /></RequireRole>} />
            <Route path="payments" element={<RequireRole any={CUSTOMER}><CustomerPaymentsPage /></RequireRole>} />
            <Route path="compare" element={<RequireRole any={CUSTOMER}><ComparePage /></RequireRole>} />
            <Route path="professional/earnings" element={<RequireRole any={['PROFESSIONAL']}><EarningsPage /></RequireRole>} />
            <Route path="professional/buyers" element={<RequireRole any={['PROFESSIONAL']}><SavedBuyersPage /></RequireRole>} />
            <Route path="messages" element={<RequireRole any={[...CUSTOMER, 'PROFESSIONAL']}><MessagesPage /></RequireRole>} />
            <Route path="disputes" element={<RequireRole any={CUSTOMER}><DisputesPage role="buyer" /></RequireRole>} />
            <Route path="professional/disputes" element={<RequireRole any={['PROFESSIONAL']}><DisputesPage role="professional" /></RequireRole>} />
            <Route path="ops/disputes" element={<RequireRole any={['MEDIATOR', 'LEGAL', 'PLATFORM_ADMIN']}><DisputesPage role="operator" /></RequireRole>} />
            <Route path="disputes/:id" element={<DisputeDetail />} />
            <Route path="organisation" element={<RequireRole any={CUSTOMER}><OrganisationPage /></RequireRole>} />
            <Route path="verification" element={<RequireRole any={CUSTOMER}><CustomerVerification /></RequireRole>} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="help" element={<HelpPage />} />
            <Route path="invitations" element={<InvitationsPage />} />
            <Route path="ops" element={<RequireRole any={[...PLATFORM_ROLES]}><StaffHome /></RequireRole>} />
            <Route path="ops/staff" element={<RequireRole any={['PLATFORM_ADMIN']}><StaffAdmin /></RequireRole>} />
            <Route path="ops/users" element={<RequireRole any={['PLATFORM_ADMIN', 'TS_ANALYST']}><UsersAdmin /></RequireRole>} />
            <Route path="ops/reconciliation" element={<RequireRole any={['FINANCIAL_OPS', 'PLATFORM_ADMIN']}><ReconciliationPage /></RequireRole>} />
            <Route path="ops/duplicates" element={<RequireRole any={['TS_ANALYST', 'PLATFORM_ADMIN']}><DuplicateAccountsPage /></RequireRole>} />
            <Route path="ops/taxonomy" element={<RequireRole any={['PLATFORM_ADMIN']}><TaxonomyAdminPage /></RequireRole>} />
            <Route path="ops/verification" element={<RequireRole any={['COMPLIANCE_OFFICER']}><ReviewQueuePage /></RequireRole>} />
            <Route path="ops/audit" element={<RequireRole any={[...PLATFORM_ROLES]}><AuditExportsPage /></RequireRole>} />
            <Route path="account" element={<AccountPage />} />
            <Route path="safety" element={<SafetyPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="ops/safety" element={<RequireRole any={[...PLATFORM_ROLES]}><SafetyPage operator /></RequireRole>} />
            <Route path="ops/ai" element={<RequireRole any={['AI_SAFETY_REVIEWER']}><AIAdminPage /></RequireRole>} />
            <Route path="ops/analytics" element={<RequireRole any={[...PLATFORM_ROLES]}><PlatformAnalyticsPage /></RequireRole>} />
            <Route path="ops/dead-letters" element={<RequireRole any={['FINANCIAL_OPS', 'PLATFORM_ADMIN']}><DeadLettersPage /></RequireRole>} />
            <Route path="security" element={<Security />} />
            <Route path="forbidden" element={<ForbiddenPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  )
}
