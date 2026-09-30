"""The weekly limit on follow-up recipe requests.

Every plan runs the planner agent and the critic (LLM tokens) and may search
Spoonacular, so each user gets one weekly plan (kind "weekly") and
REFINES_PER_WEEK follow-up requests per calendar week, Monday to Sunday in
German time.

Only successful requests count: the Generation row is written after the
planner returns, so a failed run leaves nothing to count.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas.generate import RefineQuota
from cheaprecipe.db.models import Generation, User

REFINES_PER_WEEK = 2

# Offer weeks follow the German stores' calendar.
STORE_TZ = ZoneInfo("Europe/Berlin")


def _now() -> datetime:
    """Seam for tests to freeze the clock."""
    return datetime.now(UTC)


def week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """This week's [Monday 00:00, next Monday 00:00) in Berlin, as naive UTC.

    Naive UTC because `created_at` is filled by the database's CURRENT_TIMESTAMP.
    """
    local = (now or _now()).astimezone(STORE_TZ)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # Wall-clock arithmetic on a ZoneInfo datetime, so a DST switch during the
    # week still lands on midnight.
    next_monday = monday + timedelta(days=7)
    return (
        monday.astimezone(UTC).replace(tzinfo=None),
        next_monday.astimezone(UTC).replace(tzinfo=None),
    )


def generations_this_week(session: Session, user: User, kind: str) -> int:
    start, end = week_bounds()
    return session.scalar(
        select(func.count())
        .select_from(Generation)
        .where(
            Generation.user_id == user.id,
            Generation.kind == kind,
            Generation.created_at >= start,
            Generation.created_at < end,
        )
    ) or 0


def refine_quota(session: Session, user: User) -> RefineQuota:
    used = generations_this_week(session, user, "refine")
    _, resets_at = week_bounds()
    return RefineQuota(
        used=used,
        limit=REFINES_PER_WEEK,
        remaining=max(REFINES_PER_WEEK - used, 0),
        resets_at=resets_at.replace(tzinfo=UTC),
        weekly_plan_done=generations_this_week(session, user, "weekly") > 0,
    )
