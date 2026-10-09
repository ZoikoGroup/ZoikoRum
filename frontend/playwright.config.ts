import { defineConfig, devices } from '@playwright/test'

/* Browser tests: a real Chrome drives the app against its own API, worker and database (zk_e2e), so a developer's
   running app (5173 / 8000) and data are never touched.
     npm run e2e          (needs PostgreSQL from docker-compose.yml and the backend virtualenv)
   backend/scripts/e2e_stack.py recreates and migrates the database, then runs the API and worker on 8100 (one step, so
   the servers never start before their database exists). */

const API_PORT = 8100
const WEB_PORT = 5174
const python = process.env.ZK_E2E_PYTHON ?? (process.platform === 'win32' ? '../.venv/Scripts/python.exe' : 'python')

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',  // not *.test.ts / *.spec.ts, which Vitest runs
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command: `"${python}" ../backend/scripts/e2e_stack.py`,
      url: `http://127.0.0.1:${API_PORT}/ready`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { ZK_E2E_API_PORT: String(API_PORT), ZK_E2E_WEB_URL: `http://localhost:${WEB_PORT}` },
    },
    {
      command: 'npx vite',
      url: `http://localhost:${WEB_PORT}/login`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { ZK_API_TARGET: `http://127.0.0.1:${API_PORT}`, ZK_WEB_PORT: String(WEB_PORT) },
    },
  ],
})

