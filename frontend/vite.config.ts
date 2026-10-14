import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend (FastAPI) runs on :8000. All API calls go to /v1/* and are proxied,
// so the browser sees a single origin and no CORS setup is needed in development.
// The browser tests (e2e/) run their own API and app: ZK_API_TARGET and ZK_WEB_PORT point the dev server at them.
const api = process.env.ZK_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig(({ command, mode }) => {
  // Staff and customers use separate apps (src/portal.ts):
  //   npm run dev        customer app, http://localhost:5173
  //   npm run dev:staff  staff app,    http://localhost:5174
  //   vite (no mode)     one app with both sign-in pages (browser tests)
  // Production builds take VITE_PORTAL, VITE_CUSTOMER_URL and VITE_STAFF_URL from the environment (frontend/Dockerfile).
  const portal = process.env.VITE_PORTAL ?? (mode === 'staff' || mode === 'customer' ? mode : 'both')
  process.env.VITE_PORTAL = portal
  if (command === 'serve') {
    process.env.VITE_CUSTOMER_URL ??= 'http://localhost:5173'
    process.env.VITE_STAFF_URL ??= 'http://localhost:5174'
  }
  return {
    plugins: [react()],
    server: {
      port: Number(process.env.ZK_WEB_PORT ?? (portal === 'staff' ? 5174 : 5173)),
      strictPort: true,
      host: true, // listen on IPv4 and IPv6, so both localhost and 127.0.0.1 work
      proxy: {
        // uvicorn binds 127.0.0.1; target it directly (Windows may resolve "localhost" to IPv6 ::1).
        '/v1': { target: api, changeOrigin: true },
        '/health': { target: api, changeOrigin: true },
      },
    },
  }
})
