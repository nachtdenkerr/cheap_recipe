/**
 * Waiting for a planning job (app/jobs.py): poll it, pass each new step on,
 * and resolve with the finished job — or reject with the ApiError the plain
 * request would have given (409 no offers, 429 quota…).
 */

import { ApiError, fetchPlanningJob } from './client'
import type { PlanningJob } from './types'

const POLL_MS = 1000

export async function waitForPlan(
  started: PlanningJob,
  onSteps: (steps: string[]) => void,
): Promise<PlanningJob> {
  let job = started
  onSteps(job.steps)
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
