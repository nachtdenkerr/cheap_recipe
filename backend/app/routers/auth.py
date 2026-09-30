"""Auth endpoints: signup, login, the signed-in user and their preferences."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import sessionmaker

from app import scheduler
from app.deps import CurrentUser, SessionDep
from app.presenters import user_out
from app.schemas.auth import (
    AuthSession,
    LoginRequest,
    PreferencesUpdate,
    SignupRequest,
)
from app.schemas.auth import (
    User as UserOut,
)
from app.security import hash_password, issue_token, verify_password
from cheaprecipe.db.load import chain_of
from cheaprecipe.db.models import Address, User, UserPreference
from cheaprecipe.refresh import offers_loaded

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, session: SessionDep) -> AuthSession:
    taken = session.scalars(
        select(User).where(or_(User.username == body.username, User.email == body.email))
    ).first()
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already registered")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        fullname=body.name,
        preference=UserPreference(),
    )
    session.add(user)
    session.commit()
    return AuthSession(token=issue_token(user.id), user=user_out(user))


@router.post("/login")
def login(body: LoginRequest, request: Request, session: SessionDep) -> AuthSession:
    user = session.scalars(select(User).where(User.email == body.email)).first()
    # The same answer for an unknown email and a wrong password, so the
    # endpoint cannot be used to find out who has an account.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")

    # The database clock, like created_at, so the two are comparable.
    user.last_login = func.now()
    user.last_login_ip = request.client.host if request.client else None
    session.commit()
    return AuthSession(token=issue_token(user.id), user=user_out(user))


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
