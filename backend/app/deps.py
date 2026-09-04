"""Shared FastAPI dependencies (db session, current user, settings)."""

from collections.abc import Iterator


def get_session() -> Iterator[None]:
    """Yield a database session; wired up once db/ exists."""
    raise NotImplementedError


def get_current_user() -> None:
    """Resolve the authenticated user from the request."""
    raise NotImplementedError
