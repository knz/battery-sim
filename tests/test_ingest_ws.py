"""Integration test for the WS ingest endpoint + persistence (specs §4.3, §5.1, §3.5).

Drives WS /data/ingest/ws with a scripted client (FastAPI TestClient) that replays the kind of
rows the browser forwards after fetching from Home Assistant, then asserts the dataset was
persisted and restores across a reload. Runs against a throwaway data dir so the SQLite DB and
the series .npz files never touch the working tree — the same isolation the smoke test uses.

    uv run pytest tests/test_ingest_ws.py
"""

import importlib
import os

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient whose app writes to an isolated data dir.

    app.config resolves the data dir at import time via the env var, and app.main binds CONFIG
    at import, so we set the env and reload both before constructing the app.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.dataset as dataset
    importlib.reload(dataset)
    import app.main as main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    return TestClient(main.app), main, dataset


def _drive_valid_ingest(ws):
    """Send a minimal valid stream: 2 energy series + 1 price series, hourly."""
    ws.send_json({
        "type": "header", "source": "home_assistant",
        "window": {"start": "2026-07-20T00:00:00+00:00", "end": "2026-07-20T02:00:00+00:00"},
    })
    ws.send_json({"type": "series", "name": "grid_import_t1", "kind": "energy", "unit": "kWh",
                  "stat_id": "sensor.meter_import_t1"})
    ws.send_json({"type": "rows", "name": "grid_import_t1",
                  "rows": [[1784505600000, 5127.0], [1784509200000, 5127.5], [1784512800000, 5128.4]]})
    assert ws.receive_json()["type"] == "progress"

    ws.send_json({"type": "series", "name": "grid_export_t1", "kind": "energy", "unit": "kWh"})
    ws.send_json({"type": "rows", "name": "grid_export_t1",
                  "rows": [[1784505600000, 590.0], [1784509200000, 590.0], [1784512800000, 590.2]]})
    assert ws.receive_json()["type"] == "progress"

    ws.send_json({"type": "series", "name": "price_spot", "kind": "price", "unit": "EUR/kWh"})
    ws.send_json({"type": "rows", "name": "price_spot",
                  "rows": [[1784505600000, 0.2955, 0.2929, 0.2982],
                           [1784509200000, 0.2899, 0.2886, 0.2982],
                           [1784512800000, 0.2924, 0.2858, 0.2978]]})
    assert ws.receive_json()["type"] == "progress"

    ws.send_json({"type": "done"})
    return ws.receive_json()


def test_valid_ingest_persists_and_reports(client):
    tc, main, dataset = client
    with tc.websocket_connect("/data/ingest/ws") as ws:
        result = _drive_valid_ingest(ws)

    assert result["type"] == "result"
    assert result["series"] == 3
    assert result["dataset_id"] >= 1
    grid = result["grid"]
    assert grid["grid_s"] == 3600  # hourly energy grid
    price = next(s for s in grid["series"] if s["name"] == "price_spot")
    # Prices here are also hourly, so exact — no granularity lost.
    assert price["reconciliation"] == "exact"

    # It restored: load_latest returns the frames with the right names.
    loaded = dataset.load_latest()
    assert loaded is not None
    names = {f.name for f in loaded.frames}
    assert names == {"grid_import_t1", "grid_export_t1", "price_spot"}
    # Energy frame differenced: 3 readings → 2 interval deltas.
    imp = next(f for f in loaded.frames if f.name == "grid_import_t1")
    assert len(imp.values) == 2
    assert abs(imp.values[0] - 0.5) < 1e-9
    # The HA statistic id round-trips through series_meta so a fetched slot renders its entity
    # server-side after a reload (specs §2.2). Series sent without a stat_id keep None.
    assert imp.stat_id == "sensor.meter_import_t1"
    assert next(f for f in loaded.frames if f.name == "grid_export_t1").stat_id is None


def test_unknown_series_is_rejected(client):
    tc, main, dataset = client
    with tc.websocket_connect("/data/ingest/ws") as ws:
        ws.send_json({"type": "header",
                      "window": {"start": "2026-07-20T00:00:00+00:00", "end": "2026-07-20T02:00:00+00:00"}})
        ws.send_json({"type": "series", "name": "not_a_real_slot", "kind": "energy"})
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert "unknown series" in msg["message"]
    # Nothing persisted.
    assert dataset.load_latest() is None


def test_rows_before_series_is_rejected(client):
    tc, main, dataset = client
    with tc.websocket_connect("/data/ingest/ws") as ws:
        ws.send_json({"type": "header",
                      "window": {"start": "2026-07-20T00:00:00+00:00", "end": "2026-07-20T02:00:00+00:00"}})
        ws.send_json({"type": "rows", "name": "grid_import_t1", "rows": [[0, 1.0]]})
        msg = ws.receive_json()
    assert msg["type"] == "error"


def test_done_before_header_is_rejected(client):
    tc, main, dataset = client
    with tc.websocket_connect("/data/ingest/ws") as ws:
        ws.send_json({"type": "done"})
        msg = ws.receive_json()
    assert msg["type"] == "error"


def test_two_resolutions_are_not_differenced_together(client):
    """Hourly + 5-min for one series: the main frame is hourly, the fine copy is separate.

    Regression for the real-data bug where concatenating the two native resolutions and
    differencing across the boundary fabricated an AMBIGUOUS_REGISTER_DECREASE. The 5-minute
    window restarts at a lower cumulative sum than the hourly window's tail, so a naive concat
    produces a big negative step; keeping the periods apart (specs §4.3) avoids it entirely.
    """
    tc, main, dataset = client
    HOUR_MS = 3_600_000
    FIVE_MS = 300_000
    with tc.websocket_connect("/data/ingest/ws") as ws:
        ws.send_json({"type": "header",
                      "window": {"start": "2026-07-01T00:00:00+00:00", "end": "2026-07-10T00:00:00+00:00"}})
        ws.send_json({"type": "series", "name": "grid_import_t1", "kind": "energy"})
        # Hourly full window: register climbing 100.0 → 100.4 over 5 readings.
        hourly = [[i * HOUR_MS, 100.0 + i * 0.1] for i in range(5)]
        ws.send_json({"type": "rows", "name": "grid_import_t1", "period": "hour", "rows": hourly})
        ws.receive_json()
        # 5-minute trailing copy — its cumulative sum is LOWER (a sub-window register), which a
        # naive concat after the hourly tail (100.4) would read as a huge decrease.
        fine = [[100 * HOUR_MS + i * FIVE_MS, 5.0 + i * 0.01] for i in range(6)]
        ws.send_json({"type": "rows", "name": "grid_import_t1", "period": "5minute", "rows": fine})
        ws.receive_json()
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "result"
    # No ambiguous-decrease warning: the two resolutions were never differenced across.
    assert not any(w["code"] == "AMBIGUOUS_REGISTER_DECREASE" for w in result["warnings"])

    loaded = dataset.load_latest()
    frame = next(f for f in loaded.frames if f.name == "grid_import_t1")
    assert frame.resolution_s == 3600           # main frame is hourly
    assert frame.fine_resolution_s == 300       # fine copy recorded
    assert frame.fine_coverage is not None
    # Main frame has 4 deltas (5 hourly readings), not polluted by the 5-min rows.
    assert len(frame.values) == 4


def test_page_shows_sample_before_any_fetch(client):
    """With no dataset, panel ① renders the static sample (empty state)."""
    tc, main, dataset = client
    html = tc.get("/").text
    # A sample-only quality string the real view-model never emits. (The sample's placeholder
    # entity ids are no longer rendered — the HA entity is chosen in the drawer, not shown as a
    # main-row column — so a quality-string marker is used instead.)
    assert "3 gaps totalling 4.2 h" in html


def test_page_reflects_persisted_dataset_after_ingest(client):
    """After a WS ingest, GET / renders panel ① from the persisted dataset (specs §3.5)."""
    tc, main, dataset = client
    with tc.websocket_connect("/data/ingest/ws") as ws:
        result = _drive_valid_ingest(ws)
    assert result["type"] == "result"

    html = tc.get("/").text
    # The real view-model's summary reports the fetched series count and grid.
    assert "3 series" in html
    # The real granularity table uses role labels; the sample's placeholder entity ids are gone.
    assert "sensor.electricity_meter_import_t1" not in html
    # Register summary from real frames (specs §6.4 availability).
    assert "import T1 mapped" in html
    # The fetched HA slot renders its persisted statistic id server-side (specs §2.2), both as the
    # button label and in data-slot-stat-id — so it survives a reload with no client state.
    assert "sensor.meter_import_t1" in html
    assert 'data-slot-stat-id="sensor.meter_import_t1"' in html

    # The data summary band (§2.3a) renders from the same dataset, and each DERIVED metric carries
    # an ⓘ .slot-info-btn explaining its computation (shared #slot-info-dialog, wired by ha_fetch.js).
    # This ingest has no solar, so the Household metrics get buttons but Solar does not exist.
    assert 'data-info-title="Consumption"' in html
    assert 'data-info-title="Self-sufficiency"' in html
    # The Consumption blurb is the no-existing-battery variant (no battery series was ingested).
    assert "load = grid import − grid export + solar produced." in html
    assert "battery discharged − battery charged" not in html


def test_fetch_bumps_source_generation(client):
    """A persisted fetch advances the source generation and reports it (specs §2.2).

    The generation starts at 0, becomes 1 after the first fetch, 2 after the second, and each
    result frame carries the new value. The page (#source-generation) reflects the current value.
    """
    tc, main, dataset = client
    from app import db

    assert db.source_generation() == 0
    # Before any fetch the page renders generation 0.
    assert '<script id="source-generation" type="application/json">0</script>' in tc.get("/").text

    with tc.websocket_connect("/data/ingest/ws") as ws:
        result = _drive_valid_ingest(ws)
    assert result["generation"] == 1
    assert db.source_generation() == 1
    assert '<script id="source-generation" type="application/json">1</script>' in tc.get("/").text

    # A second fetch bumps again — this is what makes another client's stored customization stale.
    with tc.websocket_connect("/data/ingest/ws") as ws:
        result = _drive_valid_ingest(ws)
    assert result["generation"] == 2
    assert db.source_generation() == 2


# The historical window the committed Energy-Charts CSVs cover, so a backend load hits no network.
_HIST_WINDOW = {"start": "2024-03-01T00:00:00+00:00", "end": "2024-03-05T00:00:00+00:00"}


def test_fetch_reifies_ha_and_backend_into_one_dataset(client):
    """The reported bug: an HA slot + a staged backend price reify into ONE dataset (specs §2.2).

    A fetch streams grid_import_t1 from HA and declares price_spot as a backend_load (energy_charts).
    On `done` the backend loads the price server-side and persists both together — so the price is
    NOT lost, unlike the old flow where save_dataset created a fresh dataset that orphaned it.
    """
    tc, main, dataset = client
    with tc.websocket_connect("/data/ingest/ws") as ws:
        ws.send_json({"type": "header", "source": "home_assistant",
                      "window": {"start": "2024-03-01T00:00:00+00:00",
                                 "end": "2024-03-05T00:00:00+00:00"}})
        ws.send_json({"type": "series", "name": "grid_import_t1", "kind": "energy",
                      "stat_id": "sensor.meter_import_t1"})
        ws.send_json({"type": "rows", "name": "grid_import_t1",
                      "rows": [[1709251200000, 100.0], [1709254800000, 100.5]]})
        assert ws.receive_json()["type"] == "progress"
        # Stage the spot price as a backend load — no prior POST, reified here.
        ws.send_json({"type": "backend_load", "name": "price_spot",
                      "source": "energy_charts", "window": _HIST_WINDOW})
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "result"
    loaded = dataset.load_latest()
    names = {f.name for f in loaded.frames}
    assert names == {"grid_import_t1", "price_spot"}          # BOTH survive
    assert loaded.series_sources["grid_import_t1"] == "home_assistant"
    assert loaded.series_sources["price_spot"] == "energy_charts"


def test_fetch_with_only_a_backend_slot(client):
    """A backend-only fetch (energy_charts spot price, no HA slots) reifies a dataset (specs §2.2)."""
    tc, main, dataset = client
    with tc.websocket_connect("/data/ingest/ws") as ws:
        ws.send_json({"type": "header", "source": "home_assistant", "window": _HIST_WINDOW})
        ws.send_json({"type": "backend_load", "name": "price_spot",
                      "source": "energy_charts", "window": _HIST_WINDOW})
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "result"
    loaded = dataset.load_latest()
    assert {f.name for f in loaded.frames} == {"price_spot"}
    assert loaded.series_sources["price_spot"] == "energy_charts"


def test_fetch_backend_failure_is_all_or_nothing(client):
    """A backend-load failure fails the whole fetch and persists nothing (specs §2.2, §3.2).

    An unknown source key makes the reify raise → LOAD_FAILED. The HA series streamed alongside it
    must NOT be persisted: the dataset is unchanged (still none here).
    """
    tc, main, dataset = client
    with tc.websocket_connect("/data/ingest/ws") as ws:
        ws.send_json({"type": "header", "source": "home_assistant",
                      "window": {"start": "2024-03-01T00:00:00+00:00",
                                 "end": "2024-03-05T00:00:00+00:00"}})
        ws.send_json({"type": "series", "name": "grid_import_t1", "kind": "energy"})
        ws.send_json({"type": "rows", "name": "grid_import_t1",
                      "rows": [[1709251200000, 100.0], [1709254800000, 100.5]]})
        assert ws.receive_json()["type"] == "progress"
        ws.send_json({"type": "backend_load", "name": "price_spot",
                      "source": "no_such_source", "window": _HIST_WINDOW})
        ws.send_json({"type": "done"})
        msg = ws.receive_json()

    assert msg["type"] == "error"
    # Nothing persisted — the HA series did not sneak through.
    assert dataset.load_latest() is None
