"""The signed-in user and their preferences.

Signing up and in happen in Neon Auth (app/security.py); the account here is
made on the first request a new Neon Auth user sends (app/deps.py).
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import scheduler
from app.deps import CurrentUser, SessionDep
from app.presenters import user_out
from app.schemas.auth import PreferencesUpdate
from app.schemas.auth import User as UserOut
from cheaprecipe.db.load import chain_of
from cheaprecipe.db.models import Address, UserPreference
from cheaprecipe.refresh import offers_loaded

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.post("/me/preferences")
def update_preferences(
    body: PreferencesUpdate, user: CurrentUser, session: SessionDep, background: BackgroundTasks
) -> UserOut:
    """Change the fields sent and leave the rest; returns the updated user.

    A home market whose offers are not loaded yet this week is refreshed in
    the background right after the response, so a new user can plan within
    minutes instead of waiting for Monday.
    """
    changes = body.model_dump(exclude_unset=True)
    pref = user.preference or UserPreference(user=user)

    if "name" in changes:
        user.fullname = changes.pop("name")
    stale: list[tuple[str, str]] = []
    if "home_market_ids" in changes:
        ids = list(dict.fromkeys(changes.pop("home_market_ids") or []))
        markets = list(session.scalars(select(Address).where(Address.id.in_(ids))))
        if len(markets) != len(ids):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown market; search for it first"
            )
        pref.home_markets = sorted(markets, key=lambda m: ids.index(m.id))
        stale = [
            (chain_of(m), m.market_id)
            for m in markets
            if not offers_loaded(session, chain_of(m), m.market_id)
        ]
    for field, value in changes.items():
        setattr(pref, field, value)

    session.add(pref)
    session.commit()
    if stale:
        factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
        background.add_task(scheduler.refresh_now, factory, stale)
    return user_out(user)
