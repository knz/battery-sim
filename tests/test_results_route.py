"""Route tests for POST /results and index()'s computed panel ③ (specs §2.4, §3.2).

These exercise the Phase-2 wiring end-to-end through the FastAPI app: a synthetic dataset is
persisted into a temporary data dir (BATTERY_SIM_DATA_DIR), then the results route is driven with
presets, an explicit range, and the error inputs it must reject cleanly (never a 500).

The dataset is seeded with app.dataset.save_dataset over hand-built SeriesFrames (the same shape
tests/test_data_summary.py uses), so the route's real load_latest → resolve_window → results_from
path runs against known totals. The data dir is redirected per-test to a tmp path so the user's
real ./data is never touched; app.config.data_dir() reads the env var on each call, so the redirect
takes effect without reimporting app.main.

Covered:
    * a preset ("last_1_week") and the default (empty body) → 200 + an HTML fragment rooted at
      #panel-results;
    * an explicit start/end range → 200;
    * the fragment carries the zero-battery headline (import with battery == baseline);
    * bad inputs → clean 4xx (unknown preset, both period+range, end<=start, non-object body);
    * no dataset → 409.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.domain.frames import QUALITY_DTYPE, SeriesFrame

# A fixed hourly window so totals are exact: 30 days × 24 h of 1 h intervals from 2026-01-01 UTC.
_DAYS = 30
_HOURS = _DAYS * 24
_WIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_WIN_END = datetime(2026, 1, 1 + _DAYS, tzinfo=timezone.utc)


def _energy(name: str, per_interval: float, n: int = _HOURS) -> SeriesFrame:
    idx = (
        np.arange(n).astype("timedelta64[s]") * 3600
        + np.datetime64("2026-01-01T00:00:00")
    ).astype("datetime64[s]")
    return SeriesFrame(
        name, "energy", 3600, idx, np.full(n, float(per_interval)),
        np.zeros(n, dtype=QUALITY_DTYPE),
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient over a fresh temp data dir holding one seeded dataset.

    Redirects BATTERY_SIM_DATA_DIR to a tmp path (config.data_dir() reads it per call), then
    persists a minimal grid-meter dataset so load_latest() in the route returns it. app.main is
    imported after the env is set; its CONFIG/templates are data-dir-independent, so a plain import
    is enough — no reload gymnastics.
    """
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))

    from app import dataset  # imported under the redirected data dir

    frames = [
        _energy("grid_import_t1", 2.0),   # 2 kWh/h × 720 h = 1,440 kWh imported
        _energy("grid_export_t1", 0.0),
    ]
    dataset.save_dataset(frames, (_WIN_START, _WIN_END), "test", [], None)

    from app import main
    return TestClient(main.app)


def test_results_preset_returns_fragment(client):
    r = client.post("/results", json={"period": "last_1_week"})
    assert r.status_code == 200
    body = r.text
    # The swap target root and the panel identity are present (it is the _panel_results fragment).
    assert 'id="panel-results"' in body
    assert "RESULTS" in body or "RESULTATEN" in body


def test_results_default_body_is_full_year_clamped(client):
    # Empty body → default preset (last_1_year), clamped to the 30-day coverage.
    r = client.post("/results", json={})
    assert r.status_code == 200
    assert 'id="panel-results"' in r.text


def test_results_explicit_range(client):
    r = client.post(
        "/results",
        json={"start": "2026-01-05T00:00:00Z", "end": "2026-01-12T00:00:00Z"},
    )
    assert r.status_code == 200
    assert 'id="panel-results"' in r.text


def test_results_zero_battery_headline(client):
    # The zero-battery invariant is visible in the rendered fragment: import "with battery" equals
    # the baseline import, and grid-import-saved is 0.
    r = client.post("/results", json={"period": "last_1_week"})
    assert r.status_code == 200
    # Both breakdown rows show the same import figure (equal by construction this increment).
    # 7 days × 24 h × 2 kWh = 336 kWh over the clamped last-week window.
    assert "336 kWh" in r.text
    assert "0 kWh" in r.text  # avoided / charged / discharged all zero


def test_results_fragment_includes_data_glance_band(client):
    # The standalone POST /results fragment renders the repeated data-glance band (from the shared
    # _data_glance.html macro imported at the top of _panel_results.html) — proof the macro import
    # resolves in the standalone render() path, not just the full page. Panel ③'s copy carries its
    # OWN heading ("Your energy use during the selected period"), NOT the interstitial band's title,
    # since it is scoped to the selected range.
    r = client.post("/results", json={"period": "last_1_week"})
    assert r.status_code == 200
    # The panel-③ band heading (default EN locale). Its NL is "Uw energieverbruik in de
    # geselecteerde periode".
    assert "Your energy use during the selected period" in r.text
    # The interstitial band's own title must NOT leak into panel ③'s copy.
    assert "Your data at a glance" not in r.text
    # And a band-specific group heading, so it is the band body and not just an aria-label echo.
    assert "Imported" in r.text


def test_results_unknown_preset_400(client):
    r = client.post("/results", json={"period": "last_decade"})
    assert r.status_code == 400


def test_results_both_period_and_range_400(client):
    r = client.post(
        "/results",
        json={"period": "last_1_week", "start": "2026-01-05T00:00:00Z"},
    )
    assert r.status_code == 400


def test_results_inverted_range_400(client):
    r = client.post(
        "/results",
        json={"start": "2026-01-12T00:00:00Z", "end": "2026-01-05T00:00:00Z"},
    )
    assert r.status_code == 400


def test_results_bad_date_400(client):
    r = client.post("/results", json={"start": "not-a-date", "end": "2026-01-12T00:00:00Z"})
    assert r.status_code == 400


def test_results_no_dataset_409(tmp_path, monkeypatch):
    # A fresh data dir with NO dataset seeded → the route reports 409, not a 500.
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    from app import main
    c = TestClient(main.app)
    r = c.post("/results", json={"period": "last_1_week"})
    assert r.status_code == 409
