"""Planning as a background job, so the page can show what is happening.

A plan takes minutes — the planner agent and the critic, round after round —
and one request that long looks frozen. A job runs the same code as
POST /generate and /generate/refine, after the response that started it,
and records the steps planning reports (cheaprecipe/observability/progress.py)
for the page to poll.

In memory: jobs belong to this API process, and a restart loses the running
ones (the plan is not saved, so the user just plans again). One running job
per user: starting another returns the one already running.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from cheaprecipe.observability import progress

log = logging.getLogger(__name__)

# Finished jobs are kept this long for the page to collect.
KEEP_FOR = timedelta(hours=1)


@dataclass
class Job:
    id: str
    user_id: int
    kind: str  # "weekly" or "refine"
    status: str = "running"  # running | done | failed
    steps: list[str] = field(default_factory=list)
    result: object | None = None
    error: str | None = None
    error_status: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _prune(now: datetime) -> None:
    for job_id, job in list(_jobs.items()):
        if job.finished_at and now - job.finished_at > KEEP_FOR:
            del _jobs[job_id]


def running_for(user_id: int) -> Job | None:
    with _lock:
        return next((j for j in _jobs.values() if j.user_id == user_id and j.status == "running"), None)


def create(user_id: int, kind: str) -> Job:
    with _lock:
        _prune(datetime.now(UTC))
        job = Job(id=uuid.uuid4().hex, user_id=user_id, kind=kind)
        _jobs[job.id] = job
        return job


def get(job_id: str, user_id: int) -> Job | None:
    """A job, only for the user who started it."""
    with _lock:
        job = _jobs.get(job_id)
    return job if job is not None and job.user_id == user_id else None


def run(job: Job, work: Callable[[], object]) -> None:
    """Run `work` for `job`, recording its steps, its result or its error."""

    def step(text: str) -> None:
        with _lock:
            if not job.steps or job.steps[-1] != text:
                job.steps.append(text)

    try:
        with progress.listening(step):
            result = work()
    except HTTPException as exc:
        # What the plain request would have answered: 409 no offers, 429 quota…
        job.status, job.error, job.error_status = "failed", str(exc.detail), exc.status_code
    except Exception:  # anything else: the page must still hear the job ended
        log.exception("planning job %s failed", job.id)
        job.status, job.error, job.error_status = "failed", "Planning failed; please try again.", 500
    else:
        job.status, job.result = "done", result
    job.finished_at = datetime.now(UTC)
    log.info("planning job %s (%s) %s after %d steps", job.id, job.kind, job.status, len(job.steps))
