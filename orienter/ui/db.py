from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
    id TEXT PRIMARY KEY,
    created_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    status TEXT,
    input_path TEXT,
    output_path TEXT,
    profile TEXT,
    params_json TEXT,
    last_heartbeat TEXT,
    engine_mode TEXT
);
CREATE TABLE IF NOT EXISTS models(
    id TEXT PRIMARY KEY,
    run_id TEXT,
    model_path TEXT,
    status TEXT,
    best_score REAL,
    metrics_json TEXT,
    artifacts_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);
CREATE TABLE IF NOT EXISTS run_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    ts TEXT,
    level TEXT,
    message TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);
CREATE TABLE IF NOT EXISTS cache(
    key TEXT PRIMARY KEY,
    value_json TEXT,
    created_at TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
