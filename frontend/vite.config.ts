import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend (FastAPI) runs on :8000. All API calls go to /v1/* and are proxied,
// so the browser sees a single origin and no CORS setup is needed in development.
// The browser tests (e2e/) run their own API and app: ZK_API_TARGET and ZK_WEB_PORT point the dev server at them.
const api = process.env.ZK_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.ZK_WEB_PORT ?? 5173),
    strictPort: true,
    host: true, // listen on IPv4 and IPv6, so both localhost and 127.0.0.1 work
    proxy: {
      // uvicorn binds 127.0.0.1; target it directly (Windows may resolve "localhost" to IPv6 ::1).
      '/v1': { target: api, changeOrigin: true },
      '/health': { target: api, changeOrigin: true },
    },
  },
})
