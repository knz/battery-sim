"""Dataset persistence — SeriesFrames to disk, metadata to SQLite (specs/08-architecture.md §5.1).

The browser-side fetch increment: the browser fetches from Home Assistant and streams raw rows
to the backend, which normalises them into SeriesFrames (app/domain) and persists them here so
they survive a restart (specs §3.5 LOAD_SUCCEEDED, §5.1 persistence layer). No HA token or
credential is stored — it never leaves the browser (specs §7.5, browser-fetch increment).

Two homes, mirroring §5.1:
  * **Filesystem** — one `.npz` per series under `<data_dir>/<workspace>/series/<name>.npz`,
    holding the frame's index/values/quality (and price min/max). Chosen over Parquet to avoid
    a pandas dependency for this increment; the on-disk shape is an implementation detail behind
    load_frames(). Path derives from workspace_id with traversal rejected (§5.5 invariant 4).
  * **SQLite** — a `datasets` row (window, source, fetched_at) and one `series_meta` row per
    series (name, kind, resolution_s, path). Reuses app/db.py's connection/data-dir plumbing.

Multi-user readiness (§5.5): every row carries workspace_id; there is one workspace for now
(db.WORKSPACE_ID). No module-level mutable state.

Main items:
    save_dataset(frames, window, source, warnings, workspace_id) -> int   persist; returns id.
    load_latest(workspace_id) -> LoadedDataset | None                     restore on startup.
    LoadedDataset                                                         frames + window + meta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app import config, db
from app.domain.frames import QUALITY_DTYPE, SeriesFrame

_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  TEXT    NOT NULL,
    source_type   TEXT    NOT NULL,
    window_start  TEXT    NOT NULL,
    window_end    TEXT    NOT NULL,
    fetched_at    TEXT    NOT NULL,
    warnings_json TEXT    NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS series_meta (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id        INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    workspace_id      TEXT    NOT NULL,
    name              TEXT    NOT NULL,
    kind              TEXT    NOT NULL,
    resolution_s      INTEGER,
    path              TEXT    NOT NULL,
    fine_resolution_s INTEGER,
    fine_start        TEXT,
    fine_end          TEXT
);
"""


@dataclass
class LoadedDataset:
    """A restored dataset: the normalised frames plus its window and provenance."""

    id: int
    source_type: str
    window: tuple[datetime, datetime]
    fetched_at: datetime
    frames: list[SeriesFrame]
    warnings: list[dict]


# Columns added to series_meta after its first release. `CREATE TABLE IF NOT EXISTS` never
# alters an existing table, so a DB created before these columns existed needs them added. This
# is a minimal forward migration for a pre-release app (no data to preserve across shapes, but a
# stale local DB should not crash). Each entry is (column, type); adding an existing column is a
# no-op we swallow.
_SERIES_META_ADDED_COLUMNS = (
    ("fine_resolution_s", "INTEGER"),
    ("fine_start", "TEXT"),
    ("fine_end", "TEXT"),
)


def _connect():
    conn = db._connect()  # reuse the feature_interest DB file and its data-dir resolution
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn) -> None:
    """Add any series_meta columns missing from an older local DB (idempotent)."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(series_meta)").fetchall()}
    for column, coltype in _SERIES_META_ADDED_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE series_meta ADD COLUMN {column} {coltype}")


def _series_dir(workspace_id: str) -> Path:
    """`<data_dir>/<workspace>/series/`, created if missing. Rejects path traversal (§5.5)."""
    if "/" in workspace_id or "\\" in workspace_id or workspace_id in ("", ".", ".."):
        raise ValueError(f"unsafe workspace_id: {workspace_id!r}")
    d = config.data_dir() / workspace_id / "series"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _frame_path(workspace_id: str, name: str) -> Path:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"unsafe series name: {name!r}")
    return _series_dir(workspace_id) / f"{name}.npz"


def _save_frame(path: Path, frame: SeriesFrame) -> None:
    arrays = {
        # datetime64[s] is not directly npz-savable as-is across versions; store epoch seconds.
        "index_s": frame.index.astype("datetime64[s]").astype(np.int64),
        "values": frame.values,
        "quality": frame.quality,
    }
    if frame.value_min is not None:
        arrays["value_min"] = frame.value_min
    if frame.value_max is not None:
        arrays["value_max"] = frame.value_max
    np.savez(path, **arrays)


def _load_frame(path: Path, name: str, kind: str, resolution_s: int | None) -> SeriesFrame:
    data = np.load(path)
    index = data["index_s"].astype("datetime64[s]")
    return SeriesFrame(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        resolution_s=resolution_s,
        index=index,
        values=data["values"],
        quality=data["quality"].astype(QUALITY_DTYPE),
        value_min=data["value_min"] if "value_min" in data else None,
        value_max=data["value_max"] if "value_max" in data else None,
    )


def save_dataset(
    frames: list[SeriesFrame],
    window: tuple[datetime, datetime],
    source_type: str,
    warnings: list[dict],
    workspace_id: str = db.WORKSPACE_ID,
) -> int:
    """Persist frames + metadata; return the new dataset id (specs §3.5 LOAD_SUCCEEDED).

    Frames are written to `.npz` first, then a single SQLite transaction records the dataset and
    its series_meta rows. `warnings` (e.g. ambiguous register decreases from ingest) are stored
    as JSON on the dataset row so panel ① can show them after a restart.
    """
    import json

    now = datetime.now(timezone.utc).isoformat()
    for f in frames:
        _save_frame(_frame_path(workspace_id, f.name), f)

    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO datasets
               (workspace_id, source_type, window_start, window_end, fetched_at, warnings_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                workspace_id,
                source_type,
                window[0].isoformat(),
                window[1].isoformat(),
                now,
                json.dumps(warnings),
            ),
        )
        dataset_id = cur.lastrowid
        for f in frames:
            fine_start = f.fine_coverage[0].isoformat() if f.fine_coverage else None
            fine_end = f.fine_coverage[1].isoformat() if f.fine_coverage else None
            conn.execute(
                """INSERT INTO series_meta
                   (dataset_id, workspace_id, name, kind, resolution_s, path,
                    fine_resolution_s, fine_start, fine_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    dataset_id,
                    workspace_id,
                    f.name,
                    f.kind,
                    f.resolution_s,
                    str(_frame_path(workspace_id, f.name)),
                    f.fine_resolution_s,
                    fine_start,
                    fine_end,
                ),
            )
    return int(dataset_id)


def load_latest(workspace_id: str = db.WORKSPACE_ID) -> LoadedDataset | None:
    """Restore the most recent dataset for a workspace, or None if there is none (specs §3.5)."""
    import json

    with _connect() as conn:
        row = conn.execute(
            """SELECT id, source_type, window_start, window_end, fetched_at, warnings_json
               FROM datasets WHERE workspace_id = ? ORDER BY id DESC LIMIT 1""",
            (workspace_id,),
        ).fetchone()
        if row is None:
            return None
        dataset_id, source_type, w_start, w_end, fetched_at, warnings_json = row
        metas = conn.execute(
            """SELECT name, kind, resolution_s, path, fine_resolution_s, fine_start, fine_end
               FROM series_meta WHERE dataset_id = ?""",
            (dataset_id,),
        ).fetchall()

    frames = []
    for name, kind, resolution_s, path, fine_res, fine_start, fine_end in metas:
        p = Path(path)
        if p.exists():
            frame = _load_frame(p, name, kind, resolution_s)
            frame.fine_resolution_s = fine_res
            if fine_start and fine_end:
                frame.fine_coverage = (
                    datetime.fromisoformat(fine_start),
                    datetime.fromisoformat(fine_end),
                )
            frames.append(frame)
    return LoadedDataset(
        id=int(dataset_id),
        source_type=source_type,
        window=(datetime.fromisoformat(w_start), datetime.fromisoformat(w_end)),
        fetched_at=datetime.fromisoformat(fetched_at),
        frames=frames,
        warnings=json.loads(warnings_json),
    )
