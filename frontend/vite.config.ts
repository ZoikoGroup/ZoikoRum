import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend (FastAPI) runs on :8000. All API calls go to /v1/* and are proxied,
// so the browser sees a single origin and no CORS setup is needed in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/v1': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
