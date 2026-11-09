/**
 * Waiting for a planning job (app/jobs.py): pass each new step on, and
 * resolve with the finished job — or reject with the ApiError the plain
 * request would have given (409 no offers, 429 quota…).
 *
 * Live when Neon Realtime is configured: the `live` Neon Function
 * (functions/live) seals a query over the job's row, and the page watches it
 * change as the planner writes each step. The finished job — its recipes —
 * is then read once from the API. Without Realtime (the mock, or a failed
 * subscription) the job is polled instead.
 */

import {
  createRealtimeClient,
  type RealtimeClient,
  type SealedLiveQuery,
} from '@neon/realtime/client'

import { getToken } from '../auth/neonAuth'
import { ApiError, USE_MOCK, fetchPlanningJob } from './client'
import type { PlanningJob } from './types'

const POLL_MS = 1000
const RENEW_EARLY_MS = 10_000

const REALTIME_URL = import.meta.env.VITE_NEON_REALTIME_URL
const LIVE_URL = import.meta.env.VITE_NEON_LIVE_URL

/** The row the live query returns (functions/live/index.ts). */
interface JobRow {
  id: string
  status: PlanningJob['status']
  steps: string[]
  error: string | null
  error_status: number | null
}

let realtime: RealtimeClient | null = null

async function sealJobQuery(jobId: string): Promise<SealedLiveQuery<JobRow>> {
  const token = await getToken()
  const response = await fetch(`${LIVE_URL}/planning-jobs/live`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ jobId }),
  })
  if (!response.ok) throw new ApiError(response.status, `Live updates refused (${response.status})`)
  return (await response.json()) as SealedLiveQuery<JobRow>
}

/** Resolves once the job's row is no longer running; rejects if live updates fail. */
async function watchLive(jobId: string, onSteps: (steps: string[]) => void): Promise<void> {
  realtime ??= createRealtimeClient({ url: REALTIME_URL! })
  const sealed = await sealJobQuery(jobId)
  const subscription = realtime.subscribe(sealed)

  let timer: ReturnType<typeof setTimeout> | undefined
  const renewBefore = (expiresAt: number) => {
    clearTimeout(timer)
    timer = setTimeout(async () => {
      try {
        const next = await sealJobQuery(jobId)
        await subscription.renew(next)
        renewBefore(next.expiresAt)
      } catch {
        renewBefore(Date.now() + RENEW_EARLY_MS + 1000) // retry in a second
      }
    }, Math.max(0, expiresAt - Date.now() - RENEW_EARLY_MS))
  }
  renewBefore(sealed.expiresAt)

  try {
    await new Promise<void>((resolve, reject) => {
      subscription.onChange((snapshot) => {
        if (snapshot.status === 'error') {
          reject(snapshot.error)
          return
        }
        const row = snapshot.data?.[0]
        if (!row) return
        onSteps(row.steps ?? [])
        if (row.status !== 'running') resolve()
      })
    })
  } finally {
    clearTimeout(timer)
    subscription.unsubscribe()
  }
}

export async function waitForPlan(
  started: PlanningJob,
  onSteps: (steps: string[]) => void,
): Promise<PlanningJob> {
  let job = started
  onSteps(job.steps)

  if (job.status === 'running' && !USE_MOCK && REALTIME_URL && LIVE_URL) {
    try {
      await watchLive(job.id, onSteps)
      job = await fetchPlanningJob(job.id)
    } catch (error) {
      console.warn('[planning] live updates unavailable, polling instead', error)
    }
  }

  while (job.status === 'running') {
    await new Promise((done) => setTimeout(done, POLL_MS))
    job = await fetchPlanningJob(job.id)
    onSteps(job.steps)
  }
  if (job.status === 'failed') {
    throw new ApiError(job.errorStatus ?? 500, job.error ?? 'Planning failed')
  }
  return job
}
