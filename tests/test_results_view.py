"""Unit tests for the panel-③ results view-model and window resolver (specs §2.4, §7.4).

Two units under test, both from app/results_view:

  * results_from(dataset, window) — the ENERGY SAVINGS view-model over a window, under this
    increment's zero-battery assumption (charge ≡ discharge ≡ 0). Covers the zero-battery invariant
    (saved = 0, baseline self-sufficiency == battery), the no-PV omit discipline (self-consumption
    row absent), and the no-grid → None guard.
  * resolve_window(dataset, *, period/start/end) — preset anchoring to the END of data coverage
    (§7.4) and clamping to coverage.

Synthetic SeriesFrames are built in-process (no browser, no real dataset), reusing the frame/dataset
helpers from tests/test_data_summary.py so the two suites share one construction of a LoadedDataset.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.results_view import PERIOD_DAYS, resolve_window, results_from
from tests.test_data_summary import (
    HOURS,
    _WIN_END,
    _WIN_START,
    _dataset,
    _energy,
)


# ── results_from ─────────────────────────────────────────────────────────────────────────────


def test_results_zero_battery_invariant():
    # import 2 kWh/h, export 0, no PV, no battery over 24 h → import 48 kWh, load 48 kWh.
    # Zero-battery: saved = 0, "with battery" import == baseline import, avoided = 0, and every
    # battery-moved figure is 0.
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r is not None
    # GRID IMPORT SAVED tile is zero.
    saved = next(k for k in r["kpis"] if k["title"] == "GRID IMPORT SAVED")
    assert saved["value"] == "0"
    assert saved["unit"] == "kWh"
    # SELF-SUFFICIENCY baseline == battery: "X% → X%" with equal halves, +0 pp delta.
    ss = next(k for k in r["kpis"] if k["title"] == "SELF-SUFFICIENCY")
    left, right = ss["value"].split(" → ")
    assert left == right
    assert ss["delta"] == "+0 pp"
    # Breakdown: import no-battery == import with-battery; avoided is 0; battery-moved rows are 0.
    by_label = {row["label"]: row["value"] for row in r["energy_breakdown"]}
    assert by_label["Grid import, no battery"] == by_label["Grid import, with battery"] == "48 kWh"
    assert by_label["Grid import avoided"] == "0 kWh"
    assert by_label["Charged into the battery"] == "0 kWh"
    assert by_label["Discharged from the battery"] == "0 kWh"
    assert by_label["Conversion losses"] == "0 kWh"
    assert by_label["Standby consumption"] == "0 kWh"
    # No benchmark key this increment (§6.12 DP not built).
    assert "benchmark" not in r


def test_results_self_sufficiency_matches_measured():
    # import 1 kWh/h, PV 3 kWh/h, export 0 → load = 1 + 3 = 4 kWh/h; self-sufficiency = 1 − 24/96
    # = 0.75 → "75%". Both halves of the KPI show that (baseline == battery).
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ])
    r = results_from(ds, (_WIN_START, _WIN_END))
    ss = next(k for k in r["kpis"] if k["title"] == "SELF-SUFFICIENCY")
    assert ss["value"] == "75% → 75%"


def test_results_no_pv_omits_self_consumption_row():
    # No PV → the self-consumption row (denominator is PV) is omitted (§2.4 omit-don't-zero).
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    labels = [row["label"] for row in r["secondary"]]
    assert "Self-consumption ratio" not in labels
    # Grid export IS shown (measured figure, equal on both sides).
    assert "Grid export" in labels
    # The "intervals battery full/empty" row is omitted this increment (no battery).
    assert "Intervals battery was full / empty" not in labels


def test_results_pv_shows_self_consumption_equal_halves():
    # With usable PV the self-consumption row appears, baseline == battery: "X% → X%".
    # PV 3 kWh/h, export 0 → self-consumption = 1 − 0/72 = 100%.
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ])
    r = results_from(ds, (_WIN_START, _WIN_END))
    sc = next(row for row in r["secondary"] if row["label"] == "Self-consumption ratio")
    assert sc["value"] == "100% → 100%"


def test_results_always_has_battery_not_configured_caveat():
    # The honest headline for this increment is ALWAYS present: a caveat that the battery is not
    # configured so savings are zero.
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert any("No battery is configured" in c for c in r["caveats"])


def test_results_period_line_and_chart_are_real():
    # The coverage line reflects the effective window, hourly grid, and interval count; the chart is
    # a real monthly import series (one bucket here — a single January).
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r["period"] == "2026-01-01 → 2026-01-02 · simulated hourly · 24 intervals"
    assert r["chart"]["months"] == ["Jan"]
    assert r["chart"]["values"] == [48]  # 2 kWh/h × 24 h


def test_results_short_window_disables_annualisation():
    # A 24 h window is well under min_annualisation_days (90), so the short-window flag + message
    # are set for the §2.4 info box.
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    r = results_from(ds, (_WIN_START, _WIN_END))
    assert r["annualisation_disabled"] is True
    assert "disabled" in r["annualisation_message"]


def test_results_returns_none_without_grid():
    # No covering grid meter → reconcile_grid returns None → results_from returns None (caller falls
    # back to the empty state).
    from tests.test_data_summary import _price
    ds = _dataset([_price("price_spot", 0.15)])
    assert results_from(ds, (_WIN_START, _WIN_END)) is None


# ── resolve_window ───────────────────────────────────────────────────────────────────────────
#
# A wider synthetic dataset so presets have room: 400 hourly intervals is too few for day-presets,
# so build a multi-day hourly meter and drive coverage from it.


_COV_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _long_dataset(days: int):
    """An hourly grid dataset whose coverage spans exactly `days` days from _COV_START.

    Coverage end = last interval start + 1 h = _COV_START + `days` days (n = days*24 hourly
    intervals). The dataset `window` is deliberately wider (a full non-leap year) so resolve_window
    must derive the real coverage from the frames, not from the advertised window.
    """
    from app.dataset import LoadedDataset
    from app.domain.frames import QUALITY_DTYPE, SeriesFrame

    n = days * 24
    idx = (np.arange(n).astype("timedelta64[s]") * 3600
           + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    imp = SeriesFrame("grid_import_t1", "energy", 3600, idx, np.full(n, 1.0),
                      np.zeros(n, dtype=QUALITY_DTYPE))
    exp = SeriesFrame("grid_export_t1", "energy", 3600, idx, np.zeros(n),
                      np.zeros(n, dtype=QUALITY_DTYPE))
    return LoadedDataset(
        id=1, source_type="test",
        window=(_COV_START, datetime(2027, 1, 1, tzinfo=timezone.utc)),
        fetched_at=_COV_START,
        frames=[imp, exp], warnings=[],
        series_sources={"grid_import_t1": "test", "grid_export_t1": "test"},
    )


def test_resolve_window_preset_anchors_to_coverage_end():
    # Coverage spans 200 days from 2026-01-01. last_30_days ends at the coverage END (last data
    # timestamp), NOT now(), and starts 30 days before it.
    ds = _long_dataset(200)
    cov_end = _COV_START + timedelta(days=200)
    start, end = resolve_window(ds, period="last_30_days")
    assert end == cov_end
    assert (end - start).days == 30


def test_resolve_window_preset_clamps_to_coverage_start():
    # Coverage is only 40 days; last_1_year (365) would reach before the data begins, so the start
    # clamps to coverage start — never pad with zeros (§7.4).
    ds = _long_dataset(40)
    cov_end = _COV_START + timedelta(days=40)
    start, end = resolve_window(ds, period="last_1_year")
    assert start == _COV_START
    assert end == cov_end


def test_resolve_window_default_is_last_1_year():
    # No args → the DEFAULT_PERIOD (last_1_year) preset. With 200 days of coverage it clamps to the
    # full coverage (365 > 200).
    ds = _long_dataset(200)
    start_default, end_default = resolve_window(ds)
    start_year, end_year = resolve_window(ds, period="last_1_year")
    assert (start_default, end_default) == (start_year, end_year)


def test_resolve_window_explicit_range_clamps():
    # An explicit range partly outside coverage clamps both ends into coverage.
    ds = _long_dataset(100)
    cov_end = _COV_START + timedelta(days=100)
    # Ask for a range starting before coverage and ending after it → clamps to full coverage.
    start, end = resolve_window(
        ds,
        start=_COV_START - timedelta(days=10),
        end=cov_end + timedelta(days=10),
    )
    assert start == _COV_START
    assert end == cov_end


def test_resolve_window_rejects_empty_range():
    ds = _long_dataset(100)
    t = datetime(2026, 2, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        resolve_window(ds, start=t, end=t)  # end <= start


def test_resolve_window_rejects_unknown_preset():
    ds = _long_dataset(100)
    with pytest.raises(ValueError):
        resolve_window(ds, period="last_decade")


def test_resolve_window_rejects_period_and_range_together():
    ds = _long_dataset(100)
    with pytest.raises(ValueError):
        resolve_window(ds, period="last_30_days", start=datetime(2026, 1, 5, tzinfo=timezone.utc))


def test_resolve_window_all_presets_known():
    # Every preset the selector offers resolves without error over ample coverage.
    ds = _long_dataset(400)
    for name in PERIOD_DAYS:
        start, end = resolve_window(ds, period=name)
        assert end > start
