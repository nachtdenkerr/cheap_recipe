"""Engine and session factory.

`DATABASE_URL` picks the database; without it a SQLite file under data/ is
used, so the API runs locally with no setup.
"""

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cheaprecipe.config import DATA_DIR, load_keys
from cheaprecipe.db.models import Base


def database_url() -> str:
    load_keys()
    return os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'cheaprecipe.db'}"


def make_engine(url: str | None = None, **kwargs) -> Engine:
    url = url or database_url()
    if url.startswith("sqlite"):
        # FastAPI serves requests from a thread pool; SQLite's default refuses that.
        kwargs.setdefault("connect_args", {"check_same_thread": False})
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        # SQLite ignores ON DELETE CASCADE unless foreign keys are switched on.
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind: Engine = engine) -> None:
    """Create any missing tables. No migrations yet, so this is the schema step."""
    Base.metadata.create_all(bind)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
