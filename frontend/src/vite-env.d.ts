/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "true": run on the in-memory mock instead of the API (src/api/client.ts). */
  readonly VITE_USE_MOCK?: string
  /** The API's base URL in a build; /api (proxied) by default. */
  readonly VITE_API_URL?: string
  /** The branch's Neon Auth URL (vite.config.ts reads NEON_AUTH_BASE_URL). */
  readonly VITE_NEON_AUTH_URL?: string
  /** The branch's Realtime WebSocket URL (NEON_REALTIME_URL). */
  readonly VITE_NEON_REALTIME_URL?: string
  /** The `live` Neon Function, which seals the planning job's live query. */
  readonly VITE_NEON_LIVE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
