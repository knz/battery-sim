"""Tests for slot-first backend persistence + the load endpoint (Phase B; specs §2.2, §4.3, §5.1).

Three layers:

  * Persistence unit tests (dataset.py): the series_meta forward-migration adds `source_type` to
    an old DB; `save_dataset` records a per-series `sources` mapping that `load_latest` reads back;
    `upsert_series` merges one series into an existing dataset (replacing that series, keeping the
    others) and stands alone when no dataset exists.
  * The POST /data/slot/{slot}/load endpoint against the committed Energy-Charts data — a
    historical in-range window so no bridge fires and no network is hit.
  * Endpoint error paths: unknown slot (404), unknown source (404), requesting a browser_fetch
    source ("home_assistant") here (400 with a clear message), and a window whose `end` precedes
    its `start` (400). That last rule is enforced at both of the app's entry points — its socket
    counterpart is `tests/test_ingest_ws.py::test_an_inverted_window_is_rejected_over_the_socket`,
    with a different failure shape — and until it was added the rule was asserted only by the
    packaged suite, which runs in the dispatch-only Release workflow.
  * The endpoint's CSV path (step 5 of the CSV-import brief): a `binding` in the body is threaded to
    `CsvSource.load_with_warnings`, an `upload_id` this workspace does not have is a 400 that
    persists nothing, and `CsvBindingError` is a 400 rather than the 502 the bare `except Exception`
    used to give it. The WS reify path's own coverage is `tests/test_csv_binding_reify.py`.

Every test runs against an isolated data dir (BATTERY_SIM_DATA_DIR) so the SQLite DB and the .npz
series files never touch the working tree. No test hits the network.

    uv run pytest tests/test_slot_load.py
"""

import importlib
from datetime import datetime, timezone

import numpy as np
import pytest

from tests.conftest import seed_workspace, w

UTC = timezone.utc


@pytest.fixture()
def dataset(tmp_path, monkeypatch):
    """A freshly-reloaded app.dataset bound to an isolated data dir (mirrors test_ingest_ws)."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.dataset as dataset
    importlib.reload(dataset)
    return dataset


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient whose app writes to an isolated data dir, plus the reloaded modules."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.dataset as dataset
    importlib.reload(dataset)
    # Reloaded because it captured the PRE-reload `db` module object at import; without this the
    # workspace row would be written to whichever database that older module still points at.
    import app.workspaces as workspaces
    importlib.reload(workspaces)
    import app.deps as deps
    importlib.reload(deps)
    import app.main as main
    importlib.reload(main)
    # The routes are workspace-scoped now (`/w/{id}/…`) and the fixture's TestClient is used
    # outside a `with` block, so the lifespan that would adopt this data dir never runs.
    seed_workspace()
    from fastapi.testclient import TestClient
    return TestClient(main.app), main, dataset


def _energy_frame(name: str, base: float, n: int = 3):
    """A tiny hourly energy SeriesFrame (n interval deltas) for persistence tests."""
    from app.domain.frames import QUALITY_DTYPE, SeriesFrame

    start = np.datetime64("2024-03-01T00:00:00", "s")
    index = np.array([start + np.timedelta64(i, "h") for i in range(n)])
    return SeriesFrame(
        name=name,
        kind="energy",
        resolution_s=3600,
        index=index,
        values=np.array([base + i for i in range(n)], dtype=np.float64),
        quality=np.zeros(n, dtype=QUALITY_DTYPE),
    )


# --- 1. migration: an old series_meta gets source_type added ----------------------------------

def test_migrate_adds_source_type_to_old_db(dataset):
    """A series_meta table created without source_type gains it via _migrate (idempotent)."""
    import sqlite3

    from app import config

    # Build a stale DB: series_meta WITHOUT the source_type column (nor the fine_* columns).
    path = config.data_dir() / "feature_interest.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
            source_type TEXT NOT NULL, window_start TEXT NOT NULL, window_end TEXT NOT NULL,
            fetched_at TEXT NOT NULL, warnings_json TEXT NOT NULL DEFAULT '[]');
        CREATE TABLE series_meta (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id INTEGER NOT NULL,
            workspace_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
            resolution_s INTEGER, path TEXT NOT NULL);
        """
    )
    conn.commit()
    conn.close()

    # dataset._connect() runs the schema + _migrate; the column must now be present.
    with dataset._connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(series_meta)").fetchall()}
    assert "source_type" in cols
    for c in ("fine_resolution_s", "fine_start", "fine_end"):
        assert c in cols  # the pre-existing forward migration still runs too


# --- 2. save_dataset persists a per-series sources mapping; load_latest reads it back ----------

def test_save_dataset_records_per_series_sources(dataset):
    frames = [_energy_frame("grid_import_t1", 1.0), _energy_frame("price_spot", 0.2)]
    win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 2, tzinfo=UTC))
    dataset.save_dataset(
        frames, win, "home_assistant", [],
        sources={"price_spot": "energy_charts"},  # grid_import_t1 falls back to dataset source
        workspace_id=dataset.db.WORKSPACE_ID,
    )

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded is not None
    assert loaded.series_sources == {
        "grid_import_t1": "home_assistant",  # fallback to the dataset-level source
        "price_spot": "energy_charts",       # explicit per-series source
    }
    assert loaded.source_type == "home_assistant"


def test_save_dataset_without_sources_falls_back_everywhere(dataset):
    """The existing WS ingest path passes no `sources`; every series gets the dataset source."""
    frames = [_energy_frame("grid_import_t1", 1.0)]
    win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 2, tzinfo=UTC))
    dataset.save_dataset(frames, win, "home_assistant", [], workspace_id=dataset.db.WORKSPACE_ID)
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded.series_sources == {"grid_import_t1": "home_assistant"}


# --- 3. upsert_series: merge into existing / stand alone --------------------------------------

def test_upsert_series_replaces_one_and_keeps_others(dataset):
    """Upserting a price series into an HA energy dataset replaces the price, keeps the meters."""
    win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 2, tzinfo=UTC))
    dataset.save_dataset(
        [_energy_frame("grid_import_t1", 1.0), _energy_frame("price_spot", 0.2)],
        win, "home_assistant", [],
        workspace_id=dataset.db.WORKSPACE_ID,
    )
    ds_before = dataset.load_latest(dataset.db.WORKSPACE_ID)
    original_id = ds_before.id

    # A new price frame with different values and a wider window.
    new_price = _energy_frame("price_spot", 9.9)  # kind is irrelevant to the merge mechanics
    later_win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 5, tzinfo=UTC))
    ds_id = dataset.upsert_series(new_price, "energy_charts", later_win, workspace_id=dataset.db.WORKSPACE_ID)

    assert ds_id == original_id  # merged into the SAME dataset, not a new one
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    names = {f.name for f in loaded.frames}
    assert names == {"grid_import_t1", "price_spot"}  # the meter survived
    # The price series was replaced (new first value), not appended.
    price = next(f for f in loaded.frames if f.name == "price_spot")
    assert abs(price.values[0] - 9.9) < 1e-9
    # Exactly one price_spot series_meta row (no duplicate).
    with dataset._connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM series_meta WHERE dataset_id = ? AND name = 'price_spot'",
            (ds_id,),
        ).fetchone()[0]
    assert n == 1
    # Per-series provenance updated for the replaced series only.
    assert loaded.series_sources["price_spot"] == "energy_charts"
    assert loaded.series_sources["grid_import_t1"] == "home_assistant"
    # The dataset window widened to the union.
    assert loaded.window[1] == datetime(2024, 3, 5, tzinfo=UTC)


def test_upsert_series_three_series_survival(dataset):
    """A,B saved, then C upserted, then B replaced: A and C survive, B is the new one, no dupes."""
    win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 2, tzinfo=UTC))
    dataset.save_dataset(
        [_energy_frame("grid_import_t1", 1.0), _energy_frame("grid_export_t1", 2.0)],
        win, "home_assistant", [],
        workspace_id=dataset.db.WORKSPACE_ID,
    )
    dataset.upsert_series(_energy_frame("price_spot", 0.2), "energy_charts", win, workspace_id=dataset.db.WORKSPACE_ID)
    dataset.upsert_series(_energy_frame("grid_export_t1", 7.7), "home_assistant", win, workspace_id=dataset.db.WORKSPACE_ID)

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert {f.name for f in loaded.frames} == {"grid_import_t1", "grid_export_t1", "price_spot"}
    export = next(f for f in loaded.frames if f.name == "grid_export_t1")
    assert abs(export.values[0] - 7.7) < 1e-9  # B was replaced, not the original 2.0
    with dataset._connect() as conn:
        rows = conn.execute(
            "SELECT name, COUNT(*) FROM series_meta GROUP BY name"
        ).fetchall()
    assert all(count == 1 for _name, count in rows)  # no duplicate rows for any series


def test_upsert_series_naive_window_into_aware_dataset(dataset):
    """A naive merge window must not crash against an aware stored window (regression, §4.4)."""
    aware_win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 5, tzinfo=UTC))
    dataset.save_dataset([_energy_frame("grid_import_t1", 1.0)], aware_win, "home_assistant", [], workspace_id=dataset.db.WORKSPACE_ID)
    # A naive window (no tzinfo) — dataset._as_utc normalises both sides before min()/max().
    naive_win = (datetime(2024, 3, 1), datetime(2024, 3, 8))
    dataset.upsert_series(_energy_frame("price_spot", 0.3), "energy_charts", naive_win, workspace_id=dataset.db.WORKSPACE_ID)
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert {f.name for f in loaded.frames} == {"grid_import_t1", "price_spot"}
    # Window widened to the union; the naive end was read as UTC.
    assert loaded.window[1] == datetime(2024, 3, 8, tzinfo=UTC)


def test_upsert_series_standalone_when_no_dataset(dataset):
    """With no dataset yet, upsert creates one holding just this series."""
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None
    frame = _energy_frame("price_spot", 0.3)
    win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 2, tzinfo=UTC))
    ds_id = dataset.upsert_series(frame, "energy_charts", win, workspace_id=dataset.db.WORKSPACE_ID)

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded is not None
    assert loaded.id == ds_id
    assert {f.name for f in loaded.frames} == {"price_spot"}
    assert loaded.series_sources == {"price_spot": "energy_charts"}
    assert loaded.source_type == "energy_charts"
    assert loaded.window == win


def test_upsert_series_rolls_back_and_keeps_the_existing_series(dataset):
    """An exception escaping `upsert_series` must leave the series the user already had.

    Regression (changelog 20260726 finding 9). `upsert_series` replaces a series by DELETE
    followed by INSERT. The connection is in autocommit mode so the migration can run its own
    `BEGIN IMMEDIATE`, and for a window that also meant the `with` block committed the DELETE and
    then let the exception escape before the INSERT — the user's existing series, silently gone.
    What is pinned here is the user-visible property: after the failure the OLD series is still
    there and still readable, not merely that the new one is absent.
    """
    win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 2, tzinfo=UTC))
    dataset.save_dataset(
        [_energy_frame("grid_import_t1", 1.0), _energy_frame("price_spot", 0.2)],
        win, "home_assistant", [],
        workspace_id=dataset.db.WORKSPACE_ID,
    )

    # Fail exactly where the regression bites: after the DELETE, before the replacement lands.
    def boom(*args, **kwargs):
        raise RuntimeError("crash between the delete and the insert")

    # Patched/restored by hand rather than with monkeypatch.undo(), which would also revert the
    # fixture's BATTERY_SIM_DATA_DIR setenv and send the assertions below at the real ./data.
    real = dataset._insert_series_meta
    dataset._insert_series_meta = boom
    try:
        with pytest.raises(RuntimeError):
            dataset.upsert_series(_energy_frame("price_spot", 9.9), "energy_charts", win, workspace_id=dataset.db.WORKSPACE_ID)
    finally:
        dataset._insert_series_meta = real

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded is not None
    # The pre-existing series survived the failed replacement: still listed, still loadable.
    assert {f.name for f in loaded.frames} == {"grid_import_t1", "price_spot"}
    # Its metadata is the ORIGINAL row — the DELETE was rolled back, not re-applied.
    assert loaded.series_sources["price_spot"] == "home_assistant"
    # The untouched series is entirely unaffected.
    meter = next(f for f in loaded.frames if f.name == "grid_import_t1")
    assert abs(meter.values[0] - 1.0) < 1e-9
    # Exactly one row, i.e. the rollback did not leave a duplicate either.
    with dataset._connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM series_meta WHERE name = 'price_spot'"
        ).fetchone()[0]
    assert n == 1

    # The documented LIMIT of the guarantee, pinned so it is a known property rather than a
    # surprise: `_save_frame` runs before the transaction and is not rolled back with it, so the
    # .npz holds the new array even though series_meta describes the old series. What the
    # transaction buys is that the series still exists and is readable — not that its values are
    # unchanged. See `upsert_series`' docstring for why the file half is left non-atomic.
    price = next(f for f in loaded.frames if f.name == "price_spot")
    assert abs(price.values[0] - 9.9) < 1e-9


def test_save_dataset_rolls_back_leaving_no_partial_dataset(dataset):
    """An exception escaping `save_dataset` must leave no `datasets` row behind.

    Regression (changelog 20260726 finding 9), the other half. `save_dataset` writes one
    `datasets` row and then one `series_meta` row per frame; under autocommit without an explicit
    transaction, a failure partway left a dataset row with missing or partial series beneath it,
    which `load_latest` would then restore as a dataset short of its series.
    """
    win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 2, tzinfo=UTC))
    frames = [_energy_frame("grid_import_t1", 1.0), _energy_frame("price_spot", 0.2)]

    calls = {"n": 0}
    real = dataset._insert_series_meta

    def fail_on_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("crash after the first series_meta row")
        return real(*args, **kwargs)

    # Restored by hand, not via monkeypatch.undo() — see the note in the upsert test above.
    dataset._insert_series_meta = fail_on_second
    try:
        with pytest.raises(RuntimeError):
            dataset.save_dataset(frames, win, "home_assistant", [], workspace_id=dataset.db.WORKSPACE_ID)
    finally:
        dataset._insert_series_meta = real

    # Neither the dataset row nor the one series_meta row that had already been inserted survives.
    with dataset._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM series_meta").fetchone()[0] == 0
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


# --- 4. endpoint: load price_spot from energy_charts over an in-range historical window --------

# A window fully inside committed NL-2024 data. last_on_disk is 2026-07 (> this window end), so
# bridge_date_range returns None → EnergyChartsSource.load hits no network (the source reads only
# on-disk CSVs). This is the "no network in tests" guarantee for the endpoint path.
_HIST_WINDOW = {"start": "2024-03-01T00:00:00+00:00", "end": "2024-03-05T00:00:00+00:00"}


def test_load_endpoint_attaches_price_from_committed_data(client):
    tc, main, dataset = client
    resp = tc.post(
        w("/data/slot/price_spot/load"),
        json={"source": "energy_charts", "window": _HIST_WINDOW},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["series"] == "price_spot"
    assert body["resolution_s"] == 3600  # NL-2024 is hourly
    assert body["intervals"] > 0
    assert "grid" in body

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded is not None
    assert "price_spot" in {f.name for f in loaded.frames}
    assert loaded.series_sources["price_spot"] == "energy_charts"


def test_load_endpoint_does_not_bump_source_generation(client):
    """A backend_load Confirm must NOT advance the source generation (specs §2.2).

    Only a persisted HA fetch bumps it. If a price load bumped it, the reload that Confirm triggers
    would invalidate the HA customization the user saved just before — the original reset bug.
    """
    tc, main, dataset = client
    from app import db

    assert db.source_generation(db.WORKSPACE_ID) == 0
    resp = tc.post(
        w("/data/slot/price_spot/load"),
        json={"source": "energy_charts", "window": _HIST_WINDOW},
    )
    assert resp.status_code == 200, resp.text
    # Unchanged: the load merged a series but issued no new generation.
    assert db.source_generation(db.WORKSPACE_ID) == 0


def test_load_endpoint_merges_into_existing_dataset(client):
    """A price load attaches to an HA-fetched energy dataset without discarding the meters."""
    tc, main, dataset = client
    # Seed an existing dataset (as the WS ingest path would leave one).
    frames = [_energy_frame("grid_import_t1", 1.0)]
    win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 5, tzinfo=UTC))
    dataset.save_dataset(frames, win, "home_assistant", [], workspace_id=dataset.db.WORKSPACE_ID)

    resp = tc.post(
        w("/data/slot/price_spot/load"),
        json={"source": "energy_charts", "window": _HIST_WINDOW},
    )
    assert resp.status_code == 200, resp.text

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert {f.name for f in loaded.frames} == {"grid_import_t1", "price_spot"}
    assert loaded.series_sources["grid_import_t1"] == "home_assistant"
    assert loaded.series_sources["price_spot"] == "energy_charts"


def test_load_endpoint_naive_window_into_aware_dataset(client):
    """A client window WITHOUT a UTC offset must not 500 when merging into an aware dataset.

    Regression: the union-window widening in upsert_series compared a naive request window with an
    aware stored window and raised TypeError → HTTP 500. _parse_window now normalises to UTC.
    """
    tc, main, dataset = client
    win = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 5, tzinfo=UTC))
    dataset.save_dataset([_energy_frame("grid_import_t1", 1.0)], win, "home_assistant", [], workspace_id=dataset.db.WORKSPACE_ID)

    # Window strings carry NO offset — the exact shape that used to crash.
    resp = tc.post(
        w("/data/slot/price_spot/load"),
        json={"source": "energy_charts",
              "window": {"start": "2024-03-01T00:00:00", "end": "2024-03-05T00:00:00"}},
    )
    assert resp.status_code == 200, resp.text
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert {f.name for f in loaded.frames} == {"grid_import_t1", "price_spot"}


# --- 5. endpoint error paths ------------------------------------------------------------------

def test_load_endpoint_unknown_slot_404(client):
    tc, _, _ = client
    resp = tc.post(
        w("/data/slot/not_a_slot/load"),
        json={"source": "energy_charts", "window": _HIST_WINDOW},
    )
    assert resp.status_code == 404
    assert "unknown slot" in resp.json()["detail"]


def test_load_endpoint_unknown_source_404(client):
    tc, _, _ = client
    resp = tc.post(
        w("/data/slot/price_spot/load"),
        json={"source": "no_such_source", "window": _HIST_WINDOW},
    )
    assert resp.status_code == 404
    assert "no_such_source" in resp.json()["detail"]


def test_load_endpoint_inverted_window_400(client):
    """`end` before `start` — `_parse_window` at `app/main.py:2407`.

    The same rule `app/ingest_ws.py:199` enforces on the socket, at the app's other entry point,
    and with a different failure SHAPE: an HTTP 400 here, an in-protocol `error` frame there
    (`tests/test_ingest_ws.py::test_an_inverted_window_is_rejected_over_the_socket`). Neither
    substitutes for the other, and until both were added the rule was asserted only by the
    packaged suite, which runs in the dispatch-only Release workflow.

    Placed here rather than beside the socket test because this route's other error paths already
    live in this section, and reaching `_parse_window` needs a slot and source that survive steps
    1–3 — `price_spot` + `energy_charts`, the same pair the tests above use.
    """
    tc, _, _ = client
    resp = tc.post(
        w("/data/slot/price_spot/load"),
        json={"source": "energy_charts",
              "window": {"start": "2024-03-05T00:00:00+00:00",
                         "end": "2024-03-01T00:00:00+00:00"}},
    )
    assert resp.status_code == 400, resp.text
    assert "window end must be after start" in resp.json()["detail"], resp.text


def test_load_endpoint_browser_fetch_source_rejected(client):
    """Home Assistant is browser_fetch: its frames arrive over WS, so loading it here is 4xx."""
    tc, _, _ = client
    # HA is available for every slot, so this exercises the kind guard specifically (not availability).
    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={"source": "home_assistant", "window": _HIST_WINDOW},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "browser_fetch" in detail or "ingest WebSocket" in detail


def test_load_endpoint_source_unavailable_for_slot(client):
    """energy_charts only fills price_spot; asking it for an energy slot is a 400."""
    tc, _, _ = client
    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={"source": "energy_charts", "window": _HIST_WINDOW},
    )
    assert resp.status_code == 400
    assert "not available" in resp.json()["detail"]


def test_load_endpoint_bad_window_400(client):
    tc, _, _ = client
    resp = tc.post(
        w("/data/slot/price_spot/load"),
        json={"source": "energy_charts", "window": {"start": "2024-03-05T00:00:00+00:00",
                                                    "end": "2024-03-01T00:00:00+00:00"}},
    )
    assert resp.status_code == 400
    assert "after start" in resp.json()["detail"]


# --- 6. the endpoint's CSV path: the binding, and its error statuses ---------------------------
#
# The drawer does not use this route — a fetch reifies staged slots over the ingest WS instead — but
# it is a real, reachable route with the same exposure, so it gets the binding and the same
# server-side validation rather than relying on being unused. `tests/test_csv_binding_reify.py`
# covers the WS path; what is specific here is the HTTP STATUS each failure answers.

_CSV_WINDOW = {"start": "2025-01-01T00:00:00+00:00", "end": "2025-01-01T04:00:00+00:00"}


@pytest.fixture()
def csv_client(tmp_path, monkeypatch):
    """`client`, plus `app.uploads` reloaded against the same isolated data dir.

    A separate fixture rather than an extra return value on `client`, so that the twelve tests above
    are untouched by this step — reloading one more module changes nothing for them, but adding a
    fourth element to their tuple unpacking would.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.dataset as dataset
    importlib.reload(dataset)
    import app.uploads as uploads
    importlib.reload(uploads)
    import app.workspaces as workspaces
    importlib.reload(workspaces)
    import app.deps as deps
    importlib.reload(deps)
    import app.main as main
    importlib.reload(main)
    seed_workspace()
    from fastapi.testclient import TestClient
    return TestClient(main.app), main, dataset, uploads


def _store_csv(uploads, *, workspace_id: str = "local", n: int = 6) -> str:
    """Store a small hourly wide CSV for `workspace_id`; return its upload id.

    Values alternate so the column is not non-decreasing — a monotone column is a cumulative meter
    register and `csv_wide` rejects it (D-KIND), which would make every test here fail for the wrong
    reason.
    """
    from app.domain import csv_wide

    lines = ["Tijdstip,Verbruik"]
    for i in range(n):
        lines.append(f"01-01-2025 {i:02d}:00:00,{0.5 if i % 2 else 0.1:.1f}")
    text = "\n".join(lines) + "\n"
    wide, summary = csv_wide.parse_and_summarise(text, "UTC")
    return uploads.create(
        workspace_id,
        filename="export.csv",
        tz="UTC",
        content=text,
        columns=[wide.timestamp_name, *wide.columns],
        rows=summary.rows,
        resolution_s=summary.resolution_s,
        first_ts=summary.first_ts,
        last_ts=summary.last_ts,
    ).id


def test_load_endpoint_loads_a_bound_csv_column(csv_client):
    """The body's `binding` is threaded through to the source and the series is merged."""
    tc, _main, dataset, uploads = csv_client
    upload_id = _store_csv(uploads)

    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={
            "source": "csv_upload",
            "window": _CSV_WINDOW,
            "binding": {"upload_id": upload_id, "column": "Verbruik", "unit": "kWh"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["series"] == "grid_import_t1"
    assert body["resolution_s"] == 3600
    assert body["intervals"] == 4  # the 4-hour window, not the 6-row file
    # `load_with_warnings` is what this route calls now, so the reply carries the §7.3 list (empty
    # for a clean file). A route still calling `load` would have no such key at all.
    assert body["warnings"] == []

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded.series_sources["grid_import_t1"] == "csv_upload"


def test_load_endpoint_reports_csv_warnings(csv_client):
    """A gap cell raises CSV_GAP_CELLS, and the route reports it rather than dropping it (§7.3)."""
    tc, _main, dataset, uploads = csv_client
    from app.domain import csv_wide

    text = "Tijdstip,Verbruik\n" + "".join(
        f"01-01-2025 {i:02d}:00:00,{'' if i == 1 else (0.5 if i % 2 else 0.1)}\n"
        for i in range(6)
    )
    wide, summary = csv_wide.parse_and_summarise(text, "UTC")
    upload_id = uploads.create(
        "local", filename="gappy.csv", tz="UTC", content=text,
        columns=[wide.timestamp_name, *wide.columns], rows=summary.rows,
        resolution_s=summary.resolution_s, first_ts=summary.first_ts, last_ts=summary.last_ts,
    ).id

    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={"source": "csv_upload", "window": _CSV_WINDOW,
              "binding": {"upload_id": upload_id, "column": "Verbruik"}},
    )
    assert resp.status_code == 200, resp.text
    assert [warn["code"] for warn in resp.json()["warnings"]] == ["CSV_GAP_CELLS"]


def test_load_endpoint_missing_binding_is_400_not_502(csv_client):
    """`CsvBindingError` → 400. It was a 502 via the bare `except Exception` (step 5 fixed it).

    502 means "the upstream service failed" and there is no upstream here; the condition is "you have
    not chosen a file and column yet", which is the client's input. The status is the assertion — a
    mutation that removed the `except CsvBindingError` branch answers 502 and fails here.
    """
    tc, _main, dataset, _uploads = csv_client

    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={"source": "csv_upload", "window": _CSV_WINDOW},
    )
    assert resp.status_code == 400, resp.text
    assert "no CSV binding" in resp.json()["detail"]
    # Nothing was merged: the load runs strictly before `upsert_series`.
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_load_endpoint_foreign_upload_id_is_400_and_persists_nothing(csv_client):
    """The security case on this route: a real upload id belonging to ANOTHER workspace.

    Under decision D-BIND the binding lives in browser localStorage, so `upload_id` is client-supplied
    on every call. `uploads.get` is workspace-scoped, which is what makes the foreign id resolve to
    None exactly as a nonexistent one does. The upload below genuinely exists — only the workspace
    asking for it is wrong — so the rejection cannot be "no such file" by accident.
    """
    tc, _main, dataset, uploads = csv_client
    seed_workspace("other")
    foreign_id = _store_csv(uploads, workspace_id="other")
    assert uploads.get("other", foreign_id) is not None
    assert uploads.get("local", foreign_id) is None

    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={"source": "csv_upload", "window": _CSV_WINDOW,
              "binding": {"upload_id": foreign_id, "column": "Verbruik"}},
    )
    assert resp.status_code == 400, resp.text
    assert "no longer has" in resp.json()["detail"]
    # Nothing persisted for the asking workspace, and the other workspace's upload is untouched.
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None
    assert uploads.get("other", foreign_id) is not None


def test_load_endpoint_absent_upload_id_is_400(csv_client):
    """A well-formed id no workspace has: the same 400, for the same reason."""
    tc, _main, dataset, _uploads = csv_client

    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={"source": "csv_upload", "window": _CSV_WINDOW,
              "binding": {"upload_id": "f" * 32, "column": "Verbruik"}},
    )
    assert resp.status_code == 400, resp.text
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_load_endpoint_malformed_upload_id_is_400(csv_client):
    """A traversal-shaped id is refused by `uploads._check_upload_id` before it becomes a path.

    That guard raises a plain `ValueError`, which is NOT a `CsvBindingError`, so this used to take
    the generic branch and answer 502 — "bad gateway" for the most obviously client-supplied bad
    input on the route. `CsvSource.load_with_warnings` now translates it at the point the binding is
    interpreted, so it lands in the 400 branch with every other unusable binding. The guard itself is
    unchanged and still rejects everything but 32 lowercase hex.

    Asserted as one status, not `in (400, 502)`: a two-value disjunction passes under either
    behaviour and so pins neither.
    """
    tc, _main, dataset, _uploads = csv_client

    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={"source": "csv_upload", "window": _CSV_WINDOW,
              "binding": {"upload_id": "../../etc/passwd", "column": "Verbruik"}},
    )
    assert resp.status_code == 400, resp.text
    # The rejected id is not echoed back (the reason is at `delete_upload`), so the message is
    # checked for its subject rather than for the segment submitted.
    assert "not a valid" in resp.json()["detail"]
    assert "etc/passwd" not in resp.json()["detail"]
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_load_endpoint_non_dict_binding_is_400(csv_client):
    """`"binding": "a string"` is malformed client input, not a failed upstream call.

    `load_slot` reads an unvalidated body, so `_csv_binding` gets whatever JSON the caller sent. It
    used to call `.get` on it unguarded and the resulting `AttributeError` surfaced as a 502 quoting
    `'str' object has no attribute 'get'`. Same class as the malformed `upload_id` above, same 400.
    """
    tc, _main, dataset, _uploads = csv_client

    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={"source": "csv_upload", "window": _CSV_WINDOW, "binding": "a string"},
    )
    assert resp.status_code == 400, resp.text
    assert "object" in resp.json()["detail"]
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_load_endpoint_unknown_column_is_502_and_persists_nothing(csv_client):
    """A column the file does not have is a load failure, and nothing is merged.

    502 rather than 400 because it arrives as a `CsvFormatError` through the generic branch, matching
    the route's existing "load failure" convention. What matters for correctness here is the second
    assertion: a failed load must not have written a dataset.
    """
    tc, _main, dataset, uploads = csv_client
    upload_id = _store_csv(uploads)

    resp = tc.post(
        w("/data/slot/grid_import_t1/load"),
        json={"source": "csv_upload", "window": _CSV_WINDOW,
              "binding": {"upload_id": upload_id, "column": "Nope"}},
    )
    assert resp.status_code == 502, resp.text
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_load_endpoint_csv_rejected_for_price_slot(csv_client):
    """D-PRICE: `available_for` excludes price_spot, so the source guard 400s before any binding."""
    tc, _main, _dataset, uploads = csv_client
    upload_id = _store_csv(uploads)

    resp = tc.post(
        w("/data/slot/price_spot/load"),
        json={"source": "csv_upload", "window": _CSV_WINDOW,
              "binding": {"upload_id": upload_id, "column": "Verbruik"}},
    )
    assert resp.status_code == 400
    assert "not available" in resp.json()["detail"]


def test_load_endpoint_energy_charts_still_takes_no_binding_extras(csv_client):
    """The non-CSV path must not be handed `workspace_id=`/`binding=` (it raises TypeError).

    `EnergyChartsSource.load`'s keyword-only extras are `opener`/`now`, so a blanket "thread the
    extras to every backend source" breaks the price path. A `binding` in the body is IGNORED for a
    source that does not take one, rather than passed through — asserted by sending one.
    """
    tc, _main, dataset, _uploads = csv_client

    resp = tc.post(
        w("/data/slot/price_spot/load"),
        json={"source": "energy_charts", "window": _HIST_WINDOW,
              "binding": {"upload_id": "f" * 32, "column": "irrelevant"}},
    )
    assert resp.status_code == 200, resp.text
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded.series_sources["price_spot"] == "energy_charts"
