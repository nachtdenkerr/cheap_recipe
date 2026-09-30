"""Alembic's entry point: the models' metadata, and the database to migrate.

Called by the `alembic` command and by session.migrate, which hands over its
own connection (config.attributes["connection"]) so the API migrates the
engine it serves. SQLite cannot ALTER most things in place, hence batch mode:
Alembic copies the table instead.
"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from cheaprecipe.db.models import Base
from cheaprecipe.db.session import database_url

config = context.config
target_metadata = Base.metadata


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url") or database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        return
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = config.get_main_option("sqlalchemy.url") or database_url()
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        _configure(connection)


if context.is_offline_mode():
    run_offline()
else:
    run_online()
