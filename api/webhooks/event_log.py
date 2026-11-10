"""Best-effort event logging into gangster_god.db.

Uses the repo's own database module (ggos/database.py) — same schema,
same idempotency — never raw sqlite3 strings with guessed columns.
(The pasted autopatcher version assumed a 5-column events table;
the real one has 8 columns in a different order. That INSERT fails.)

DB path: GGOS_DB_PATH env, else <repo root>/data/gangster_god.db
(the same default ggos/config.py uses).

Logging must never fail the webhook: any error is printed and
swallowed so the HTTP 200 still goes out.
"""
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def db_path():
    return Path(
        os.environ.get("GGOS_DB_PATH") or (REPO_ROOT / "data" / "gangster_god.db")
    )


def log_event(event_type, source, payload, external_id=None):
    """Insert one event row. Returns the row id, or None if logging failed."""
    try:
        from ggos import database as db

        path = db_path()
        db.init_db(path)
        conn = db.get_connection(path)
        try:
            result = db.insert_event(
                conn,
                event_type,
                source=source,
                external_id=external_id,
                description=None,
                data=json.dumps(payload, default=str),
            )
            return result["id"]
        finally:
            conn.close()
    except Exception as exc:  # logging must never break the webhook
        print(f"event log failed ({event_type}/{source}): {exc}")
        return None
