import sqlite3
from contextlib import contextmanager

from .settings import DB_PATH


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                created_at TEXT,
                status TEXT,
                stage TEXT,
                input_path TEXT,
                config_json TEXT,
                shortlist_k INTEGER,
                total_candidates INTEGER,
                sliced_candidates INTEGER,
                best_candidate_id TEXT NULL,
                error TEXT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                idx INTEGER,
                rot_w REAL,
                rot_x REAL,
                rot_y REAL,
                rot_z REAL,
                stage1_json TEXT,
                stage2_json TEXT,
                score REAL NULL,
                rank INTEGER NULL,
                status TEXT,
                rotated_stl_path TEXT,
                gcode_path TEXT,
                preview_json_path TEXT,
                error TEXT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                ts TEXT,
                level TEXT,
                message TEXT
            )
            """
        )
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
