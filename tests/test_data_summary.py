"""Unit tests for the data summary band (specs/02-ux-wireframes.md §2.3a).

Two layers:

  * The sample view-model: app/sample_data._data_summary()'s shape, and that sample_view() carries
    it. These are the shared shape CONTRACT the computed view-model must also satisfy.
  * The computed view-model: app/summary_view.data_summary_from() over synthetic datasets with
    known totals — the real §6.3 load reconstruction + §6.11 battery-free metrics. Covers the base
    totals, the existing-battery net-of variant, omit-don't-zero for the optional groups, the
    negative-load clamp, and the no-grid → None guard.

Neither layer launches a browser or seeds a real dataset (the smoke test covers empty-state
absence); the computed cases build SeriesFrames in-process and wrap them in a LoadedDataset.
"""

from datetime import datetime, timezone

import numpy as np

from app.dataset import LoadedDataset
from app.domain.frames import QUALITY_DTYPE, SeriesFrame
from app.sample_data import _data_summary, sample_view
from app.summary_view import data_summary_from


def test_sample_view_includes_data_summary():
    # sample_view() carries the band unconditionally (main.py drops it in the empty state).
    assert "data_summary" in sample_view()


def test_summary_always_present_groups():
    # Grid and Household are always present (specs §2.3a table): they need no PV, no battery, no
    # price — only the meter registers and the load reconstruction.
    s = _data_summary()
    assert set(s["grid"]) == {"imported", "exported"}
    assert set(s["household"]) >= {"consumption", "self_sufficiency", "net_battery"}


def test_summary_existing_battery_variant():
    # The sample demos the existing-battery variant (confirmed with the user): the battery group
    # is present, and Household is flagged net_of the existing battery so the template labels it.
    s = _data_summary()
    assert s["battery"] is not None
    assert set(s["battery"]) == {"charged", "discharged"}
    assert s["household"]["net_battery"] is True


def test_summary_optional_groups_are_omit_not_zero():
    # The optional groups are separate keys the template guards on, so a no-PV / no-battery /
    # no-price dataset omits them (renders None) rather than showing 0 (specs §2.4). Here the
    # sample has all three, but the keys must exist so the template's `{% if %}` guards resolve.
    s = _data_summary()
    for key in ("solar", "battery", "price"):
        assert key in s


# ── The computed view-model (app/summary_view.data_summary_from) ─────────────────────────────
#
# Synthetic frames on a fixed hourly window so the totals are exact. HOURS intervals of 1 h each,
# starting at 2026-01-01T00:00 UTC; a constant per-interval value v sums to v * HOURS kWh.

HOURS = 24
_WIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_WIN_END = datetime(2026, 1, 2, tzinfo=timezone.utc)  # HOURS hourly intervals


def _energy(name: str, per_interval, n: int = HOURS) -> SeriesFrame:
    """An hourly energy frame of `n` intervals; `per_interval` is a scalar or an array of kWh."""
    idx = (np.arange(n).astype("timedelta64[s]") * 3600 + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    values = np.full(n, float(per_interval)) if np.isscalar(per_interval) else np.asarray(per_interval, dtype=float)
    return SeriesFrame(name, "energy", 3600, idx, values, np.zeros(n, dtype=QUALITY_DTYPE))


def _price(name: str, values, n: int = HOURS) -> SeriesFrame:
    idx = (np.arange(n).astype("timedelta64[s]") * 3600 + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    vals = np.full(n, float(values)) if np.isscalar(values) else np.asarray(values, dtype=float)
    return SeriesFrame(name, "price", 3600, idx, vals, np.zeros(n, dtype=QUALITY_DTYPE))


def _dataset(frames: list[SeriesFrame]) -> LoadedDataset:
    return LoadedDataset(
        id=1,
        source_type="test",
        window=(_WIN_START, _WIN_END),
        fetched_at=_WIN_START,
        frames=frames,
        warnings=[],
        series_sources={f.name: "test" for f in frames},
    )


def test_computed_grid_and_household_totals():
    # import 2 kWh/h, export 0, no PV, no battery → load = import − export = 2 kWh/h.
    #   imported = 2 * 24 = 48 kWh; exported = 0; consumption = load = 48 kWh.
    #   self_sufficiency = 1 − import/load = 1 − 48/48 = 0 → "0%" (all consumption from the grid).
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    s = data_summary_from(ds)
    assert s is not None
    assert s["grid"] == {"imported": "48 kWh", "exported": "0 kWh"}
    # load = 48 − 0 = 48 kWh; self_sufficiency = 1 − 48/48 = 0 → "0%".
    assert s["household"]["consumption"] == "48 kWh"
    assert s["household"]["self_sufficiency"] == "0%"
    assert s["household"]["net_battery"] is False
    assert s["days"] == 1
    assert s["coverage"] == "2026-01-01 → 2026-01-02"
    # No PV, no battery, no price → those groups omitted (None), template drops them.
    assert s["solar"] is None
    assert s["battery"] is None
    assert s["price"] is None


def test_computed_self_sufficiency_with_pv():
    # import 1 kWh/h, export 0, PV 3 kWh/h → load = 1 + 3 = 4 kWh/h; over 24 h: import 24, load 96.
    #   self_sufficiency = 1 − 24/96 = 0.75 → "75%".
    #   self_consumption = 1 − export/pv = 1 − 0/72 = 1.0 → "100%".
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ])
    s = data_summary_from(ds)
    assert s["household"]["self_sufficiency"] == "75%"
    assert s["solar"]["produced"] == "72 kWh"
    assert s["solar"]["self_consumption"] == "100%"
    assert s["solar"]["partial"] is False  # PV spans the whole window here
    assert s["household"]["net_battery"] is False
    assert s["notes"] == []


def test_computed_tariff_registers_fold_together():
    # T1 + T2 import fold into one import total: 1 + 2 = 3 kWh/h → 72 kWh imported.
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_import_t2", 2.0),
        _energy("grid_export_t1", 0.0),
    ])
    s = data_summary_from(ds)
    assert s["grid"]["imported"] == "72 kWh"


def test_computed_existing_battery_variant():
    # An existing battery is mapped → §6.3 strips it: load = imp − exp + batt_dis − batt_chg.
    #   import 5 kWh/h, export 0, charge 2 kWh/h, discharge 1 kWh/h.
    #   load = 5 + 1 − 2 = 4 kWh/h → 96 kWh; battery group present; household net_battery True.
    ds = _dataset([
        _energy("grid_import_t1", 5.0),
        _energy("grid_export_t1", 0.0),
        _energy("battery_charge", 2.0),
        _energy("battery_discharge", 1.0),
    ])
    s = data_summary_from(ds)
    assert s["household"]["consumption"] == "96 kWh"
    assert s["household"]["net_battery"] is True
    assert s["battery"] == {"charged": "48 kWh", "discharged": "24 kWh"}


def test_computed_heavy_clamp_marks_reconstruction_unreliable():
    # export > import with no PV/battery → reconstructed load is negative every interval and is
    # clamped (§6.3). The clamp discards ~all of the load, over the 5% reliability threshold, so
    # consumption + self_sufficiency are SUPPRESSED (None) and a `load_unreliable` note is added —
    # the tell-tale of real PV export the solar sensor did not report (the live-data bug this fixes).
    ds = _dataset([_energy("grid_import_t1", 1.0), _energy("grid_export_t1", 3.0)])
    s = data_summary_from(ds)
    assert s["household"]["consumption"] is None
    assert s["household"]["self_sufficiency"] is None
    assert s["household"]["self_sufficiency_clamped"] is False
    assert any(n["key"] == "load_unreliable" for n in s["notes"])
    # The note carries the exported total so the warning can name it (48 kWh over the window).
    note = next(n for n in s["notes"] if n["key"] == "load_unreliable")
    assert note["export_kwh"] == "72 kWh"  # 3 kWh/h × 24


def test_computed_small_clamp_stays_reliable():
    # A FEW clamped intervals (sensor noise / minor skew) stay under the 5% threshold, so the
    # figures are still shown and no warning fires. One export spike in an otherwise net-import
    # window: 23 h at load 5, 1 h at load −5 (clamped). clamped 5 of ~115 kWh ≈ 4.3% < 5%.
    imp = np.full(HOURS, 5.0)
    exp = np.zeros(HOURS)
    exp[0] = 10.0  # one hour exports 10 while importing 5 → load −5, clamped
    ds = _dataset([_energy("grid_import_t1", imp), _energy("grid_export_t1", exp)])
    s = data_summary_from(ds)
    assert s["household"]["consumption"] is not None
    assert not any(n["key"] == "load_unreliable" for n in s["notes"])


def test_computed_negative_self_sufficiency_is_display_clamped():
    # An existing battery that net-CHARGES over the window (charge 2 > discharge 1 each hour) ends
    # more charged than it started, so grid import (5) exceeds reconstructed load (5+1−2=4). The
    # raw 1 − import/load = 1 − 120/96 = −0.25 is honest but negative; the DISPLAY clamps to 0%
    # and sets self_sufficiency_clamped so the band shows the "evens out over cycles" caveat (§2.3a).
    ds = _dataset([
        _energy("grid_import_t1", 5.0),
        _energy("grid_export_t1", 0.0),
        _energy("battery_charge", 2.0),
        _energy("battery_discharge", 1.0),
    ])
    s = data_summary_from(ds)
    assert s["household"]["consumption"] == "96 kWh"  # 4 kWh/h × 24
    assert s["household"]["self_sufficiency"] == "0%"
    assert s["household"]["self_sufficiency_clamped"] is True


def test_computed_self_sufficiency_not_clamped_when_positive():
    # The clamp flag stays False in the ordinary case (import < load), so the caveat is not shown.
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ])
    s = data_summary_from(ds)
    assert s["household"]["self_sufficiency"] == "75%"
    assert s["household"]["self_sufficiency_clamped"] is False


def test_computed_price_stats_over_own_coverage():
    # Price avg/min/max over the price series, with a negative spot price rendered with U+2212.
    prices = np.array([0.10, 0.20, -0.05] + [0.15] * (HOURS - 3))
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _price("price_spot", prices),
    ])
    s = data_summary_from(ds)
    assert s["price"]["min"] == "−0.050 €/kWh"  # U+2212 minus, 3 dp
    assert s["price"]["max"] == "0.200 €/kWh"
    # avg is the plain mean of the per-interval prices.
    assert s["price"]["avg"] == f"{prices.mean():.3f} €/kWh"


def test_computed_returns_none_without_grid():
    # A dataset with only a price series (no covering energy series) has no simulatable grid, so
    # the band is unsummarisable → None (main.py then omits it, as in the empty state).
    ds = _dataset([_price("price_spot", 0.15)])
    assert data_summary_from(ds) is None


def _energy_subwindow(name: str, per_interval: float, start_hour: int, n: int) -> SeriesFrame:
    """An hourly energy frame starting `start_hour` hours into the base window, `n` intervals long.

    Models a series (solar, battery) mapped PART-WAY through a longer meter history — the real case
    behind the "grid import looks low" bug: panels installed months into a two-year record.
    """
    base = np.datetime64("2026-01-01T00:00:00") + np.timedelta64(start_hour, "h")
    idx = (np.arange(n).astype("timedelta64[s]") * 3600 + base).astype("datetime64[s]")
    return SeriesFrame(name, "energy", 3600, idx, np.full(n, float(per_interval)), np.zeros(n, dtype=QUALITY_DTYPE))


def _dataset_2day(frames: list[SeriesFrame]) -> LoadedDataset:
    # A 48-hour window so a short (24 h) solar series can be strictly inside it.
    return LoadedDataset(
        id=1, source_type="test",
        window=(_WIN_START, datetime(2026, 1, 3, tzinfo=timezone.utc)),
        fetched_at=_WIN_START, frames=frames, warnings=[],
        series_sources={f.name: "test" for f in frames},
    )


def test_computed_short_solar_does_not_clip_grid_totals():
    # THE "grid import looks very low" FIX. The meters span the full 48 h; solar covers only the
    # last 24 h. The window must be driven by the GRID meters, so import totals the full 48 h, not
    # the 24 h solar overlap. (Before the fix, effective_window intersected all series and import
    # was clipped to solar's span.)
    meters_full = [
        _energy("grid_import_t1", 2.0, n=48),   # 48 h × 2 = 96 kWh
        _energy("grid_export_t1", 0.0, n=48),
    ]
    solar_late = _energy_subwindow("solar_production", 1.0, start_hour=24, n=24)  # last 24 h only
    ds = _dataset_2day(meters_full + [solar_late])
    s = data_summary_from(ds)
    # Import spans the full 48 h (96 kWh), NOT clipped to solar's 24 h (which would give 48 kWh).
    assert s["grid"]["imported"] == "96 kWh"
    assert s["days"] == 2
    # Solar reports its OWN 24 h span and flags partial so it is not read against the 48 h window.
    assert s["solar"]["produced"] == "24 kWh"
    assert s["solar"]["partial"] is True
    assert s["solar"]["days"] == 1


def test_computed_near_zero_pv_omits_solar_with_note():
    # THE −1001532% FIX. A solar sensor mapped but reporting almost nothing (below the 1 kWh floor)
    # is treated as empty: the Solar group is omitted (not "Produced 0 kWh", not a divide-by-~0
    # self_consumption) and a `solar_empty` data-quality note is added instead.
    tiny = np.zeros(HOURS)
    tiny[0] = 0.03  # a single stray reading, 0.03 kWh total — well below PV_PRESENT_FLOOR_KWH
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", tiny),
    ])
    s = data_summary_from(ds)
    assert s["solar"] is None
    assert any(n["key"] == "solar_empty" for n in s["notes"])
    # Household still computes (import 48, no real PV → load 48): the empty PV adds ~nothing.
    assert s["household"]["consumption"] == "48 kWh"


def test_computed_self_consumption_over_pv_window_not_full_window():
    # self_consumption compares PV against export over the PV's OWN window, not the whole window.
    # Meters span 48 h and export 1 kWh/h throughout (48 kWh). Solar covers the last 24 h at 4
    # kWh/h (96 kWh). self_consumption = 1 − export_in_pv_window/pv = 1 − 24/96 = 0.75 → "75%".
    # (Using full-window export 48 would wrongly give 1 − 48/96 = 50%.)
    ds = _dataset_2day([
        _energy("grid_import_t1", 3.0, n=48),
        _energy("grid_export_t1", 1.0, n=48),
        _energy_subwindow("solar_production", 4.0, start_hour=24, n=24),
    ])
    s = data_summary_from(ds)
    assert s["solar"]["produced"] == "96 kWh"
    assert s["solar"]["self_consumption"] == "75%"


def test_computed_view_satisfies_sample_shape_contract():
    # The computed view-model must carry the same keys the sample contract asserts, so the template
    # renders either identically. Build the full existing-battery + PV + price variant and re-run
    # the shape checks the sample tests use.
    ds = _dataset([
        _energy("grid_import_t1", 5.0),
        _energy("grid_export_t1", 1.0),
        _energy("solar_production", 3.0),
        _energy("battery_charge", 2.0),
        _energy("battery_discharge", 1.0),
        _price("price_spot", 0.15),
    ])
    s = data_summary_from(ds)
    assert set(s["grid"]) == {"imported", "exported"}
    assert set(s["household"]) >= {"consumption", "self_sufficiency", "net_battery"}
    assert set(s["battery"]) == {"charged", "discharged"}
    assert s["household"]["net_battery"] is True
    for key in ("solar", "battery", "price"):
        assert key in s
