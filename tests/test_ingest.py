"""Unit tests for the pure ingest/normalise domain (specs §6.1, §6.2, §4.3, §4.4).

Arrays in, frames out — no I/O, no data dir. These pin the reset/gap logic and the grid
reconciliation that panel ① reports, against hand-computed expectations.

    uv run pytest tests/test_ingest.py
"""

import numpy as np

from app.domain import ingest, normalize
from app.domain.frames import QualityFlags, SeriesFrame


def _idx(*iso):
    return np.array(list(iso), dtype="datetime64[s]")


# --- resolution inference ------------------------------------------------------------------

def test_infer_hourly_resolution():
    idx = _idx("2026-01-01T00:00:00", "2026-01-01T01:00:00", "2026-01-01T02:00:00")
    assert ingest.infer_resolution_s(idx) == 3600


def test_infer_five_minute_resolution():
    idx = _idx("2026-01-01T00:00:00", "2026-01-01T00:05:00", "2026-01-01T00:10:00")
    assert ingest.infer_resolution_s(idx) == 300


def test_infer_resolution_tolerates_a_gap():
    # Hourly with one missed interval (2h jump) is still hourly — the mode dominates.
    idx = _idx("2026-01-01T00:00:00", "2026-01-01T01:00:00", "2026-01-01T03:00:00",
               "2026-01-01T04:00:00")
    assert ingest.infer_resolution_s(idx) == 3600


def test_infer_resolution_irregular_is_none():
    idx = _idx("2026-01-01T00:00:00", "2026-01-01T00:07:00", "2026-01-01T00:31:00")
    assert ingest.infer_resolution_s(idx) is None


def test_single_row_has_no_resolution():
    assert ingest.infer_resolution_s(_idx("2026-01-01T00:00:00")) is None


# --- cumulative → delta, resets --------------------------------------------------------------

def test_plain_increasing_register():
    idx = _idx("2026-01-01T00:00:00", "2026-01-01T01:00:00", "2026-01-01T02:00:00")
    vals = np.array([100.0, 100.5, 101.4])
    d, flags, warns = ingest.cumulative_to_delta(idx, vals, 3600)
    assert np.allclose(d, [0.5, 0.9])
    assert not warns
    assert int(flags[0]) == 0 and int(flags[1]) == 0


def test_float_noise_decrease_is_zeroed_not_flagged():
    idx = _idx("2026-01-01T00:00:00", "2026-01-01T01:00:00")
    vals = np.array([100.0, 99.995])  # 0.005 drop < RESET_TOLERANCE_KWH
    d, flags, warns = ingest.cumulative_to_delta(idx, vals, 3600)
    assert d[0] == 0.0
    assert int(flags[0]) == 0
    assert not warns


def test_genuine_reset_below_floor():
    idx = _idx("2026-01-01T00:00:00", "2026-01-01T01:00:00")
    vals = np.array([5127.6, 0.3])  # register restarted near zero
    d, flags, warns = ingest.cumulative_to_delta(idx, vals, 3600)
    assert d[0] == 0.3  # energy since reset = new reading
    assert flags[0] & QualityFlags.RESET_CORRECTED
    assert not warns


def test_ambiguous_decrease_flagged_and_warned():
    idx = _idx("2026-01-01T00:00:00", "2026-01-01T01:00:00")
    vals = np.array([100.0, 60.0])  # backwards but not to zero → do not guess
    d, flags, warns = ingest.cumulative_to_delta(idx, vals, 3600)
    assert d[0] == 0.0
    assert flags[0] & QualityFlags.RESET_CORRECTED
    assert len(warns) == 1 and warns[0]["code"] == "AMBIGUOUS_REGISTER_DECREASE"


def test_gap_emits_nan_and_flag():
    # 3h jump between reading 2 and 3 at hourly resolution → the middle interval is a gap.
    idx = _idx("2026-01-01T00:00:00", "2026-01-01T01:00:00", "2026-01-01T04:00:00")
    vals = np.array([100.0, 100.5, 102.0])
    d, flags, warns = ingest.cumulative_to_delta(idx, vals, 3600)
    assert d[0] == 0.5
    assert np.isnan(d[1])  # the gap interval
    assert flags[1] & QualityFlags.GAP_FILLED


# --- frame assembly --------------------------------------------------------------------------

def test_energy_frame_shape_and_index():
    rows = [
        ingest.EnergyRow(start_ms=0, sum=100.0),
        ingest.EnergyRow(start_ms=3_600_000, sum=100.5),
        ingest.EnergyRow(start_ms=7_200_000, sum=101.4),
    ]
    frame, warns = ingest.energy_frame("grid_import_t1", rows)
    assert frame.kind == "energy"
    assert frame.resolution_s == 3600
    # 3 readings → 2 interval deltas, indexed at the first two starts.
    assert len(frame.index) == 2 and len(frame.values) == 2
    assert np.allclose(frame.values, [0.5, 0.9])


def test_energy_frame_sorts_unordered_rows():
    rows = [
        ingest.EnergyRow(start_ms=3_600_000, sum=100.5),
        ingest.EnergyRow(start_ms=0, sum=100.0),
    ]
    frame, _ = ingest.energy_frame("grid_import_t1", rows)
    assert np.allclose(frame.values, [0.5])


def test_price_frame_carries_the_mean_and_nothing_else():
    """A price frame is mean-only — no intra-interval bracket rides along.

    The §6.16 bracket used to be taken from an HA `measurement` statistic's own min/max and
    carried on the frame; it is now derived from the 15-minute values at grid reconciliation
    (`simframe._resample_price_stats`), so `PriceRow` and `SeriesFrame` have no min/max at all.
    """
    rows = [
        ingest.PriceRow(start_ms=0, mean=0.2955),
        ingest.PriceRow(start_ms=3_600_000, mean=0.2899),
    ]
    frame = ingest.price_frame("price_spot", rows)
    assert frame.kind == "price"
    assert np.allclose(frame.values, [0.2955, 0.2899])
    assert not hasattr(frame, "value_min") and not hasattr(frame, "value_max")
    assert not hasattr(rows[0], "min") and not hasattr(rows[0], "max")


# --- grid selection / reconciliation (specs §6.2) --------------------------------------------

def _energy_frame(name, resolution_s, n=48):
    idx = np.arange(n).astype("timedelta64[s]") * resolution_s + np.datetime64("2026-01-01T00:00:00")
    return SeriesFrame(name, "energy", resolution_s, idx.astype("datetime64[s]"),
                       np.ones(n), np.zeros(n, dtype=np.uint16))


def _price_frame(name, resolution_s, n=192):
    idx = np.arange(n).astype("timedelta64[s]") * resolution_s + np.datetime64("2026-01-01T00:00:00")
    return SeriesFrame(name, "price", resolution_s, idx.astype("datetime64[s]"),
                       np.full(n, 0.3), np.zeros(n, dtype=np.uint16))


def test_grid_is_coarsest_energy_resolution():
    from datetime import datetime, timezone
    win = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    frames = [_energy_frame("grid_import_t1", 3600), _energy_frame("solar_production", 300, n=576)]
    assert normalize.choose_grid(frames, win) == 3600  # hourly wins over 5-min


def test_price_finer_than_grid_is_averaged_and_lossy():
    from datetime import datetime, timezone
    win = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    frames = [_energy_frame("grid_import_t1", 3600), _price_frame("price_spot", 900)]
    report = normalize.grid_report(frames, win)
    assert report["grid_s"] == 3600
    price_entry = next(s for s in report["series"] if s["name"] == "price_spot")
    assert price_entry["reconciliation"] == "averaged"
    assert price_entry["warn"] is True
    assert report["price_granularity_lost"]["lost"] is True
    assert report["price_granularity_lost"]["native_resolution_s"] == 900


def test_price_coarser_than_grid_is_held_not_lossy():
    from datetime import datetime, timezone
    win = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    frames = [_energy_frame("grid_import_t1", 3600), _price_frame("price_spot", 7200, n=6)]
    report = normalize.grid_report(frames, win)
    price_entry = next(s for s in report["series"] if s["name"] == "price_spot")
    assert price_entry["reconciliation"] == "held"
    assert price_entry["warn"] is False
    assert report["price_granularity_lost"]["lost"] is False
