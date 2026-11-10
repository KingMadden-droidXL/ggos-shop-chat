"""The ONE schema module. All tables are created here, migrations are tracked
in schema_version, and init_db() is idempotent — safe to run on every boot.

The old codebase had two competing schemas and relative DB paths that
silently created different database files. That is gone: one module,
one absolute path (see ggos.config.DB_PATH).
"""
import json
import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 3

_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    event_type TEXT NOT NULL,
    source TEXT,
    external_id TEXT,
    agent_name TEXT,
    description TEXT,
    data TEXT,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (event_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_source ON events (source, external_id);

CREATE TABLE IF NOT EXISTS money (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    description TEXT,
    metadata TEXT,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_money_source ON money (source, external_id);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    agent_name TEXT NOT NULL,
    action TEXT NOT NULL,
    rationale TEXT,
    approved INTEGER NOT NULL DEFAULT 0,
    executed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    labels TEXT
);
CREATE INDEX IF NOT EXISTS idx_telemetry_metric_time ON telemetry (metric, timestamp);

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'idle',
    config TEXT
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_name ON agent_runs (agent_name, started_at);

CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    agent_name TEXT,
    key TEXT NOT NULL,
    value TEXT NOT NULL
);
"""

_MIGRATION_2 = """
-- Operations queue: real task lifecycle, no fake auto-execution.
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, created_at);

-- Standard operating procedures: named step lists triggered by event types.
CREATE TABLE IF NOT EXISTS sops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    trigger_event TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sops_trigger ON sops (trigger_event);

-- Prompt pipeline runs: stores real inputs and real outputs only.
-- Nothing here generates content; callers record what actually happened.
CREATE TABLE IF NOT EXISTS prompt_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_type TEXT NOT NULL,
    input_raw TEXT NOT NULL,
    outputs_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_prompt_runs_type ON prompt_runs (pipeline_type, created_at);
"""

_MIGRATION_3 = """
-- Paper predictions: a record of a price/score at scan time, evaluated
-- later against the real price after the horizon. No money, no trades.
-- change_24h_pct keeps the DIRECTION of the past move, because raw_alpha
-- alone (its size) cannot test whether moves keep going the same way.
CREATE TABLE IF NOT EXISTS paper_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin_id TEXT NOT NULL,
    decision_id INTEGER,
    scanned_at TEXT NOT NULL,
    price_usd REAL NOT NULL CHECK (price_usd > 0),
    change_24h_pct REAL NOT NULL,
    composite_score REAL NOT NULL,
    raw_alpha REAL NOT NULL,
    volatility REAL NOT NULL,
    horizon_hours REAL NOT NULL DEFAULT 24 CHECK (horizon_hours >= 0),
    evaluated_at TEXT,
    eval_price_usd REAL,
    forward_return_pct REAL,
    UNIQUE (coin_id, scanned_at, horizon_hours)
);
CREATE INDEX IF NOT EXISTS idx_paper_pending
    ON paper_predictions (evaluated_at, scanned_at);
"""

MIGRATIONS = {1: _MIGRATION_1, 2: _MIGRATION_2, 3: _MIGRATION_3}


def is_turso():
    """True when the cloud DB is configured (TURSO_DATABASE_URL set)."""
    return bool(os.environ.get("TURSO_DATABASE_URL"))


def _fetchdicts(cursor):
    """Rows as dicts via cursor.description — works for sqlite3.Row AND
    for libsql tuples (libsql has no row_factory).

    NOTE: libsql requires query parameters as a TUPLE, not a list —
    always pass tuple(params). sqlite3 accepts both."""

    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _fetchone_dict(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


def get_connection(db_path=None):
    """Local sqlite3 by default. Set TURSO_DATABASE_URL (+ optional
    TURSO_AUTH_TOKEN) to use the cloud Turso/libSQL database instead —
    same schema, same functions. Set GGOS_USE_LIBSQL=1 to run the
    libsql client against a local file (used by the Turso tests).

    UNTESTED: the remote Turso path has no credentials on file yet, so
    it has never run against a real Turso database. The libsql-local
    path IS tested (tests/test_turso.py).
    """
    if is_turso():
        import libsql_experimental as libsql

        return libsql.connect(
            os.environ["TURSO_DATABASE_URL"],
            auth_token=os.environ.get("TURSO_AUTH_TOKEN"),
        )
    if os.environ.get("GGOS_USE_LIBSQL") == "1":
        import libsql_experimental as libsql

        return libsql.connect(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def current_version(conn):
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not exists:
        return 0
    row = _fetchone_dict(conn.execute("SELECT MAX(version) AS v FROM schema_version"))
    return row["v"] or 0


def init_db(db_path=None):
    """Create/upgrade the schema. Idempotent — safe to call on every startup.
    With TURSO_DATABASE_URL set, db_path is ignored and the cloud DB is
    migrated instead."""
    if is_turso():
        conn = get_connection()
    else:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = get_connection(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        version = current_version(conn)
        for target in sorted(MIGRATIONS):
            if target > version:
                conn.executescript(MIGRATIONS[target])
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (target,)
                )
                conn.commit()
        return current_version(conn)
    finally:
        conn.close()


def insert_event(conn, event_type, source=None, external_id=None, agent_name=None,
                 description=None, data=None):
    """Insert an event. When source + external_id are given, the insert is
    idempotent: a duplicate returns the existing row id instead of inserting.

    Note: the UNIQUE(source, external_id) constraint treats NULLs as distinct,
    so events without a source never collide with each other.
    """
    if source and external_id:
        row = _fetchone_dict(
            conn.execute(
                "SELECT id FROM events WHERE source = ? AND external_id = ?",
                (source, external_id),
            )
        )
        if row:
            return {"inserted": False, "id": row["id"]}
    cur = conn.execute(
        "INSERT INTO events (event_type, source, external_id, agent_name,"
        " description, data) VALUES (?, ?, ?, ?, ?, ?)",
        (event_type, source, external_id, agent_name, description, data),
    )
    conn.commit()
    return {"inserted": True, "id": cur.lastrowid}


def get_agent_runs(conn, agent_name=None, limit=100):
    """Fixed version of the old broken query (it appended AND with no WHERE,
    misordered its params, and targeted a table that didn't exist)."""
    query = "SELECT * FROM agent_runs"
    params = []
    if agent_name:
        query += " WHERE agent_name = ?"
        params.append(agent_name)
    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    return _fetchdicts(conn.execute(query, tuple(params)))


def recent_events(conn, limit=50):
    return _fetchdicts(
        conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
    )


# -- tasks -----------------------------------------------------------------

TASK_STATUSES = ("pending", "in_progress", "completed", "failed")


def create_task(conn, module, payload=None, status="pending"):
    """Queue one unit of work. Returns the new task row as a dict."""
    if status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {TASK_STATUSES}")
    cur = conn.execute(
        "INSERT INTO tasks (module, status, payload) VALUES (?, ?, ?)",
        (module, status, json.dumps(payload or {})),
    )
    conn.commit()
    return get_task(conn, cur.lastrowid)


def get_task(conn, task_id):
    return _fetchone_dict(
        conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    )


def update_task_status(conn, task_id, status):
    """Advance a task's status. Returns the updated row, or None if missing."""
    if status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {TASK_STATUSES}")
    conn.execute(
        "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, task_id),
    )
    conn.commit()
    return get_task(conn, task_id)


def list_tasks(conn, status=None, limit=100):
    query = "SELECT * FROM tasks"
    params = []
    if status:
        if status not in TASK_STATUSES:
            raise ValueError(f"status must be one of {TASK_STATUSES}")
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return _fetchdicts(conn.execute(query, tuple(params)))


# -- sops -------------------------------------------------------------------

def create_sop(conn, title, trigger_event, steps):
    """Store a standard operating procedure. steps is a list of strings."""
    if not isinstance(steps, list):
        raise ValueError("steps must be a list of strings")
    cur = conn.execute(
        "INSERT INTO sops (title, trigger_event, steps_json) VALUES (?, ?, ?)",
        (title, trigger_event, json.dumps(steps)),
    )
    conn.commit()
    return get_sop(conn, cur.lastrowid)


def get_sop(conn, sop_id):
    return _fetchone_dict(
        conn.execute("SELECT * FROM sops WHERE id = ?", (sop_id,))
    )


def list_sops(conn, trigger_event=None, limit=100):
    query = "SELECT * FROM sops"
    params = []
    if trigger_event:
        query += " WHERE trigger_event = ?"
        params.append(trigger_event)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return _fetchdicts(conn.execute(query, tuple(params)))


# -- prompt runs --------------------------------------------------------------

def save_prompt_run(conn, pipeline_type, input_raw, outputs):
    """Record a real pipeline run: what went in and what actually came out.
    This function generates nothing — the caller supplies both sides."""
    if not isinstance(outputs, dict):
        raise ValueError("outputs must be a dict")
    cur = conn.execute(
        "INSERT INTO prompt_runs (pipeline_type, input_raw, outputs_json)"
        " VALUES (?, ?, ?)",
        (pipeline_type, input_raw, json.dumps(outputs)),
    )
    conn.commit()
    return _fetchone_dict(
        conn.execute("SELECT * FROM prompt_runs WHERE id = ?", (cur.lastrowid,))
    )


def list_prompt_runs(conn, pipeline_type=None, limit=100):
    query = "SELECT * FROM prompt_runs"
    params = []
    if pipeline_type:
        query += " WHERE pipeline_type = ?"
        params.append(pipeline_type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return _fetchdicts(conn.execute(query, tuple(params)))
