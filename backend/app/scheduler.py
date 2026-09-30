"""Runs the weekly refresh (cheaprecipe/refresh.py) from inside the API.

A background task started with the app checks every REFRESH_CHECK_MINUTES
whether this week's refresh is due and not yet done, for every branch that
some user has as a home market, and runs it once per branch. Due means: it is
Monday REFRESH_HOUR:00 German time or later in the same week — so a server
that was off on Monday catches up when it starts. A branch someone chooses
mid-week is refreshed right away (`refresh_now`), not next Monday.

The WeeklyRefresh row is the lock. Inserting (store, week) is atomic, so of
two API processes only one wins; a run stuck in "running" for longer than
STALE_AFTER counts as crashed and may be taken over; a failed run is retried
after RETRY_AFTER, at most MAX_ATTEMPTS times a week.

    WEEKLY_REFRESH=off           don't run it (tests, or a cron runs `cheaprecipe weekly`)
    REFRESH_HOUR=5               from when on Monday
    REFRESH_CHECK_MINUTES=30     how often to check
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from cheaprecipe.config import load_keys
from cheaprecipe.db.adapters import STORE_TZ
from cheaprecipe.db.load import chain_of
from cheaprecipe.db.models import WeeklyRefresh
from cheaprecipe.refresh import markets_in_use, week_start, weekly_refresh

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=2)
RETRY_AFTER = timedelta(hours=1)
MAX_ATTEMPTS = 3


def _setting(name: str, default: str) -> str:
    load_keys()
    return os.environ.get(name, default).strip()


def enabled() -> bool:
    return _setting("WEEKLY_REFRESH", "on").lower() not in {"off", "false", "0", "no"}


def is_due(now: datetime) -> bool:
    """From Monday REFRESH_HOUR:00 (German time) on, for the rest of the week."""
    local = now.astimezone(STORE_TZ)
    monday_at = datetime.combine(
        week_start(local), datetime.min.time(), tzinfo=STORE_TZ
    ) + timedelta(hours=int(_setting("REFRESH_HOUR", "5")))
    return local >= monday_at


def _claim(session: Session, store: str, now: datetime) -> WeeklyRefresh | None:
    """Take this week's run for `store`, or None if it is done or someone else has it."""
    week = week_start(now)
    naive_now = now.astimezone(STORE_TZ).replace(tzinfo=None)
    row = session.scalars(
        select(WeeklyRefresh).where(WeeklyRefresh.store == store, WeeklyRefresh.week_start == week)
    ).first()
    if row is None:
        row = WeeklyRefresh(store=store, week_start=week, status="running", started_at=naive_now)
        session.add(row)
        try:
            session.commit()
        except IntegrityError:  # another process claimed it first
            session.rollback()
            return None
        return row
    if row.status == "done":
        return None
    if row.status == "running" and naive_now - row.started_at < STALE_AFTER:
        return None
    if row.status == "failed" and (
        row.attempts >= MAX_ATTEMPTS
        or naive_now - (row.finished_at or row.started_at) < RETRY_AFTER
    ):
        return None
    row.status, row.started_at, row.attempts = "running", naive_now, row.attempts + 1
    session.commit()
    return row


def run_due(
    factory: sessionmaker,
    now: datetime | None = None,
    branches: list[tuple[str, str]] | None = None,
    check_due: bool = True,
) -> list[str]:
    """Run every branch's refresh that is due and unclaimed; returns the branches run.

    `branches` are (chain, market id) pairs; by default, every home market in use.
    """
    now = now or datetime.now(STORE_TZ)
    if not enabled() or (check_due and not is_due(now)):
        return []
    if branches is None:
        with factory() as session:
            branches = [(chain_of(b), b.market_id) for b in markets_in_use(session)]
    ran = []
    for chain, market_id in branches:
        key = f"{chain}:{market_id}"
        with factory() as session:
            row = _claim(session, key, now)
            if row is None:
                continue
            log.info("weekly refresh for %s, week of %s (attempt %d)", key, row.week_start, row.attempts)
            try:
                summary = weekly_refresh(session, chain, market_id)
            except Exception as exc:
                session.rollback()
                log.exception("weekly refresh for %s failed", key)
                row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
            else:
                row.status, row.error, row.summary = "done", None, summary.as_dict()
            row.finished_at = datetime.now(STORE_TZ).replace(tzinfo=None)
            session.commit()
            ran.append(key)
    return ran


def refresh_now(factory: sessionmaker, branches: list[tuple[str, str]]) -> list[str]:
    """Refresh these branches now, if not done this week — a newly chosen home market."""
    return run_due(factory, branches=branches, check_due=False)


async def refresh_loop(factory: sessionmaker, stop: asyncio.Event) -> None:
    """Check on a timer until `stop` is set; the work runs in a thread."""
    interval = 60 * float(_setting("REFRESH_CHECK_MINUTES", "30"))
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_due, factory)
        except Exception:  # never let the loop die
            log.exception("weekly refresh check failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
