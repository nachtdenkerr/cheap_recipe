"""Planning as a background job, so the page can show what is happening.

A plan takes minutes — the planner agent and the critic, round after round —
and one request that long looks frozen. A job runs the same code as
POST /generate and /generate/refine, after the response that started it,
and records the steps planning reports (cheaprecipe/observability/progress.py).

Jobs are rows in `planning_job`, so the page can watch one live: the `live`
Neon Function seals a Realtime query over the row and the page subscribes
to its status and steps (frontend/src/api/planning.ts). GET /generate/jobs/{id}
still answers too, and carries the result once the job is done.

One running job per user: starting another returns the one already running.
A job left running by an API that stopped is marked failed when the next one
starts (`fail_abandoned`), so the user can plan again.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from cheaprecipe.db.models import PlanningJob
from cheaprecipe.observability import progress

log = logging.getLogger(__name__)

ABANDONED = "Planning stopped when the server restarted; please plan again."


def _now() -> datetime:
    # Naive UTC, like the column (DateTime without a time zone).
    return datetime.now(UTC).replace(tzinfo=None)


def running_for(session: Session, user_id: int) -> PlanningJob | None:
    return session.scalars(
        select(PlanningJob).where(PlanningJob.user_id == user_id, PlanningJob.status == "running")
    ).first()


def create(session: Session, user_id: int, kind: str) -> PlanningJob:
    job = PlanningJob(id=uuid.uuid4().hex, user_id=user_id, kind=kind, status="running", steps=[])
    session.add(job)
    session.commit()
    return job


def get(session: Session, job_id: str, user_id: int) -> PlanningJob | None:
    """A job, only for the user who started it."""
    job = session.get(PlanningJob, job_id)
    return job if job is not None and job.user_id == user_id else None


def fail_abandoned(factory: sessionmaker) -> int:
    """Mark jobs a previous API process left running as failed."""
    with factory() as session:
        count = session.execute(
            update(PlanningJob)
            .where(PlanningJob.status == "running")
            .values(status="failed", error=ABANDONED, error_status=503, finished_at=_now())
        ).rowcount
        session.commit()
    if count:
        log.info("marked %d planning job(s) from before the restart as failed", count)
    return count


def run(
    factory: sessionmaker,
    job_id: str,
    work: Callable[[], object],
    serialize: Callable[[object], dict],
) -> None:
    """Run `work` for the job, recording its steps, its result or its error.

    Each step is its own short write, so a live subscriber sees it as it
    happens; `serialize` turns the result into what the row keeps.
    """
    steps: list[str] = []

    def save(**values) -> None:
        with factory() as session:
            session.execute(update(PlanningJob).where(PlanningJob.id == job_id).values(**values))
            session.commit()

    def step(text: str) -> None:
        if steps and steps[-1] == text:
            return
        steps.append(text)
        try:
            save(steps=list(steps))
        except Exception:  # a lost step must not stop the plan
            log.warning("could not record a step of planning job %s", job_id, exc_info=True)

    outcome: dict
    try:
        with progress.listening(step):
            result = work()
    except HTTPException as exc:
        # What the plain request would have answered: 409 no offers, 429 quota…
        outcome = {"status": "failed", "error": str(exc.detail), "error_status": exc.status_code}
    except Exception:  # anything else: the page must still hear the job ended
        log.exception("planning job %s failed", job_id)
        outcome = {"status": "failed", "error": "Planning failed; please try again.", "error_status": 500}
    else:
        outcome = {"status": "done", "result": serialize(result)}
    save(**outcome, finished_at=_now())
    log.info("planning job %s %s after %d steps", job_id, outcome["status"], len(steps))
