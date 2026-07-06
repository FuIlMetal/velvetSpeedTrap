"""
SQLite storage for runs and settings.

A single connection is shared across the sensor / web / OLED threads, guarded
by a lock. SQLite serialises writes anyway; the lock just keeps our own
multi-statement operations tidy.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, List, Optional

from . import config
from .models import RunRecord

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   REAL    NOT NULL,
    ended_at     REAL    NOT NULL,
    peak_mph     REAL    NOT NULL,
    avg_mph      REAL    NOT NULL,
    duration_s   REAL    NOT NULL,
    revolutions  INTEGER NOT NULL,
    treat_given  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_peak ON runs(peak_mph DESC);
CREATE INDEX IF NOT EXISTS idx_started ON runs(started_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_db(path: str = None) -> None:
    """Create the database file + schema if needed. Call once at startup."""
    global _conn
    path = path or config.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(_SCHEMA)
        _conn.commit()


def _require_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db.init_db() must be called before using the database")
    return _conn


# --- Runs -----------------------------------------------------------------

def save_run(record: RunRecord) -> int:
    conn = _require_conn()
    with _lock:
        cur = conn.execute(
            """
            INSERT INTO runs (started_at, ended_at, peak_mph, avg_mph,
                              duration_s, revolutions, treat_given)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            record.as_row(),
        )
        conn.commit()
        return cur.lastrowid


def top_n(n: int = 10) -> List[sqlite3.Row]:
    conn = _require_conn()
    with _lock:
        return conn.execute(
            """
            SELECT id, peak_mph, avg_mph, started_at, duration_s,
                   revolutions, treat_given
            FROM runs
            ORDER BY peak_mph DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()


def recent_runs(n: int = 20) -> List[sqlite3.Row]:
    conn = _require_conn()
    with _lock:
        return conn.execute(
            """
            SELECT id, peak_mph, avg_mph, started_at, duration_s,
                   revolutions, treat_given
            FROM runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()


def all_time_peak() -> float:
    conn = _require_conn()
    with _lock:
        row = conn.execute("SELECT MAX(peak_mph) AS p FROM runs").fetchone()
    return (row["p"] if row else None) or 0.0


def peak_today() -> float:
    """Highest peak since local midnight."""
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_epoch = midnight.timestamp()
    conn = _require_conn()
    with _lock:
        row = conn.execute(
            "SELECT MAX(peak_mph) AS p FROM runs WHERE started_at >= ?",
            (start_epoch,),
        ).fetchone()
    return (row["p"] if row else None) or 0.0


def last_run_time() -> float:
    """Wall-clock end time of the most recent run (0.0 if none)."""
    conn = _require_conn()
    with _lock:
        row = conn.execute("SELECT MAX(ended_at) AS t FROM runs").fetchone()
    return (row["t"] if row else None) or 0.0


def run_count() -> int:
    conn = _require_conn()
    with _lock:
        row = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()
    return row["c"] if row else 0


def treats_today() -> int:
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    conn = _require_conn()
    with _lock:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE treat_given = 1 AND started_at >= ?",
            (midnight.timestamp(),),
        ).fetchone()
    return row["c"] if row else 0


# --- Settings (string key/value, typed accessors) -------------------------

def get_setting(key: str, default: Any = None) -> Optional[str]:
    conn = _require_conn()
    with _lock:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def get_setting_float(key: str, default: float) -> float:
    val = get_setting(key, None)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def set_setting(key: str, value: Any) -> None:
    conn = _require_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )
        conn.commit()


def delete_setting(key: str) -> None:
    conn = _require_conn()
    with _lock:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        conn.commit()
