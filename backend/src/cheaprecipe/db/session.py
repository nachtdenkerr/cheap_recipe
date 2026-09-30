"""Engine and session factory.

`DATABASE_URL` picks the database; without it a SQLite file under data/ is
used, so the API runs locally with no setup.
"""

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cheaprecipe.config import DATA_DIR, load_keys
from cheaprecipe.db.models import Base  # noqa: F401 — the models, for the migrations

if TYPE_CHECKING:
    from alembic.config import Config

log = logging.getLogger(__name__)


def database_url() -> str:
    load_keys()
    return os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'cheaprecipe.db'}"


def make_engine(url: str | None = None, **kwargs) -> Engine:
    url = url or database_url()
    if url.startswith("sqlite"):
        # FastAPI serves requests from a thread pool; SQLite's default refuses that.
        # The weekly refresh writes from a background thread too: wait for its
        # lock instead of failing with "database is locked".
        kwargs.setdefault("connect_args", {"check_same_thread": False, "timeout": 30})
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


MIGRATIONS = Path(__file__).with_name("migrations")
# The first migration: the schema as it stood when migrations began.
BASELINE = "0001"


def _alembic(connection) -> "Config":
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["connection"] = connection
    return config


def migrate(bind: Engine = engine) -> None:
    """Bring the database's schema up to date (db/migrations).

    A database made before migrations existed — tables, but no alembic_version
    — is stamped as the baseline first, so its data is kept and only later
    migrations run on it.
    """
    from alembic import command

    with bind.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        config = _alembic(connection)
        if tables and "alembic_version" not in tables:
            log.info("database predates migrations: stamping it as the baseline %s", BASELINE)
            command.stamp(config, BASELINE)
        command.upgrade(config, "head")


def init_db(bind: Engine = engine) -> None:
    """The schema step: every migration applied (`migrate`)."""
    migrate(bind)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
