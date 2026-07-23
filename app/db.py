"""Persistence for feature-interest counts (specs/08-architecture.md §5.1).

This increment implements exactly one of the six tables the architecture describes:

    feature_interest(workspace_id, feature_key, count, last_clicked_at)
      PRIMARY KEY (workspace_id, feature_key)

using the standard-library `sqlite3` (no SQLAlchemy yet — that arrives with the full schema).
The file lives in the resolved data directory (app/config.py).

Invariants from §5.1, asserted by this module in place of a fixture:
  * The write is an **upsert, not an append**: a repeat click for the same (workspace, key)
    updates `last_clicked_at` and leaves `count` alone. Interest is a boolean fact about a
    household; the count is only meaningful summed across installations, so a single install
    never exceeds 1. This is also what makes a second thumbs-up not count twice (§2.1).
  * Every row carries `workspace_id` (§5.5 invariant 1: no table is implicitly global). Until
    multi-workspace lands there is a single constant workspace, WORKSPACE_ID.

Main items:
    WORKSPACE_ID          the single local workspace id used for now.
    record_interest(...)  upsert a click; returns True if this was the first click for the key.
    interest_count(...)   read a key's count (used by tests; never shown to the user, §2.1).
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import config

WORKSPACE_ID = "local"

_DB_FILENAME = "feature_interest.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feature_interest (
    workspace_id     TEXT    NOT NULL,
    feature_key      TEXT    NOT NULL,
    count            INTEGER NOT NULL DEFAULT 0,
    last_clicked_at  TEXT    NOT NULL,
    PRIMARY KEY (workspace_id, feature_key)
);
"""


def _db_path() -> Path:
    return config.data_dir() / _DB_FILENAME


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.execute(_SCHEMA)
    return conn


def record_interest(feature_key: str, workspace_id: str = WORKSPACE_ID) -> bool:
    """Upsert a thumbs-up for `feature_key`. Returns True iff it was the first click.

    First click inserts count 1. A repeat click refreshes `last_clicked_at` only — count is
    not bumped (interest is boolean per household, §5.1 invariant 2). The (workspace_id,
    feature_key) primary key makes this a single atomic upsert.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        # Check existence first (same transaction) so we can report first-vs-repeat; the
        # upsert itself cannot tell them apart via rowcount.
        existed = conn.execute(
            "SELECT 1 FROM feature_interest WHERE workspace_id = ? AND feature_key = ?",
            (workspace_id, feature_key),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO feature_interest (workspace_id, feature_key, count, last_clicked_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT (workspace_id, feature_key)
            DO UPDATE SET last_clicked_at = excluded.last_clicked_at
            """,
            (workspace_id, feature_key, now),
        )
    return existed is None


def interest_count(feature_key: str, workspace_id: str = WORKSPACE_ID) -> int:
    """The recorded count for a key (0 if none). For tests only — never shown to users (§2.1)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT count FROM feature_interest WHERE workspace_id = ? AND feature_key = ?",
            (workspace_id, feature_key),
        ).fetchone()
    return row[0] if row else 0
