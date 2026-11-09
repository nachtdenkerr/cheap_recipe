import { defineConfig } from "@neon/config/v1";

// cheap_recipe's Neon backend. Deploy with `neon deploy --env .env` (the
// `live` function's env reads process.env). See README › Neon.
//
// Postgres: the FastAPI API's database (SQLAlchemy + psycopg, Alembic).
// Auth:     Managed Better Auth; the page signs in, the API verifies the JWT.
// AI:       the AI Gateway, used when LLM_PROVIDER=neon.
// Storage:  `assets` — the weekly offers archive (backend/src/cheaprecipe/storage.py).
// Function: `live` seals Realtime queries on planning jobs (functions/live).
// Realtime: the page watches its planning job live.

// Origins the browser app is served from: Realtime accepts their WebSockets,
// and the `live` function answers their CORS requests.
const appOrigins = (process.env.APP_ORIGINS ?? "http://localhost:5173")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

export default defineConfig({
  preview: {
    realtime: { allowedOrigins: appOrigins },
  },
  auth: true,
  aiGateway: true,
  functions: {
    live: {
      name: "Planning job live queries",
      source: "./functions/live/index.ts",
      env: {
        // The branch's Realtime secret, from the env file `neon deploy --env` reads.
        REALTIME_SECRET: { value: process.env.NEON_REALTIME_SECRET, required: true },
        ALLOWED_ORIGINS: appOrigins.join(","),
      },
    },
  },
  buckets: {
    // Private: the offers archive is read with credentials or presigned URLs.
    assets: { access: "private" },
  },
  // Branch policy: per-branch tuning
  branch: (branch) => {
    if (branch.isDefault) {
      // Default branch: no overrides, uses project defaults
      return {};
    }
    if (!branch.exists) {
      // New non-default branches: auto-expire
      // Run `neon checkout <name>` to create a new branch with these settings
      return { ttl: "7d" };
    }
    // Existing branch: no changes
    return {};
  },
});
