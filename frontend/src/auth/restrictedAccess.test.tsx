import { beforeEach, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

const state = vi.hoisted(() => ({ pathname: '/app/reports', user: { status: 'SUSPENDED', mfaRequired: true, defaultDashboard: 'buyer' }, loading: false }))
vi.mock('./AuthContext', () => ({ useAuth: () => state }))
vi.mock('react-router-dom', () => ({
  Navigate: ({ to }: { to: string }) => <a href={to}>Redirect</a>,
  useLocation: () => ({ pathname: state.pathname }),
  useSearchParams: () => [new URLSearchParams('next=/app/reports')],
}))
import { GuestOnly, RequireAuth } from './guards'

beforeEach(() => { state.pathname = '/app/reports'; state.user.status = 'SUSPENDED' })
test('restricted accounts are sent to their safety workspace', () => {
  expect(renderToStaticMarkup(<RequireAuth>Business page</RequireAuth>)).toContain('href="/app/safety"')
})
test('a safety page remains accessible when the account would otherwise require MFA setup', () => {
  state.pathname = '/app/safety'
  expect(renderToStaticMarkup(<RequireAuth>Read notice and appeal</RequireAuth>)).toBe('Read notice and appeal')
})
test('a post-login business destination cannot bypass the restricted landing page', () => {
  expect(renderToStaticMarkup(<GuestOnly>Login</GuestOnly>)).toContain('href="/app/safety"')
})
test('active accounts retain the MFA setup requirement', () => {
  state.user.status = 'ACTIVE'
  expect(renderToStaticMarkup(<RequireAuth>Business page</RequireAuth>)).toContain('href="/app/security"')
})
