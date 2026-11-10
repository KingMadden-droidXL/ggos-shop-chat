"""Regenerate data/schema.sql from ggos/database.py MIGRATIONS.

Run from the repo root:  python -m scripts.dump_schema
"""
from pathlib import Path
import sqlite3
import tempfile

from ggos import database as db


def main():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "schema.db"
        version = db.init_db(p)
        conn = sqlite3.connect(str(p))
        lines = [
            "-- gangster_god.db schema — GENERATED from ggos/database.py MIGRATIONS",
            f"-- (schema v{version}). Load into Turso with:",
            "--   turso db shell gangster-god < data/schema.sql",
            "-- Regenerate: python -m scripts.dump_schema",
            "",
        ]
        for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
            " AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ):
            lines.append(row[0].rstrip(";") + ";")
        conn.close()
    out = Path("data/schema.sql")
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out} (schema v{version})")


if __name__ == "__main__":
    main()
