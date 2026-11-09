"""Shared FastAPI dependencies (db session, current user)."""

import re
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.security import AuthNotConfigured, read_token
from cheaprecipe.db.models import User, UserPreference
from cheaprecipe.db.session import get_session

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[Session, Depends(get_session)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"}
    )


def _free_username(session: Session, email: str) -> str:
    """A username from the email's local part, made unique (max 30 characters)."""
    base = re.sub(r"[^a-z0-9_.-]", "", email.split("@")[0].lower())[:24] or "cook"
    base = base if len(base) >= 3 else f"{base}cook"
    candidate, n = base, 1
    while session.scalars(select(User.id).where(User.username == candidate)).first() is not None:
        n += 1
        candidate = f"{base}{n}"
    return candidate


def account_for(session: Session, claims: dict, client_ip: str | None = None) -> User:
    """The local account behind a Neon Auth identity, made on first sign-in.

    An account from before Neon Auth (no auth_user_id) is taken over only by
    a Neon Auth user who has verified that email; anyone else could sign up
    with someone's address and walk into their account.
    """
    sub = claims["sub"]
    user = session.scalars(select(User).where(User.auth_user_id == sub)).first()
    if user is not None:
        return user

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise _unauthorized()
    existing = session.scalars(select(User).where(func.lower(User.email) == email)).first()
    if existing is not None:
        if existing.auth_user_id is None and claims.get("emailVerified") is True:
            existing.auth_user_id = sub
            existing.last_login, existing.last_login_ip = func.now(), client_ip
            session.commit()
            return existing
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account with this email already exists; verify your email to use it.",
        )

    user = User(
        auth_user_id=sub,
        username=_free_username(session, email),
        email=email,
        fullname=claims.get("name") or None,
        preference=UserPreference(),
        last_login=func.now(),
        last_login_ip=client_ip,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Two first requests at once: the other one made the account.
        session.rollback()
        user = session.scalars(select(User).where(User.auth_user_id == sub)).first()
        if user is None:
            raise
    return user


def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Resolve the authenticated user from the `Authorization: Bearer` Neon Auth JWT."""
    if credentials is None:
        raise _unauthorized()
    try:
        claims = read_token(credentials.credentials)
    except AuthNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    if claims is None:
        raise _unauthorized()
    return account_for(session, claims, request.client.host if request.client else None)


CurrentUser = Annotated[User, Depends(get_current_user)]
