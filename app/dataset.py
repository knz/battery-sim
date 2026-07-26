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

Atomicity: `save_dataset` and `upsert_series` are both multi-statement writes, and their `with
_connect()` blocks are transactions — they commit as a unit or roll back entirely, which is
`db._Connection`'s doing rather than sqlite3's (the connection is in autocommit mode for the
migration's sake; see app/db.py). This matters most for `upsert_series`, which replaces a series
by DELETE-then-INSERT: without the rollback an exception between the two removes a series the user
already had and puts nothing back. The `.npz` writes stay OUTSIDE the transaction and are not
undone by it — the limit is spelled out in `upsert_series`' docstring.

Per-series provenance (slot-first sources): a dataset's series may come from different sources
now — the energy meters from Home Assistant, the spot price from the preset Energy-Charts source
(specs §2.2 slot-first source picker). So provenance is recorded PER SERIES in series_meta
(`source_type` column), not only per dataset. `upsert_series` merges one freshly-loaded frame
into the latest dataset, replacing any series of the same name and leaving the others intact —
this is what lets a backend-loaded price attach to an existing HA-fetched energy dataset (§4.3).

Main items:
    connect()                                                    a connection with both schemas.
    save_dataset(frames, window, source, warnings, sources, workspace_id) -> int  persist; id.
    upsert_series(frame, source_key, window, workspace_id) -> int          merge one series in.
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
    fine_end          TEXT,
    source_type       TEXT,
    stat_id           TEXT
);
"""


@dataclass
class LoadedDataset:
    """A restored dataset: the normalised frames plus its window and provenance.

    `source_type` is the dataset-level provenance (the source that created the dataset, kept for
    backward compatibility). `series_sources` is the per-series provenance (specs §2.2): series
    name → the descriptor key of the source that produced it, populated from series_meta. A series
    with no recorded per-series source falls back to `source_type` when written, so the mapping
    always has an entry per persisted series.
    """

    id: int
    source_type: str
    window: tuple[datetime, datetime]
    fetched_at: datetime
    frames: list[SeriesFrame]
    warnings: list[dict]
    series_sources: dict[str, str]


# Columns added to series_meta after its first release. `CREATE TABLE IF NOT EXISTS` never
# alters an existing table, so a DB created before these columns existed needs them added. This
# is a minimal forward migration for a pre-release app (no data to preserve across shapes, but a
# stale local DB should not crash). Each entry is (column, type); adding an existing column is a
# no-op we swallow.
_SERIES_META_ADDED_COLUMNS = (
    ("fine_resolution_s", "INTEGER"),
    ("fine_start", "TEXT"),
    ("fine_end", "TEXT"),
    # Per-series provenance (slot-first sources, specs §2.2): the descriptor key of the source
    # that produced this series (e.g. "home_assistant", "energy_charts"). Added after series_meta
    # first shipped, so a stale local DB gets it here rather than crashing. NULL on rows written
    # before per-series provenance existed; readers fall back to the dataset-level source_type.
    ("source_type", "TEXT"),
    # The HA statistic id a series was fetched from (specs §2.2), so a fetched HA slot can render
    # its entity after a reload. NULL for non-HA sources and for pre-stat_id rows.
    ("stat_id", "TEXT"),
)


def _as_utc(dt: datetime) -> datetime:
    """Normalise a datetime to tz-aware UTC (naive is read as UTC, per the §4.4 UTC pipeline).

    Used before comparing a window read back from storage — which may be naive if an older build
    wrote it — with an aware one, since min()/max() across the two raises TypeError.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _connect():
    conn = db.connect()  # reuse the shared DB file, its data-dir resolution and its own schema
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def connect():
    """A connection with BOTH this module's tables and app/db.py's created and migrated.

    The public spelling of `_connect`, for the modules that need to query `datasets` /
    `series_meta` alongside the workspace index (app/workspaces.py). It exists because
    `db.connect()` alone does not create these two tables, so a query against them on a fresh
    installation — where no dataset has ever been saved — would fail with "no such table" rather
    than returning nothing.
    """
    return _connect()


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


def _insert_series_meta(
    conn, dataset_id: int, workspace_id: str, frame: SeriesFrame, source_type: str | None
) -> None:
    """Write one series_meta row for `frame` (its .npz is written separately by _save_frame).

    `source_type` is the per-series provenance (the source's descriptor key), or None when a
    caller did not record one — readers then fall back to the dataset-level source_type.
    """
    fine_start = frame.fine_coverage[0].isoformat() if frame.fine_coverage else None
    fine_end = frame.fine_coverage[1].isoformat() if frame.fine_coverage else None
    conn.execute(
        """INSERT INTO series_meta
           (dataset_id, workspace_id, name, kind, resolution_s, path,
            fine_resolution_s, fine_start, fine_end, source_type, stat_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dataset_id,
            workspace_id,
            frame.name,
            frame.kind,
            frame.resolution_s,
            str(_frame_path(workspace_id, frame.name)),
            frame.fine_resolution_s,
            fine_start,
            fine_end,
            source_type,
            frame.stat_id,
        ),
    )


def save_dataset(
    frames: list[SeriesFrame],
    window: tuple[datetime, datetime],
    source_type: str,
    warnings: list[dict],
    sources: dict[str, str] | None = None,
    workspace_id: str = db.WORKSPACE_ID,
) -> int:
    """Persist frames + metadata; return the new dataset id (specs §3.5 LOAD_SUCCEEDED).

    Frames are written to `.npz` first, then a single SQLite transaction records the dataset and
    its series_meta rows. `warnings` (e.g. ambiguous register decreases from ingest) are stored
    as JSON on the dataset row so panel ① can show them after a restart.

    `sources` maps a series name to the descriptor key of the source that produced it (specs §2.2
    per-series provenance). A series absent from the mapping (or the whole mapping being None,
    which the existing WS ingest path passes) falls back to the dataset-level `source_type` — so
    the single-source ingest path keeps working unchanged while a mixed-source dataset records
    where each series came from.
    """
    import json

    sources = sources or {}
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
            _insert_series_meta(
                conn, dataset_id, workspace_id, f, sources.get(f.name, source_type)
            )
    return int(dataset_id)


def upsert_series(
    frame: SeriesFrame,
    source_key: str,
    window: tuple[datetime, datetime] | None = None,
    workspace_id: str = db.WORKSPACE_ID,
) -> int:
    """Merge one freshly-loaded `frame` into the latest dataset, or create one for it alone.

    This is the slot-first merge (specs §2.2): a backend_load source (e.g. the Energy-Charts spot
    price) is loaded for a single slot and attached to whatever dataset already exists — without
    discarding the other series. Returns the id of the dataset the series now lives in.

    Behaviour:

      * If a latest dataset exists for `workspace_id`, this series is added to it, REPLACING any
        existing series_meta row of the same name (and overwriting its `.npz`). The other series
        are untouched. Because `_frame_path` is deterministic by name, overwriting the same file
        is the natural replace — no orphaned .npz is left behind.
      * If no dataset exists yet, a new dataset is created containing just this series. Its window
        is `window` when supplied, else the frame's own coverage (falling back to a zero-length
        window at epoch only for an empty frame — an edge case a real load does not hit).

    Window/coverage policy (documented so it is not surprising): when merging into an existing
    dataset and `window` is supplied, the dataset's stored window is widened to the UNION of the
    existing window and `window` (a spot price loaded past the existing energy coverage extends
    the dataset's advertised span; loading a subset never shrinks it). When `window` is None the
    dataset window is left as-is. The stored window is the advertised fetch span only; the actual
    per-series coverage that the simulation grid uses is recomputed from the frames' own indices
    at read time (normalize.grid_report, specs §6.2), so a slightly wide window here is harmless.

    **Atomicity, and its limit.** The SQL below runs in one transaction (`db.connect`'s `with`
    block): the DELETE of the existing series_meta row and the INSERT of its replacement either
    both land or neither does. That matters because they are a replace — without the rollback, an
    exception between them removes a series the user already had and puts nothing back.

    The `.npz` write is NOT part of that transaction and is not undone by it. It happens first, and
    `_frame_path` is deterministic by name, so a failure after this line leaves the file holding
    the NEW array while `series_meta` still points at it describing the OLD series. The row-level
    guarantee is therefore "the series is still there and still readable", not "its values are
    unchanged". Accepted for the same reason `workspaces.delete` accepts its rows/files split: the
    fix is a write-to-temp-and-rename plus a reclaim pass, which is more machinery than a local
    single-user app warrants, and the failed path re-runs on the next load.
    """
    _save_frame(_frame_path(workspace_id, frame.name), frame)

    with _connect() as conn:
        row = conn.execute(
            """SELECT id, window_start, window_end FROM datasets
               WHERE workspace_id = ? ORDER BY id DESC LIMIT 1""",
            (workspace_id,),
        ).fetchone()

        if row is None:
            # No dataset yet: create one holding just this series. Its window is the supplied one,
            # else the frame's own coverage, else a degenerate window (empty frame only).
            win = window or frame.coverage()
            if win is None:
                win = (datetime.fromtimestamp(0, timezone.utc),) * 2
            now = datetime.now(timezone.utc).isoformat()
            cur = conn.execute(
                """INSERT INTO datasets
                   (workspace_id, source_type, window_start, window_end, fetched_at, warnings_json)
                   VALUES (?, ?, ?, ?, ?, '[]')""",
                (workspace_id, source_key, win[0].isoformat(), win[1].isoformat(), now),
            )
            dataset_id = int(cur.lastrowid)
            _insert_series_meta(conn, dataset_id, workspace_id, frame, source_key)
            return dataset_id

        dataset_id, w_start, w_end = int(row[0]), row[1], row[2]
        # Replace any existing series of this name, then insert the fresh one.
        conn.execute(
            "DELETE FROM series_meta WHERE dataset_id = ? AND name = ?",
            (dataset_id, frame.name),
        )
        _insert_series_meta(conn, dataset_id, workspace_id, frame, source_key)

        if window is not None:
            # Widen the dataset window to the union of the stored window and the loaded window.
            # Both sides are normalised to tz-aware UTC before comparison: a window stored by an
            # older build (or a naive caller) could be naive, and min()/max() across a naive and
            # an aware datetime raises TypeError. The pipeline holds UTC (specs §4.4), so a naive
            # stored instant is read as UTC.
            cur_start = _as_utc(datetime.fromisoformat(w_start))
            cur_end = _as_utc(datetime.fromisoformat(w_end))
            new_start = min(cur_start, _as_utc(window[0]))
            new_end = max(cur_end, _as_utc(window[1]))
            if (new_start, new_end) != (cur_start, cur_end):
                conn.execute(
                    "UPDATE datasets SET window_start = ?, window_end = ? WHERE id = ?",
                    (new_start.isoformat(), new_end.isoformat(), dataset_id),
                )
        return dataset_id


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
            """SELECT name, kind, resolution_s, path, fine_resolution_s, fine_start, fine_end,
                      source_type, stat_id
               FROM series_meta WHERE dataset_id = ?""",
            (dataset_id,),
        ).fetchall()

    frames = []
    series_sources: dict[str, str] = {}
    for name, kind, resolution_s, path, fine_res, fine_start, fine_end, s_source, stat_id in metas:
        p = Path(path)
        if p.exists():
            frame = _load_frame(p, name, kind, resolution_s)
            frame.fine_resolution_s = fine_res
            if fine_start and fine_end:
                frame.fine_coverage = (
                    datetime.fromisoformat(fine_start),
                    datetime.fromisoformat(fine_end),
                )
            # The HA statistic id this series was fetched from (specs §2.2), so the source picker
            # can render a fetched HA slot's entity. None for non-HA sources / pre-stat_id rows.
            frame.stat_id = stat_id
            frames.append(frame)
            # Per-series provenance, falling back to the dataset-level source for rows written
            # before per-series source_type existed (specs §2.2).
            series_sources[name] = s_source if s_source is not None else source_type
    return LoadedDataset(
        id=int(dataset_id),
        source_type=source_type,
        window=(datetime.fromisoformat(w_start), datetime.fromisoformat(w_end)),
        fetched_at=datetime.fromisoformat(fetched_at),
        frames=frames,
        warnings=json.loads(warnings_json),
        series_sources=series_sources,
    )
