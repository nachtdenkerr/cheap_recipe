"""Auth endpoints: signup, login, the signed-in user and their preferences."""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, or_, select

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
from cheaprecipe.db.models import Supermarket, User, UserPreference

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
    body: PreferencesUpdate, user: CurrentUser, session: SessionDep
) -> UserOut:
    """Change the fields sent and leave the rest; returns the updated user."""
    changes = body.model_dump(exclude_unset=True)
    pref = user.preference or UserPreference(user=user)

    if "name" in changes:
        user.fullname = changes.pop("name")
    if "market" in changes:
        name = changes.pop("market")
        market = None
        if name is not None:
            market = session.scalars(
                select(Supermarket).where(Supermarket.name.ilike(name))
            ).first()
            if market is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown supermarket {name!r}"
                )
        pref.fav_supermarket = market
    for field, value in changes.items():
        setattr(pref, field, value)

    session.add(pref)
    session.commit()
    return user_out(user)
