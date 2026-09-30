"""The migrations (db/migrations) build the schema the models describe."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from cheaprecipe.db.models import Base
from cheaprecipe.db.session import BASELINE, make_engine, migrate


def test_the_migrations_build_exactly_the_models(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    migrate(engine)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        # A model change without its migration shows up here.
        assert compare_metadata(context, Base.metadata) == []


def test_a_database_from_before_migrations_keeps_its_data(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    # The baseline's schema, as create_all made it — then a user in it.
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE generation DROP COLUMN assessment"))
        connection.execute(text("ALTER TABLE generation DROP COLUMN rounds"))
        connection.execute(text(
            "INSERT INTO user_account (username, email, password_hash) VALUES ('nga', 'n@x.test', 'x')"
        ))

    migrate(engine)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) != BASELINE
        assert connection.scalar(text("SELECT username FROM user_account")) == "nga"
    columns = {c["name"] for c in inspect(engine).get_columns("generation")}
    assert {"assessment", "rounds"} <= columns


def test_migrating_twice_changes_nothing(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'twice.db'}")
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 1
