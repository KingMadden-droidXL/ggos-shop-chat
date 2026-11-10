-- gangster_god.db schema — GENERATED from ggos/database.py MIGRATIONS
-- (schema v3). Load into Turso with:
--   turso db shell gangster-god < data/schema.sql
-- Regenerate: python -m scripts.dump_schema

CREATE INDEX idx_agent_runs_name ON agent_runs (agent_name, started_at);
CREATE INDEX idx_events_source ON events (source, external_id);
CREATE INDEX idx_events_type_time ON events (event_type, timestamp);
CREATE INDEX idx_money_source ON money (source, external_id);
CREATE INDEX idx_paper_pending
    ON paper_predictions (evaluated_at, scanned_at);
CREATE INDEX idx_prompt_runs_type ON prompt_runs (pipeline_type, created_at);
CREATE INDEX idx_sops_trigger ON sops (trigger_event);
CREATE INDEX idx_tasks_status ON tasks (status, created_at);
CREATE INDEX idx_telemetry_metric_time ON telemetry (metric, timestamp);
CREATE TABLE agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    summary TEXT
);
CREATE TABLE agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'idle',
    config TEXT
);
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    agent_name TEXT NOT NULL,
    action TEXT NOT NULL,
    rationale TEXT,
    approved INTEGER NOT NULL DEFAULT 0,
    executed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE events (
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
CREATE TABLE knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT
);
CREATE TABLE memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    agent_name TEXT,
    key TEXT NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE money (
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
CREATE TABLE paper_predictions (
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
CREATE TABLE prompt_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_type TEXT NOT NULL,
    input_raw TEXT NOT NULL,
    outputs_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE schema_version ( version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE sops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    trigger_event TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    labels TEXT
);
