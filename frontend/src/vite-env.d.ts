/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "true": run on the in-memory mock instead of the API (src/api/client.ts). */
  readonly VITE_USE_MOCK?: string
  /** The API's base URL in a build; /api (proxied) by default. */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
