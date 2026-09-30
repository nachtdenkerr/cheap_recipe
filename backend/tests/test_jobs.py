"""The planning job registry (app/jobs.py)."""

from fastapi import HTTPException

from app import jobs
from cheaprecipe.observability import progress


def test_a_job_records_its_steps_and_result():
    job = jobs.create(user_id=1, kind="weekly")
    assert jobs.running_for(1) is job  # one at a time: starting again returns this one

    def work():
        progress.report("Checking this week's offers")
        progress.report("Checking this week's offers")  # the same step once
        progress.report("The critic is reviewing the week")
        return ["a week"]

    jobs.run(job, work)
    assert (job.status, job.result) == ("done", ["a week"])
    assert job.steps == ["Checking this week's offers", "The critic is reviewing the week"]
    assert jobs.running_for(1) is None


def test_a_job_fails_with_the_requests_answer():
    job = jobs.create(user_id=2, kind="refine")

    def work():
        raise HTTPException(429, "No requests left this week")

    jobs.run(job, work)
    assert (job.status, job.error_status, job.error) == ("failed", 429, "No requests left this week")


def test_an_unexpected_error_is_a_failed_job_not_a_crash():
    job = jobs.create(user_id=3, kind="weekly")
    jobs.run(job, lambda: 1 / 0)
    assert (job.status, job.error_status) == ("failed", 500)


def test_only_its_user_sees_a_job():
    job = jobs.create(user_id=4, kind="weekly")
    assert jobs.get(job.id, 4) is job and jobs.get(job.id, 5) is None


def test_nothing_listens_outside_a_job():
    progress.report("ignored")  # no error, no effect
