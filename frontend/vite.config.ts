import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// The Neon branch's public URLs, from the repo root's .env (written by
// `neon deploy` / `neon env pull`), exposed to the browser under VITE_ names.
// Only these URLs are read: the root .env also holds server secrets, which
// must never reach a bundle. A VITE_ value set in frontend/.env* wins.
function neonUrls(mode: string): Record<string, string> {
  const root = loadEnv(mode, '..', '')
  const local = loadEnv(mode, '.', 'VITE_')
  const liveUrl =
    root.NEON_BRANCH_ID && root.NEON_FUNCTION_HOST_SUFFIX
      ? `https://${root.NEON_BRANCH_ID}-live${root.NEON_FUNCTION_HOST_SUFFIX}`
      : ''
  const values: Record<string, string | undefined> = {
    VITE_NEON_AUTH_URL: local.VITE_NEON_AUTH_URL ?? root.NEON_AUTH_BASE_URL,
    VITE_NEON_REALTIME_URL: local.VITE_NEON_REALTIME_URL ?? root.NEON_REALTIME_URL,
    VITE_NEON_LIVE_URL: local.VITE_NEON_LIVE_URL ?? liveUrl,
  }
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [`import.meta.env.${key}`, JSON.stringify(value ?? '')]),
  )
}

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  define: neonUrls(mode),
  server: {
    port: 5173,
    // The FastAPI backend (uv run uvicorn app.main:app in backend/). Set
    // VITE_USE_MOCK=true in .env.local to run on src/api/mockData.ts instead.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
}))
