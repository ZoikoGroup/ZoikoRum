import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { PLATFORM_ROLES } from './api/auth'
import { AuthProvider } from './auth/AuthContext'
import { GuestOnly, RequireAuth, RequireRole } from './auth/guards'
import { ConfirmEmail, ForgotPassword, ResetPassword } from './pages/AccountPages'
import AppShell from './pages/AppShell'
import { AccountPage, DashboardPage, ForbiddenPage } from './pages/Dashboards'
import EnterpriseAccess from './pages/EnterpriseAccess'
import Join from './pages/Join'
import Security from './pages/Security'
import SignIn from './pages/SignIn'
import StaffAdmin from './pages/StaffAdmin'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public: targets of "Sign In", "Enterprise Access" and "Join as a Professional" on zoikorum.com */}
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<GuestOnly><SignIn /></GuestOnly>} />
          <Route path="/join" element={<GuestOnly><Join /></GuestOnly>} />
          <Route path="/enterprise" element={<GuestOnly><EnterpriseAccess /></GuestOnly>} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/confirm-email" element={<ConfirmEmail />} />

          {/* Signed in: each workspace is gated by role (the API enforces the same rules). */}
          <Route path="/app" element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route path="buyer" element={<RequireRole any={['BUYER']}><DashboardPage kind="buyer" /></RequireRole>} />
            <Route path="professional" element={<RequireRole any={['PROFESSIONAL']}><DashboardPage kind="professional" /></RequireRole>} />
            <Route path="firm" element={<RequireRole any={['FIRM_ADMIN']}><DashboardPage kind="firm" /></RequireRole>} />
            <Route path="enterprise" element={<RequireRole any={['ENTERPRISE_ADMIN']}><DashboardPage kind="enterprise" /></RequireRole>} />
            <Route path="ops" element={<RequireRole any={[...PLATFORM_ROLES]}><DashboardPage kind="ops" /></RequireRole>} />
            <Route path="ops/staff" element={<RequireRole any={['PLATFORM_ADMIN']}><StaffAdmin /></RequireRole>} />
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
