"""Integration test for the WS ingest endpoint + persistence (specs §4.3, §5.1, §3.5).

Drives WS /w/{id}/data/ingest/ws with a scripted client (FastAPI TestClient) that replays the kind of
rows the browser forwards after fetching from Home Assistant, then asserts the dataset was
persisted and restores across a reload. Runs against a throwaway data dir so the SQLite DB and
the series .npz files never touch the working tree — the same isolation the smoke test uses.

Two protocol rules here were, until recently, asserted ONLY by `tests/test_packaged_ingest.py` and
so ran only in the dispatch-only Release workflow: an inverted header window
(`test_an_inverted_window_is_rejected_over_the_socket`, whose HTTP counterpart is
`tests/test_slot_load.py::test_load_endpoint_inverted_window_400`) and an unknown workspace being
refused at the HANDSHAKE with a 404 rather than an in-protocol error
(`test_an_unknown_workspace_fails_the_websocket_handshake`). That second one is worth having here
specifically because it has already caused a misdiagnosis — a rejected handshake looks exactly
like a bundle with no WebSocket support. See
`changelog/20260807-packaged-test-coverage-implementation.md`.

At the end there is a unit-level block on the optional per-slot `binding` a `backend_load` message may
carry (decision D-BIND of the CSV-import brief, step 5): the session records it verbatim for the route
to translate, and rejects a malformed one naming the field. What it deliberately does NOT check —
whether the unit is known, whether the upload exists — is pinned there too, since those belong to
`csv_wide` and to the route respectively. The end-to-end CSV reify path is
`tests/test_csv_binding_reify.py`.

    uv run pytest tests/test_ingest_ws.py
"""

import importlib
import os

import pytest

from tests.conftest import data_page, seed_workspace, w


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
                  "rows": [[1784505600000, 0.2955],
                           [1784509200000, 0.2899],
                           [1784512800000, 0.2924]]})
    assert ws.receive_json()["type"] == "progress"

    ws.send_json({"type": "done"})
    return ws.receive_json()


def test_valid_ingest_persists_and_reports(client):
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
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
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
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


def test_a_price_row_with_the_old_four_element_shape_still_ingests(client):
    """A stale cached ha_fetch.js may still send [start_ms, mean, min, max].

    The wire format narrowed to [start_ms, mean] when the §6.16 bracket became a derived
    quantity. The parser reads the first two elements and ignores the rest, so a browser holding
    the previous script is not broken by the change — and the min/max it sends is discarded, not
    stored anywhere.
    """
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header",
                      "window": {"start": "2026-07-20T00:00:00+00:00",
                                 "end": "2026-07-20T03:00:00+00:00"}})
        ws.send_json({"type": "series", "name": "grid_import_t1", "kind": "energy",
                      "unit": "kWh"})
        ws.send_json({"type": "rows", "name": "grid_import_t1",
                      "rows": [[1784505600000, 5127.0], [1784509200000, 5127.5]]})
        assert ws.receive_json()["type"] == "progress"
        ws.send_json({"type": "series", "name": "price_spot", "kind": "price",
                      "unit": "EUR/kWh"})
        ws.send_json({"type": "rows", "name": "price_spot",
                      "rows": [[1784505600000, 0.2955, 0.2929, 0.2982],
                               [1784509200000, 0.2899, 0.2886, 0.2982]]})
        assert ws.receive_json()["type"] == "progress"
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "result", result
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert loaded is not None
    price = next(f for f in loaded.frames if f.name == "price_spot")
    # The means landed; the two trailing elements left no trace on the frame.
    assert abs(price.values[0] - 0.2955) < 1e-9
    assert abs(price.values[1] - 0.2899) < 1e-9
    assert not hasattr(price, "value_min") and not hasattr(price, "value_max")


def test_the_browser_asks_home_assistant_for_the_mean_only():
    """The two ends of the narrowed wire format have to move together.

    `ha_fetch.js` builds the price rows the WS parser above reads. Nothing else in the suite runs
    that file — it is browser code — so a static scrape is the only thing standing between a
    backend that stopped reading positions 2 and 3 and a browser that still pays HA for them. It
    also pins the packing, since asking for "mean" alone while still packing `r.min`/`r.max` would
    silently send nulls.

    The two regexes tolerate quote style and inner whitespace on purpose. A scrape that matched
    the source byte for byte would fail on a Prettier run or a quote-style normalisation — changes
    with no behavioural content — and whoever hit that false positive would loosen or delete the
    test, costing the protection it exists for. The `nz(r.min)` / `nz(r.max)` check below is a
    plain substring on purpose: any spelling of it is a real regression.
    """
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "app" / "static" / "ha_fetch.js").read_text(
        encoding="utf-8"
    )
    # Scoped to the price branch: `payload.types` is also assigned ["sum"] for energy two lines
    # down, so an unscoped search for the assignment would pass with the price branch deleted.
    assert re.search(
        r"""slot\.kind\s*===\s*['"]price['"].*?payload\.types\s*=\s*\[\s*['"]mean['"]\s*\]""",
        js, re.S,
    ), (
        "ha_fetch.js still requests HA statistic columns beyond the mean (or dropped the price "
        "branch); the backend discards anything past position 1 of a price row"
    )
    assert re.search(
        r"""return\s*\[\s*r\.start\s*,\s*nz\(\s*r\.mean\s*\)\s*\]""", js
    ), "ha_fetch.js no longer packs a price row as [start_ms, mean]"
    assert "nz(r.min)" not in js and "nz(r.max)" not in js


def test_unknown_series_is_rejected(client):
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header",
                      "window": {"start": "2026-07-20T00:00:00+00:00", "end": "2026-07-20T02:00:00+00:00"}})
        ws.send_json({"type": "series", "name": "not_a_real_slot", "kind": "energy"})
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert "unknown series" in msg["message"]
    # Nothing persisted.
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


def test_rows_before_series_is_rejected(client):
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header",
                      "window": {"start": "2026-07-20T00:00:00+00:00", "end": "2026-07-20T02:00:00+00:00"}})
        ws.send_json({"type": "rows", "name": "grid_import_t1", "rows": [[0, 1.0]]})
        msg = ws.receive_json()
    assert msg["type"] == "error"


def test_done_before_header_is_rejected(client):
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "done"})
        msg = ws.receive_json()
    assert msg["type"] == "error"


def test_an_inverted_window_is_rejected_over_the_socket(client):
    """`end` before `start` in the header — `app/ingest_ws.py:199`.

    Sits with its neighbours above because it is the same class of check, but it had no
    unpackaged test until now: the rule was asserted only by
    `tests/test_packaged_ingest.py::test_level1_the_server_answers_a_header_frame`, which runs in
    the dispatch-only Release workflow. That test uses the inverted window as a convenient way to
    make the server originate a frame; the RULE it happens to exercise deserves its own coverage
    where it runs on every push.

    Asserts the message and not merely the type, so it cannot pass on whichever other error the
    header path might raise first — the neighbours above assert `type` alone because for them any
    rejection is the property; here the specific rule is.
    """
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header",
                      "window": {"start": "2026-07-20T02:00:00+00:00",
                                 "end": "2026-07-20T00:00:00+00:00"}})
        msg = ws.receive_json()
    assert msg["type"] == "error", msg
    assert "window end must be after start" in msg["message"], msg


def test_an_unknown_workspace_fails_the_websocket_handshake(client):
    """An unknown workspace id is rejected BEFORE `ws.accept()`, as an HTTP 404.

    `deps.get_workspace` rejects the dependency, and FastAPI answers a rejected WebSocket
    dependency with an ordinary HTTP 404 instead of upgrading. The client therefore sees a denial
    response, not an in-protocol `error` frame.

    **Pinned unpackaged because the packaged suite records this exact behaviour causing a
    misdiagnosis.** A rejected handshake looks identical to "this bundle has no WebSocket support"
    to anyone who has not read the route, and
    `tests/test_packaged_ingest.py::test_level1_an_unknown_workspace_fails_the_handshake` exists to
    keep that trap documented in executable form. It only ran at release time; this keeps the same
    fact visible in the source tree on every push.

    `TestClient` surfaces the denial as `WebSocketDenialResponse` carrying the real status code,
    which is a stronger assertion than the packaged test's substring match on "404" — that one has
    to inspect an exception's repr because a real `websockets` client raises a different type.
    """
    from starlette.testclient import WebSocketDenialResponse

    tc, main, dataset = client
    with pytest.raises(WebSocketDenialResponse) as excinfo:
        with tc.websocket_connect("/w/no-such-workspace/data/ingest/ws"):
            pass
    assert excinfo.value.status_code == 404, (
        "an unknown workspace should be refused by the workspace dependency with a 404. A "
        f"different status means the rejection moved somewhere else. Got {excinfo.value.status_code}."
    )


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
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
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

    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    frame = next(f for f in loaded.frames if f.name == "grid_import_t1")
    assert frame.resolution_s == 3600           # main frame is hourly
    assert frame.fine_resolution_s == 300       # fine copy recorded
    assert frame.fine_coverage is not None
    # Main frame has 4 deltas (5 hourly readings), not polluted by the 5-min rows.
    assert len(frame.values) == 4


def test_page_shows_sample_before_any_fetch(client):
    """With no dataset, the configure-data screen shows the roster and NO quality figures.

    Reads `/w/{id}/data`, not the results page: phase 4.2 deleted panel ①, so the roster exists on
    exactly one screen now (§2′.5).

    **The assertion inverted in phase 4.2 and that is the specified behaviour, not a loosening.**
    Panel ① rendered `sample_view()`'s quality box unconditionally, so this used to look for a
    sample-only quality string ("3 gaps totalling 4.2 h") as proof the empty state was the sample
    one. 4.1's review found that wrong on the new screen and gated the box on `has_dataset`
    (§2′.5's "present once data has loaded"): showing sample gap figures for data the user never
    supplied reads as a report about their own data. So the empty state is now the ABSENCE of those
    figures, and the presence of the roster that asks for them.
    """
    tc, main, dataset = client
    html = tc.get(data_page()).text
    assert 'id="slot-roster"' in html, "the empty state must still ask for the data"
    # The sample's quality figures must NOT be on screen before anything is loaded.
    assert "3 gaps totalling 4.2 h" not in html
    assert "Data quality" not in html


def test_page_reflects_persisted_dataset_after_ingest(client):
    """After a WS ingest, the configure-data screen renders from the persisted dataset (§3.5)."""
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _drive_valid_ingest(ws)
    assert result["type"] == "result"

    html = tc.get(data_page()).text
    # The quality box appears once data has loaded (§2′.5) and reports the real frames.
    assert "Data quality" in html
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
    result frame carries the new value. The configure-data screen (#source-generation) reflects the
    current value — it is the only screen that renders that node since phase 4.2, because it is the
    only one whose JS reconciles a locally-staged mapping against it (§2′.11).
    """
    tc, main, dataset = client
    from app import db

    assert db.source_generation(db.WORKSPACE_ID) == 0
    # Before any fetch the page renders generation 0.
    assert '<script id="source-generation" type="application/json">0</script>' in tc.get(data_page()).text

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _drive_valid_ingest(ws)
    assert result["generation"] == 1
    assert db.source_generation(db.WORKSPACE_ID) == 1
    assert '<script id="source-generation" type="application/json">1</script>' in tc.get(data_page()).text

    # A second fetch bumps again — this is what makes another client's stored customization stale.
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        result = _drive_valid_ingest(ws)
    assert result["generation"] == 2
    assert db.source_generation(db.WORKSPACE_ID) == 2


# The historical window the committed Energy-Charts CSVs cover, so a backend load hits no network.
_HIST_WINDOW = {"start": "2024-03-01T00:00:00+00:00", "end": "2024-03-05T00:00:00+00:00"}


def test_fetch_reifies_ha_and_backend_into_one_dataset(client):
    """The reported bug: an HA slot + a staged backend price reify into ONE dataset (specs §2.2).

    A fetch streams grid_import_t1 from HA and declares price_spot as a backend_load (energy_charts).
    On `done` the backend loads the price server-side and persists both together — so the price is
    NOT lost, unlike the old flow where save_dataset created a fresh dataset that orphaned it.
    """
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
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
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    names = {f.name for f in loaded.frames}
    assert names == {"grid_import_t1", "price_spot"}          # BOTH survive
    assert loaded.series_sources["grid_import_t1"] == "home_assistant"
    assert loaded.series_sources["price_spot"] == "energy_charts"


def test_fetch_with_only_a_backend_slot(client):
    """A backend-only fetch (energy_charts spot price, no HA slots) reifies a dataset (specs §2.2)."""
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        ws.send_json({"type": "header", "source": "home_assistant", "window": _HIST_WINDOW})
        ws.send_json({"type": "backend_load", "name": "price_spot",
                      "source": "energy_charts", "window": _HIST_WINDOW})
        ws.send_json({"type": "done"})
        result = ws.receive_json()

    assert result["type"] == "result"
    loaded = dataset.load_latest(dataset.db.WORKSPACE_ID)
    assert {f.name for f in loaded.frames} == {"price_spot"}
    assert loaded.series_sources["price_spot"] == "energy_charts"


def test_fetch_backend_failure_is_all_or_nothing(client):
    """A backend-load failure fails the whole fetch and persists nothing (specs §2.2, §3.2).

    An unknown source key makes the reify raise → LOAD_FAILED. The HA series streamed alongside it
    must NOT be persisted: the dataset is unchanged (still none here).
    """
    tc, main, dataset = client
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
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
    assert dataset.load_latest(dataset.db.WORKSPACE_ID) is None


# ── The setup-band answers ride on the header and are committed by the fetch (§2.1) ──────────


def _drive_with_setup(ws, **setup):
    """`_drive_valid_ingest` with extra header fields — the setup answers this fetch commits."""
    ws.send_json({
        "type": "header", "source": "home_assistant",
        "window": {"start": "2026-07-20T00:00:00+00:00", "end": "2026-07-20T02:00:00+00:00"},
        **setup,
    })
    ws.send_json({"type": "series", "name": "grid_import_t1", "kind": "energy", "unit": "kWh"})
    ws.send_json({"type": "rows", "name": "grid_import_t1",
                  "rows": [[1784505600000, 5127.0], [1784509200000, 5127.5]]})
    assert ws.receive_json()["type"] == "progress"
    ws.send_json({"type": "series", "name": "grid_export_t1", "kind": "energy", "unit": "kWh"})
    ws.send_json({"type": "rows", "name": "grid_export_t1",
                  "rows": [[1784505600000, 590.0], [1784509200000, 590.0]]})
    assert ws.receive_json()["type"] == "progress"
    ws.send_json({"type": "done"})
    return ws.receive_json()


def test_the_fetch_commits_the_setup_answers(client):
    """The whole point of the change: the answers reach disk, and the toggle is no longer inert."""
    tc, main, _dataset = client
    import app.simconfig_store as store

    assert store.load(store.db.WORKSPACE_ID).has_pv is True    # appendix-A defaults before any fetch
    assert store.load(store.db.WORKSPACE_ID).has_battery is False

    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        assert _drive_with_setup(ws, has_pv=False, has_battery=True)["type"] == "result"

    cfg = store.load(store.db.WORKSPACE_ID)
    assert cfg.has_pv is False
    assert cfg.has_battery is True


def test_a_header_without_the_setup_fields_leaves_the_stored_answers_alone(client):
    """Absent ≠ false. An older client that does not send the fields must not silently reset the
    user's configuration — the reason `on_header` distinguishes missing from present-and-false.
    """
    tc, main, _dataset = client
    import app.simconfig_store as store
    from app.domain.simconfig import SimulationConfig

    store.save(SimulationConfig(has_pv=False, has_battery=True), store.db.WORKSPACE_ID)
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        assert _drive_valid_ingest(ws)["type"] == "result"   # no has_pv/has_battery in its header

    cfg = store.load(store.db.WORKSPACE_ID)
    assert cfg.has_pv is False
    assert cfg.has_battery is True


def test_committing_no_pv_normalises_the_stored_coupling(client):
    """§2.5: without PV, pv_coupling is forced null and battery coupling AC. The commit path
    assigns the field directly, so it must re-run the invariants before writing — otherwise a
    household that just turned PV off keeps a stored DC coupling for an array it does not have.
    """
    tc, main, _dataset = client
    import app.simconfig_store as store
    from app.domain.simconfig import Coupling, PvCoupling, SimulationConfig, TopologyConfig

    store.save(SimulationConfig(
        has_pv=True, topology=TopologyConfig(pv_coupling=PvCoupling.DC_HYBRID)
    ), store.db.WORKSPACE_ID)
    with tc.websocket_connect(w("/data/ingest/ws")) as ws:
        assert _drive_with_setup(ws, has_pv=False)["type"] == "result"

    cfg = store.load(store.db.WORKSPACE_ID)
    assert cfg.has_pv is False
    assert cfg.pv_coupling is None
    assert cfg.coupling is Coupling.AC


def test_the_ingest_session_records_the_setup_answers():
    """Unit-level counterpart: the session distinguishes absent from present-and-false."""
    from app.ingest_ws import IngestSession

    win = {"start": "2026-07-20T00:00:00+00:00", "end": "2026-07-20T02:00:00+00:00"}

    absent = IngestSession()
    absent.on_header({"type": "header", "window": win})
    assert absent.setup_has_pv is None and absent.setup_has_battery is None

    present = IngestSession()
    present.on_header({"type": "header", "window": win, "has_pv": False, "has_battery": True})
    assert present.setup_has_pv is False and present.setup_has_battery is True



# --- the optional per-slot `binding` on a backend_load message (D-BIND, step 5) ----------------
#
# Unit-level, against `IngestSession` directly rather than through the socket, because what is under
# test is the PURE layer's contract: the session records the binding verbatim for the route to
# translate, and rejects a malformed one before any I/O could happen. The end-to-end behaviour —
# loading, provenance, the security check on `upload_id` — is `tests/test_csv_binding_reify.py`.

_BINDING_WIN = {"start": "2026-07-20T00:00:00+00:00", "end": "2026-07-20T02:00:00+00:00"}


def _session_with_header():
    from app.ingest_ws import IngestSession

    session = IngestSession()
    session.on_header({"type": "header", "window": _BINDING_WIN})
    return session


def test_backend_load_records_the_binding_verbatim():
    """The session stores the raw dict, unconverted — the route owns the translation.

    Asserted as identity-of-content rather than "it is a CsvBinding", because keeping it a plain dict
    is the deliberate choice recorded on `BackendLoadRequest`: the protocol layer must not import an
    adapter from `app/sources/`, and the field is generic so a second configurable source can reuse
    it without this module learning what the configuration means.
    """
    session = _session_with_header()
    binding = {"upload_id": "a" * 32, "column": "Verbruik_T1", "unit": "Wh"}
    session.on_backend_load({
        "type": "backend_load", "name": "grid_import_t1", "source": "csv_upload",
        "window": _BINDING_WIN, "binding": binding,
    })
    req = session.backend_loads["grid_import_t1"]
    assert req.binding == binding
    assert req.source == "csv_upload"


def test_backend_load_without_a_binding_records_none():
    """Absent is the normal case for every source but CSV, and is not an error here.

    A CSV slot that needs one and did not send it is the SOURCE's to reject (`CsvBindingError`), so
    that this module never has to know which source keys require configuration.
    """
    session = _session_with_header()
    session.on_backend_load({
        "type": "backend_load", "name": "price_spot", "source": "energy_charts",
        "window": _BINDING_WIN,
    })
    assert session.backend_loads["price_spot"].binding is None


def test_backend_load_with_an_explicitly_null_binding_records_none():
    """A client that sends `"binding": null` is treated as one that sent no binding at all."""
    session = _session_with_header()
    session.on_backend_load({
        "type": "backend_load", "name": "price_spot", "source": "energy_charts",
        "window": _BINDING_WIN, "binding": None,
    })
    assert session.backend_loads["price_spot"].binding is None


@pytest.mark.parametrize(
    "binding, expected",
    [
        ("nope", "must be an object"),
        ([1, 2], "must be an object"),
        ({}, "missing 'upload_id'"),
        ({"upload_id": None, "column": "A"}, "missing 'upload_id'"),
        ({"upload_id": 42, "column": "A"}, "missing 'upload_id'"),
        ({"upload_id": "a" * 32}, "missing 'column'"),
        ({"upload_id": "a" * 32, "column": None}, "missing 'column'"),
        ({"upload_id": "a" * 32, "column": "A", "unit": []}, "non-string 'unit'"),
    ],
)
def test_a_malformed_binding_is_rejected_and_records_nothing(binding, expected):
    """Shape rejection names the field, and the slot is not recorded at all.

    The second assertion is the one worth having: a validator that raised AFTER inserting into
    `backend_loads` would leave a half-recorded slot behind, and the session is reused for the rest of
    the stream.
    """
    from app.ingest_ws import IngestError

    session = _session_with_header()
    with pytest.raises(IngestError) as exc:
        session.on_backend_load({
            "type": "backend_load", "name": "grid_import_t1", "source": "csv_upload",
            "window": _BINDING_WIN, "binding": binding,
        })
    assert expected in str(exc.value)
    assert "grid_import_t1" not in session.backend_loads


def test_a_binding_with_an_unknown_unit_is_NOT_rejected_by_the_session():
    """Unit vocabulary belongs to `csv_wide.UNIT_FACTORS`, not to the protocol layer.

    Pinned as a deliberate non-behaviour: a reader adding a unit should have exactly one place to
    change it, and `CsvSource` already rejects an unknown one by name before reading the file
    (`bad_unit`). A copy of the vocabulary here would be a second place to forget.
    """
    session = _session_with_header()
    session.on_backend_load({
        "type": "backend_load", "name": "grid_import_t1", "source": "csv_upload",
        "window": _BINDING_WIN,
        "binding": {"upload_id": "a" * 32, "column": "A", "unit": "MWh"},
    })
    assert session.backend_loads["grid_import_t1"].binding["unit"] == "MWh"
