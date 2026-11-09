"""Copy the local SQLite database into Postgres (Neon), table by table.

    uv run python scripts/copy_sqlite_to_postgres.py                 # data/cheaprecipe.db → DATABASE_URL
    uv run python scripts/copy_sqlite_to_postgres.py --source other.db

The target is migrated first (over the direct URL), then every table the
models know is copied in foreign-key order, in one transaction, and each
integer id sequence is moved past the copied ids. It refuses a target that
already has rows, so it cannot double up data; the SQLite file is only read.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import func, inspect, select, text

from cheaprecipe.config import DATA_DIR
from cheaprecipe.db.models import Base
from cheaprecipe.db.session import database_url, init_db, make_engine, migration_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=DATA_DIR / "cheaprecipe.db")
    args = parser.parse_args()

    target_url = database_url()
    if not target_url.startswith("postgresql"):
        print("DATABASE_URL is not a Postgres URL; nothing to copy into.", file=sys.stderr)
        return 2
    if not args.source.exists():
        print(f"{args.source} does not exist.", file=sys.stderr)
        return 2

    source = make_engine(f"sqlite:///{args.source}")
    # The direct URL: one long transaction, and setval, have no business on a pooler.
    target = make_engine(migration_url())
    init_db()

    source_tables = set(inspect(source).get_table_names())
    tables = [t for t in Base.metadata.sorted_tables if t.name in source_tables]

    with target.connect() as conn:
        busy = [t.name for t in tables if conn.scalar(select(func.count()).select_from(t))]
    if busy:
        print(f"The target already has rows in: {', '.join(busy)}. Not copying.", file=sys.stderr)
        return 1

    copied: dict[str, int] = {}
    with source.connect() as src, target.begin() as dst:
        for table in tables:
            present = {c["name"] for c in inspect(source).get_columns(table.name)}
            columns = [c for c in table.columns if c.name in present]
            rows = [dict(row._mapping) for row in src.execute(select(*columns))]
            if rows:
                dst.execute(table.insert(), rows)
            copied[table.name] = len(rows)

        # Postgres hands out ids from a sequence that knows nothing of the copied rows.
        for table in tables:
            pk = list(table.primary_key.columns)
            if len(pk) == 1 and pk[0].autoincrement in (True, "auto") and pk[0].type.python_type is int:
                dst.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk[0].name}'), "
                    f"COALESCE((SELECT MAX({pk[0].name}) FROM {table.name}), 0) + 1, false)"
                ))

    for name, count in copied.items():
        print(f"{name:24} {count:6}")
    print(f"copied {sum(copied.values())} rows from {args.source.name} into {target.url.host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
