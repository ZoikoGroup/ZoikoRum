import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { PLATFORM_ROLES } from './api/auth'
import { AuthProvider } from './auth/AuthContext'
import { GuestOnly, RequireAuth, RequireRole } from './auth/guards'
import { ConfirmEmail, ForgotPassword, ResetPassword } from './pages/AccountPages'
import AppShell from './pages/AppShell'
import { AccountPage, ForbiddenPage } from './pages/Dashboards'
import EnterpriseAccess from './pages/EnterpriseAccess'
import { EnterpriseStructurePage, EnterpriseTeamPage } from './pages/EnterprisePages'
import { FirmDashboard, FirmProfilePage, FirmTeamPage } from './pages/FirmPages'
import { InvitationsPage, InviteLanding } from './pages/Invitations'
import Join from './pages/Join'
import Legal from './pages/Legal'
import { OfferingsPage } from './pages/OfferingsPage'
import { ProfessionalDashboard, ProfileSetupPage } from './pages/ProfessionalPages'
import PublicProfilePage from './pages/PublicProfile'
import BrowseProfessionals from './pages/BrowseProfessionals'
import { FirmVerificationPage, ProfessionalVerificationPage, ReviewQueuePage } from './pages/VerificationPages'
import Security from './pages/Security'
import SignIn from './pages/SignIn'
import StaffAdmin from './pages/StaffAdmin'
import { StaffHome } from './pages/StaffHome'
import { BuyerHome, EnterpriseHome } from './pages/WorkspaceHome'
import { SavedPage } from './pages/SavedPage'

const ENTERPRISE: ('ENTERPRISE_ADMIN' | 'ENTERPRISE_MEMBER')[] = ['ENTERPRISE_ADMIN', 'ENTERPRISE_MEMBER']

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
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
            <Route path="buyer" element={<RequireRole any={['BUYER']}><BuyerHome /></RequireRole>} />
            <Route path="professional" element={<RequireRole any={['PROFESSIONAL']}><ProfessionalDashboard /></RequireRole>} />
            <Route path="professional/profile" element={<RequireRole any={['PROFESSIONAL']}><ProfileSetupPage /></RequireRole>} />
            <Route path="professional/offerings" element={<RequireRole any={['PROFESSIONAL']}><OfferingsPage /></RequireRole>} />
            <Route path="professional/verification" element={<RequireRole any={['PROFESSIONAL']}><ProfessionalVerificationPage /></RequireRole>} />
            <Route path="firm" element={<RequireRole any={['FIRM_ADMIN']}><FirmDashboard /></RequireRole>} />
            <Route path="firm/team" element={<RequireRole any={['FIRM_ADMIN', 'PROFESSIONAL']}><FirmTeamPage /></RequireRole>} />
            <Route path="firm/profile" element={<RequireRole any={['FIRM_ADMIN', 'PROFESSIONAL']}><FirmProfilePage /></RequireRole>} />
            <Route path="firm/verification" element={<RequireRole any={['FIRM_ADMIN']}><FirmVerificationPage /></RequireRole>} />
            <Route path="enterprise" element={<RequireRole any={ENTERPRISE}><EnterpriseHome /></RequireRole>} />
            <Route path="enterprise/team" element={<RequireRole any={ENTERPRISE}><EnterpriseTeamPage /></RequireRole>} />
            <Route path="enterprise/structure" element={<RequireRole any={ENTERPRISE}><EnterpriseStructurePage /></RequireRole>} />
            <Route path="saved" element={<RequireRole any={['BUYER', ...ENTERPRISE]}><SavedPage /></RequireRole>} />
            <Route path="invitations" element={<InvitationsPage />} />
            <Route path="ops" element={<RequireRole any={[...PLATFORM_ROLES]}><StaffHome /></RequireRole>} />
            <Route path="ops/staff" element={<RequireRole any={['PLATFORM_ADMIN']}><StaffAdmin /></RequireRole>} />
            <Route path="ops/verification" element={<RequireRole any={['COMPLIANCE_OFFICER']}><ReviewQueuePage /></RequireRole>} />
            <Route path="account" element={<AccountPage />} />
            <Route path="security" element={<Security />} />
            <Route path="forbidden" element={<ForbiddenPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
