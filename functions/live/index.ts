/**
 * `live` — seals Realtime queries for the cheap_recipe page.
 *
 * Planning runs in the FastAPI backend and writes each step to the
 * `planning_job` row (backend/app/jobs.py). The page asks this function for a
 * sealed live query on its job and subscribes to it, instead of polling.
 * Sealing needs the Realtime TypeScript SDK, which is why this lives in a
 * Neon Function and not in the Python API.
 *
 *   POST /planning-jobs/live   { "jobId": "<32 hex>" }   Authorization: Bearer <Neon Auth JWT>
 *   → SealedLiveQuery<PlanningJobRow>   (renewed by posting again)
 *
 * The URL is public, so every request is authenticated: the Neon Auth JWT is
 * verified against the branch's JWKS, and the query itself joins through
 * user_account on the token's `sub`, so a job id alone shows nothing.
 */

import { createRealtime, rawSql } from "@neon/realtime/server";
import { createRemoteJWKSet, jwtVerify } from "jose";

export interface PlanningJobRow {
  id: string;
  status: "running" | "done" | "failed";
  steps: string[];
  error: string | null;
  error_status: number | null;
}

const authBase = process.env.NEON_AUTH_BASE_URL!;
const authOrigin = new URL(authBase).origin;
const jwks = createRemoteJWKSet(new URL(process.env.NEON_AUTH_JWKS_URL ?? `${authBase}/.well-known/jwks.json`));

const databaseName = new URL(process.env.DATABASE_URL!).pathname.slice(1) || "neondb";
const realtime = createRealtime({
  secret: process.env.NEON_REALTIME_SECRET ?? process.env.REALTIME_SECRET!,
  db: databaseName,
});

const allowedOrigins = new Set(
  (process.env.ALLOWED_ORIGINS ?? "http://localhost:5173").split(",").map((o) => o.trim()).filter(Boolean),
);

const JOB_ID = /^[0-9a-f]{32}$/;

/** Only the job's owner matches: the row is joined to the account the token signs in. */
function planningJobQuery(authUserId: string, jobId: string) {
  return rawSql<PlanningJobRow>(
    `SELECT planning_job.id, planning_job.status, planning_job.steps,
            planning_job.error, planning_job.error_status
       FROM planning_job
       JOIN user_account ON user_account.id = planning_job.user_id
      WHERE user_account.auth_user_id = $1 AND planning_job.id = $2`,
    [authUserId, jobId],
  );
}

function cors(request: Request): Record<string, string> {
  const origin = request.headers.get("origin");
  if (!origin || !allowedOrigins.has(origin)) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "600",
    Vary: "Origin",
  };
}

function json(request: Request, status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...cors(request) },
  });
}

async function userId(request: Request): Promise<string | undefined> {
  const header = request.headers.get("authorization");
  if (!header?.toLowerCase().startsWith("bearer ")) return undefined;
  try {
    const { payload } = await jwtVerify(header.slice(7), jwks, { issuer: authOrigin, audience: authOrigin });
    return typeof payload.sub === "string" ? payload.sub : undefined;
  } catch {
    return undefined;
  }
}

export default {
  async fetch(request: Request): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(request) });
    if (request.method === "GET" && pathname === "/health") return json(request, 200, { status: "ok" });
    if (pathname !== "/planning-jobs/live") return json(request, 404, { error: "Not found" });
    if (request.method !== "POST") return json(request, 405, { error: "Method not allowed" });

    const sub = await userId(request);
    if (!sub) return json(request, 401, { error: "Unauthorized" });

    let jobId: unknown;
    try {
      ({ jobId } = (await request.json()) as { jobId?: unknown });
    } catch {
      return json(request, 400, { error: "Body must be JSON" });
    }
    if (typeof jobId !== "string" || !JOB_ID.test(jobId)) {
      return json(request, 400, { error: "jobId must be a planning job id" });
    }

    return json(request, 200, await realtime.seal({ query: planningJobQuery(sub, jobId) }));
  },
};
