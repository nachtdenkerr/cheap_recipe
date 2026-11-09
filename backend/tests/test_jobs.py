"""The planning job store (app/jobs.py), in the planning_job table."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import jobs
from cheaprecipe.db.models import PlanningJob, User
from cheaprecipe.db.session import init_db, make_engine
from cheaprecipe.observability import progress


@pytest.fixture
def factory():
    engine = make_engine("sqlite://", poolclass=StaticPool)
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(User(id=i, username=f"u{i}", email=f"u{i}@x.test") for i in range(1, 6))
        session.commit()
    return factory


def _reload(factory, job_id) -> PlanningJob:
    with factory() as session:
        return session.get(PlanningJob, job_id)


def _as_dict(result):
    return {"recipes": result}


def test_a_job_records_its_steps_and_result(factory):
    with factory() as session:
        job = jobs.create(session, user_id=1, kind="weekly")
        # One at a time: starting again returns this one.
        assert jobs.running_for(session, 1).id == job.id

    def work():
        progress.report("Checking this week's offers")
        progress.report("Checking this week's offers")  # the same step once
        progress.report("The critic is reviewing the week")
        # Each step is written as it happens, for a live subscriber.
        assert _reload(factory, job.id).steps == [
            "Checking this week's offers", "The critic is reviewing the week",
        ]
        return ["a week"]

    jobs.run(factory, job.id, work, _as_dict)
    done = _reload(factory, job.id)
    assert (done.status, done.result) == ("done", {"recipes": ["a week"]})
    assert done.finished_at is not None
    with factory() as session:
        assert jobs.running_for(session, 1) is None


def test_a_job_fails_with_the_requests_answer(factory):
    with factory() as session:
        job = jobs.create(session, user_id=2, kind="refine")

    def work():
        raise HTTPException(429, "No requests left this week")

    jobs.run(factory, job.id, work, _as_dict)
    failed = _reload(factory, job.id)
    assert (failed.status, failed.error_status, failed.error) == ("failed", 429, "No requests left this week")


def test_an_unexpected_error_is_a_failed_job_not_a_crash(factory):
    with factory() as session:
        job = jobs.create(session, user_id=3, kind="weekly")
    jobs.run(factory, job.id, lambda: 1 / 0, _as_dict)
    assert (_reload(factory, job.id).status, _reload(factory, job.id).error_status) == ("failed", 500)


def test_only_its_user_sees_a_job(factory):
    with factory() as session:
        job = jobs.create(session, user_id=4, kind="weekly")
        assert jobs.get(session, job.id, 4).id == job.id
        assert jobs.get(session, job.id, 5) is None


def test_a_job_left_running_by_a_stopped_api_fails(factory):
    with factory() as session:
        job = jobs.create(session, user_id=5, kind="weekly")
    assert jobs.fail_abandoned(factory) == 1
    abandoned = _reload(factory, job.id)
    assert (abandoned.status, abandoned.error) == ("failed", jobs.ABANDONED)


def test_nothing_listens_outside_a_job():
    progress.report("ignored")  # no error, no effect
