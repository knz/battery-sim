"""Unit tests for the §4.4 SimulationFrame builder (app/domain/simframe.py).

Two spec fixtures from the §6.14 validation harness plus the price-reconciliation edge cases:

  * Fixture 21 (mixed native resolutions) — hourly energy + a 15-minute price. Pins BOTH that the
    grid stays hourly (a selector letting the price vote would pick 900 s and then have to upsample
    energy, which §6.2 forbids) and that the hourly `spot` is the arithmetic MEAN of each hour's
    four quarter-hourly prices. The per-quarter prices are deliberately ASYMMETRIC and the energy
    deliberately varies WITHIN the hour, so that sum, first-value, last-value, median and an
    energy-weighted mean are five distinct numbers and each wrong implementation fails visibly —
    §6.2's "energy-unweighted" is an explicit spec choice, so the test has to be able to see it
    violated.
  * Fixture 7 (DST) — a window spanning both the March and October transitions yields 8,760 ± 1
    hourly intervals with no duplicated or dropped index entries. The pipeline holds UTC throughout
    (§4.4), so what this really asserts is that the UTC axis is uniform and untouched by local-time
    transitions; it is written to assert exactly that, not a local-time property the code does not
    claim.
  * Edge cases — price coverage shorter than the meter window (NaN, not 0), a price coarser than
    the grid (forward-filled, and BOUNDED to the last point's own interval), an irregular price
    series (unbounded hold, but the extrapolated intervals counted), no price slot at all, `pv`
    all-zero rather than None, and agreement with reconcile_grid on the energy arrays.
  * The intra-interval price bracket — `spot_min` / `spot_max`, the cheapest and dearest native
    price point that landed in each grid interval. Pins that it really is the endpoints of what the
    mean collapsed (not the mean again), that it collapses to a point for a single-point or held
    interval, that it is NaN exactly where `spot` is, and that NaN native values are excluded from
    it rather than propagating through the min/max reduction.

Frames are built in-process (no browser, no real dataset), reusing the helpers in
tests/test_data_summary.py where the window matches, and building longer/finer frames locally where
it does not.
"""

from datetime import datetime, timezone

import numpy as np

from app.dataset import LoadedDataset
from app.domain.frames import QUALITY_DTYPE, SeriesFrame
from app.domain.normalize import price_granularity_lost
from app.domain.reconcile import reconcile_grid
from app.domain.simframe import CLOSURE_TOL, simulation_frame
from tests.test_data_summary import (
    HOURS,
    _WIN_END,
    _WIN_START,
    _dataset,
    _energy,
)

_EPOCH = np.datetime64("2026-01-01T00:00:00")


def _series(name: str, kind: str, resolution_s, index, values) -> SeriesFrame:
    """A SeriesFrame from an explicit index/values pair (for the non-hourly cases)."""
    idx = np.asarray(index, dtype="datetime64[s]")
    vals = np.asarray(values, dtype=float)
    return SeriesFrame(name, kind, resolution_s, idx, vals, np.zeros(len(idx), dtype=QUALITY_DTYPE))


def _regular_index(start: np.datetime64, step_s: int, n: int) -> np.ndarray:
    return (np.asarray(start, dtype="datetime64[s]")
            + (np.arange(n, dtype=np.int64) * step_s).astype("timedelta64[s]"))


# ── Spec fixture 21: mixed native resolutions ────────────────────────────────────────────────


# Four prices within each hour, chosen ASYMMETRIC on purpose. The earlier symmetric set
# [0.10, 0.20, 0.30, 0.40] separated mean from sum, first and last but NOT from the median: for a
# symmetric set median == mean, so a median implementation slipped through. Here:
#     mean   0.20   ← the §6.2 convention, and what the test pins
#     median 0.10   ← distinct now
#     sum    0.80
#     first  0.10   (equal to the median, but a run of hours with different patterns still
#                    separates them; the median is the value this asymmetry is aimed at)
#     last   0.50
_QUARTER_PRICES = [0.10, 0.10, 0.10, 0.50]
_QUARTER_MEAN = sum(_QUARTER_PRICES) / 4  # 0.20
_QUARTER_MEDIAN = 0.10  # named so the contrast with the mean is visible at the assertion

# Intra-hour ENERGY for fixture 21, in kWh per quarter, deliberately NON-uniform. §6.2 specifies
# the price mean as energy-UNWEIGHTED, and with uniform energy an energy-weighted implementation is
# numerically identical to the unweighted one — so the old fixture could not detect that violation
# at all. With these weights the two conventions diverge:
#     unweighted mean  = (0.10 + 0.10 + 0.10 + 0.50) / 4                  = 0.20   ← pinned
#     energy-weighted  = (0.10·3 + 0.10·1 + 0.10·1 + 0.50·1) / (3+1+1+1)  ≈ 0.1667
# Both numbers are named here so a future reader sees which convention this fixture fixes and that
# the other one was considered rather than overlooked.
_QUARTER_ENERGY = [3.0, 1.0, 1.0, 1.0]
_QUARTER_ENERGY_WEIGHTED = sum(p * e for p, e in zip(_QUARTER_PRICES, _QUARTER_ENERGY)) / sum(
    _QUARTER_ENERGY
)  # ≈ 0.16667


def _quarter_hourly_price(n_hours: int = HOURS) -> SeriesFrame:
    """A 15-minute price over `n_hours` hours, cycling _QUARTER_PRICES within each hour."""
    n = n_hours * 4
    idx = _regular_index(_EPOCH, 900, n)
    values = np.tile(np.asarray(_QUARTER_PRICES), n_hours)
    return _series("price_spot", "price", 900, idx, values)


def _quarter_hourly_pv(n_hours: int = HOURS) -> SeriesFrame:
    """A 15-minute PV series cycling _QUARTER_ENERGY within each hour.

    Present only so the fixture has energy that VARIES within the hour. It does not vote on the
    grid in a way that changes it: choose_grid takes the MAX resolution over covering energy
    series, and the hourly grid meters are coarser, so the grid stays 3600 s (asserted below).
    """
    n = n_hours * 4
    idx = _regular_index(_EPOCH, 900, n)
    return _series("solar_production", "energy", 900, idx, np.tile(np.asarray(_QUARTER_ENERGY), n_hours))


def test_fixture21_grid_stays_hourly_and_spot_is_the_quarter_hour_mean():
    # Hourly grid meters + a 15-minute price over the same window (specs §6.14 fixture 21), plus a
    # 15-minute PV series so the energy within each hour is non-uniform — see _QUARTER_ENERGY.
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _quarter_hourly_pv(),
        _quarter_hourly_price(),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None

    # THE LOAD-BEARING ASSERTION: the grid is hourly. Only ENERGY series vote on the grid (§6.2),
    # so the finer price must not drag it down to 900 s — that would force upsampling the energy,
    # which §6.2 forbids outright.
    assert sf.grid_s == 3600
    assert sf.dt_hours == 1.0
    assert sf.intervals == HOURS

    # The intra-hour energy really is non-uniform (3.0 + 1.0 + 1.0 + 1.0 = 6.0 kWh per hour), which
    # is what makes the energy-weighted alternative below numerically different.
    assert np.allclose(sf.pv, sum(_QUARTER_ENERGY))

    # Each hourly spot is the ARITHMETIC, ENERGY-UNWEIGHTED MEAN of that hour's four quarter-hourly
    # prices (§6.2). Every plausible wrong implementation lands on a different number:
    #     sum 0.80, first 0.10, last 0.50, median 0.10, energy-weighted ≈ 0.1667 — vs 0.20 here.
    assert np.allclose(sf.spot, _QUARTER_MEAN)
    assert abs(_QUARTER_MEAN - _QUARTER_MEDIAN) > CLOSURE_TOL  # the asymmetry is real
    assert abs(_QUARTER_MEAN - _QUARTER_ENERGY_WEIGHTED) > CLOSURE_TOL  # so is the weighting gap
    assert not np.allclose(sf.spot, _QUARTER_ENERGY_WEIGHTED)  # §6.2's choice, pinned
    assert sf.spot_complete is True
    assert sf.spot_missing_intervals == 0
    assert sf.spot_extrapolated_intervals == 0


def test_fixture21_reports_price_granularity_lost():
    # The other half of fixture 21: averaging 900 s prices onto a 3600 s grid loses granularity the
    # simulator cannot recover, and §6.2 requires that to be reported with the native spacing.
    frames = [
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _quarter_hourly_price(),
    ]
    lost = price_granularity_lost(frames, 3600)
    assert lost == {"lost": True, "native_resolution_s": 900}


# ── Spec fixture 7: DST ──────────────────────────────────────────────────────────────────────


def test_fixture7_dst_year_has_8760_uniform_hourly_intervals():
    # A window spanning BOTH the March and the October Europe/Amsterdam transitions (specs §6.14
    # fixture 7). The pipeline holds UTC throughout (§4.4): the index is a UTC axis, so the honest
    # claim is that it is UNIFORM and unperturbed by the local-time transitions — not that some
    # local day has 23 or 25 hours, which this code does not model and does not claim.
    n = 8760
    start = np.datetime64("2026-01-01T00:00:00")
    idx = _regular_index(start, 3600, n)
    win = (
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    ds = LoadedDataset(
        id=1,
        source_type="test",
        window=win,
        fetched_at=win[0],
        frames=[
            _series("grid_import_t1", "energy", 3600, idx, np.full(n, 1.0)),
            _series("grid_export_t1", "energy", 3600, idx, np.zeros(n)),
            _series("price_spot", "price", 3600, idx, np.full(n, 0.20)),
        ],
        warnings=[],
        series_sources={},
    )
    sf = simulation_frame(ds, win)
    assert sf is not None

    # 8,760 ± 1 hourly intervals (2026 is not a leap year; the ±1 is the spec's own slack).
    assert sf.grid_s == 3600
    assert abs(sf.intervals - 8760) <= 1
    # No duplicated and no dropped entries: strictly increasing, and every step exactly one hour.
    steps = np.diff(sf.index.astype("datetime64[s]").astype(np.int64))
    assert len(np.unique(sf.index)) == sf.intervals  # no duplicates
    assert np.all(steps == 3600)  # uniform, so nothing dropped either
    # Every array is the same length as the index — the invariant the simulation core relies on.
    for arr in (sf.pv, sf.load, sf.spot, sf.import_obs, sf.export_obs):
        assert len(arr) == sf.intervals


# ── Price coverage, resolution and absence ───────────────────────────────────────────────────


def test_price_shorter_than_the_window_leaves_nan_not_zero():
    # Prices cover only the first 12 of 24 hours. The uncovered intervals must be NaN, never 0:
    # §4.4 is explicit that an all-zero spot reads as "prices are zero everywhere" and makes every
    # band comparison take a definite, wrong branch. The frame must also REPORT the incompleteness.
    covered = 12
    idx = _regular_index(_EPOCH, 3600, covered)
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _series("price_spot", "price", 3600, idx, np.full(covered, 0.30)),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert np.allclose(sf.spot[:covered], 0.30)
    # The uncovered TAIL is NaN, not 0 and not the last price held forever. This price is at the
    # grid resolution, so it takes the bucket-mean path: a bucket that received no price point has
    # no price, full stop. (The forward-fill path — coarser or irregular price — does hold the last
    # value past the end, because a step function is all it has; that is asserted separately.)
    assert np.isnan(sf.spot[covered:]).all()
    assert sf.spot_complete is False
    assert sf.spot_missing_intervals == HOURS - covered

    # The same series shifted so it covers only the SECOND half: the leading intervals have no
    # price in force at all and must be NaN too.
    idx_late = _regular_index(np.datetime64("2026-01-01T12:00:00"), 3600, covered)
    ds_late = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _series("price_spot", "price", 3600, idx_late, np.full(covered, 0.30)),
    ])
    sf_late = simulation_frame(ds_late, (_WIN_START, _WIN_END))
    assert sf_late is not None
    assert np.isnan(sf_late.spot[:covered]).all()
    assert not np.isnan(sf_late.spot[covered:]).any()
    assert sf_late.spot_complete is False
    assert sf_late.spot_missing_intervals == covered


def test_price_coarser_than_the_grid_is_forward_filled():
    # Hourly price, 15-minute meters → a 900 s grid with a 3600 s price. Reachable because §6.2
    # lets only ENERGY series vote on the grid. The price in force at each interval's START applies
    # (§4.4 "EUR/kWh valid from" — a step function), i.e. reconciliation `held`, which is lossless.
    n_q = HOURS * 4
    q_idx = _regular_index(_EPOCH, 900, n_q)
    hourly_prices = np.arange(HOURS, dtype=float) / 100  # 0.00, 0.01, … distinct per hour
    ds = _dataset([
        _series("grid_import_t1", "energy", 900, q_idx, np.full(n_q, 0.5)),
        _series("grid_export_t1", "energy", 900, q_idx, np.zeros(n_q)),
        _series("price_spot", "price", 3600, _regular_index(_EPOCH, 3600, HOURS), hourly_prices),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert sf.grid_s == 900
    assert sf.dt_hours == 0.25
    assert sf.intervals == n_q
    # Each hour's price repeats across its four quarters.
    assert np.allclose(sf.spot, np.repeat(hourly_prices, 4))
    assert sf.spot_complete is True


def test_forward_fill_is_bounded_to_the_last_price_points_own_interval():
    # The coarse-REGULAR forward-fill stops one `resolution_s` past the last price point. A price
    # point declared at 3600 s spacing states the price for its own hour and states nothing about
    # the hour after; holding it indefinitely would let one point drive the whole dispatch signal
    # while still reporting as fully priced. This is a policy choice and it replaces an earlier one
    # (hold forever) — the earlier expectation was the thing that was wrong, not the case.
    n_q = HOURS * 4
    q_idx = _regular_index(_EPOCH, 900, n_q)
    ds = _dataset([
        _series("grid_import_t1", "energy", 900, q_idx, np.full(n_q, 0.5)),
        _series("grid_export_t1", "energy", 900, q_idx, np.zeros(n_q)),
        # Hourly price covering only the first 6 hours of the 24-hour, 15-minute grid. The last
        # point is at 05:00 and covers [05:00, 06:00).
        _series("price_spot", "price", 3600, _regular_index(_EPOCH, 3600, 6), np.full(6, 0.15)),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert sf.grid_s == 900

    # Quarters 0–23 are hours 0–5: priced, held within each hour's own interval. The 24th quarter
    # is 06:00, one hour past the last point's start, so the hold ends exactly there.
    covered_q = 6 * 4
    assert np.allclose(sf.spot[:covered_q], 0.15)
    assert np.isnan(sf.spot[covered_q:]).all()

    # And the frame says so, rather than reporting a fully-priced window built from one stale value.
    assert sf.spot_complete is False
    assert sf.spot_missing_intervals == n_q - covered_q
    # Bounded, therefore nothing was extrapolated: the tail is missing, not invented.
    assert sf.spot_extrapolated_intervals == 0


def test_irregular_price_series_is_held_from_each_point():
    # An irregular price (`resolution_s is None`, §4.4 / open question §8.20) has no native spacing
    # to bucket by, so bucket-averaging is undefined. Resolved by forward-filling: a price value is
    # "valid from" its timestamp regardless of how regularly the points arrive, and the rule reduces
    # to the regular `held` case when spacing happens to be uniform. Asserted here so the resolution
    # is pinned rather than left to drift.
    idx = np.asarray(
        [
            np.datetime64("2026-01-01T00:00:00"),
            np.datetime64("2026-01-01T05:30:00"),  # deliberately off-grid
            np.datetime64("2026-01-01T18:00:00"),
        ],
        dtype="datetime64[s]",
    )
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _series("price_spot", "price", None, idx, [0.10, 0.20, 0.30]),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    # Hours 0–5 hold 0.10 (the 05:30 point only takes effect from hour 6's start), 6–17 hold 0.20,
    # 18–23 hold 0.30.
    expected = np.concatenate([np.full(6, 0.10), np.full(12, 0.20), np.full(6, 0.30)])
    assert np.allclose(sf.spot, expected)

    # The irregular path is the ONE place where the hold stays unbounded — there is no declared
    # spacing to bound it by — so it is REPORTED instead. The 18:00 point covers hour 18 itself
    # (the interval starting exactly at a price timestamp takes that price, observed); hours 19–23
    # are held past it with nothing supporting a length, so they count as extrapolated.
    assert sf.spot_missing_intervals == 0
    assert sf.spot_extrapolated_intervals == 5
    # …and extrapolation alone makes the frame incomplete: `spot_complete` means every interval
    # OBSERVED, so a run precondition gating on it cannot be fooled by an extrapolated tail.
    assert sf.spot_complete is False


def test_no_price_slot_yields_an_all_nan_spot_rather_than_crashing():
    # `price_spot` is a REQUIRED slot (series_vocab), but slot-first sources fill slots one at a
    # time, so a dataset can legitimately exist before the price arrives. The builder must not
    # crash: it returns a frame with an all-NaN spot and says so, leaving the "cannot dispatch
    # without prices" gate to the run precondition rather than to frame construction.
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert np.isnan(sf.spot).all()
    assert sf.spot_complete is False
    assert sf.spot_missing_intervals == HOURS


def test_nan_price_points_are_skipped_not_averaged_in():
    # A gap inside one hour: three good quarters and one NaN. The hour averages the three good ones
    # rather than coming out NaN — an ingest gap in one quarter should not blank the whole hour.
    price = _quarter_hourly_price()
    price.values = price.values.copy()
    price.values[0] = np.nan  # first quarter of hour 0
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        price,
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert abs(sf.spot[0] - sum(_QUARTER_PRICES[1:]) / 3) < CLOSURE_TOL
    assert np.allclose(sf.spot[1:], _QUARTER_MEAN)


# ── The intra-interval price bracket (spot_min / spot_max) ───────────────────────────────────


def test_bracket_is_the_cheapest_and_dearest_quarter_in_each_hour():
    # The reason the bracket exists: since 2025-10-01 the NL market settles every 15 minutes while
    # household data is hourly, so four quarter prices collapse into one mean and the collapse is
    # lossy. spot_min/spot_max are the endpoints of what was collapsed — 0.10 and 0.50 here, around
    # a mean of 0.20. Pinned against the mean so a min/max that silently returned the mean (or each
    # other) fails.
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _quarter_hourly_price(),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert np.allclose(sf.spot_min, min(_QUARTER_PRICES))
    assert np.allclose(sf.spot_max, max(_QUARTER_PRICES))
    assert np.allclose(sf.spot, _QUARTER_MEAN)
    # The ordering the later width computation relies on, and the spread is genuinely non-zero.
    assert np.all(sf.spot_min <= sf.spot) and np.all(sf.spot <= sf.spot_max)
    assert float(sf.spot_max[0] - sf.spot_min[0]) > CLOSURE_TOL


def test_bracket_collapses_to_the_mean_for_a_single_point_interval():
    # An hourly price on an hourly grid: one point per bucket, so there is nothing to spread over
    # and the bracket is a POINT. This is the natural collapse, not a special case — it is also what
    # every pre-2025-10-01 hour of the ENTSO-E series looks like, so it has to come out at zero
    # width rather than at some invented margin.
    hourly = np.arange(HOURS, dtype=float) / 100  # distinct per hour, so a stuck value shows up
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _series("price_spot", "price", 3600, _regular_index(_EPOCH, 3600, HOURS), hourly),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert np.allclose(sf.spot, hourly)
    assert np.array_equal(sf.spot_min, sf.spot)
    assert np.array_equal(sf.spot_max, sf.spot)


def test_bracket_is_nan_exactly_where_the_price_is_absent():
    # §4.4: absence is NaN, never 0 — and that applies to all three arrays alike. A zero-filled
    # bracket would read as "the price was somewhere between 0 and 0", which is a definite and wrong
    # statement rather than a missing one. Covers both the partially-covered window and the
    # no-price-slot-at-all case, since the latter takes a different branch in _spot_on_grid.
    covered = 12
    idx = _regular_index(_EPOCH, 3600, covered)
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _series("price_spot", "price", 3600, idx, np.full(covered, 0.30)),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert np.allclose(sf.spot_min[:covered], 0.30)
    assert np.allclose(sf.spot_max[:covered], 0.30)
    # NaN exactly where spot is NaN — no ±inf leaking out of the min/max accumulators either.
    assert np.array_equal(np.isnan(sf.spot_min), np.isnan(sf.spot))
    assert np.array_equal(np.isnan(sf.spot_max), np.isnan(sf.spot))
    assert np.isfinite(sf.spot_min[:covered]).all()

    no_price = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    sf_none = simulation_frame(no_price, (_WIN_START, _WIN_END))
    assert sf_none is not None
    assert np.isnan(sf_none.spot_min).all()
    assert np.isnan(sf_none.spot_max).all()


def test_nan_price_points_are_excluded_from_the_bracket_too():
    # A NaN quarter is a gap, not a price, so it must not become the bucket's min or max — and it
    # must not poison them either (np.minimum propagates NaN, which is why the mask does the work).
    # The gap here is on the DEAREST quarter, so a leaked NaN and a correct exclusion give visibly
    # different maxima: 0.10 rather than 0.50 for hour 0.
    price = _quarter_hourly_price()
    price.values = price.values.copy()
    price.values[3] = np.nan  # last quarter of hour 0 — the 0.50 one
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        price,
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert abs(float(sf.spot_min[0]) - 0.10) < CLOSURE_TOL
    assert abs(float(sf.spot_max[0]) - 0.10) < CLOSURE_TOL  # the three survivors are all 0.10
    # Every other hour keeps its full four quarters and its full spread.
    assert np.allclose(sf.spot_min[1:], min(_QUARTER_PRICES))
    assert np.allclose(sf.spot_max[1:], max(_QUARTER_PRICES))


def test_held_price_has_no_spread_so_the_bracket_is_a_point():
    # Hourly price against 15-minute meters → the forward-fill path. A held value carries no
    # sub-interval information: nothing was collapsed, so nothing was lost, and inventing a spread
    # there would report an uncertainty the data does not support. min == max == spot.
    n_q = HOURS * 4
    q_idx = _regular_index(_EPOCH, 900, n_q)
    hourly_prices = np.arange(HOURS, dtype=float) / 100
    ds = _dataset([
        _series("grid_import_t1", "energy", 900, q_idx, np.full(n_q, 0.5)),
        _series("grid_export_t1", "energy", 900, q_idx, np.zeros(n_q)),
        _series("price_spot", "price", 3600, _regular_index(_EPOCH, 3600, HOURS), hourly_prices),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert sf.grid_s == 900
    assert np.allclose(sf.spot, np.repeat(hourly_prices, 4))
    assert np.array_equal(sf.spot_min, sf.spot)
    assert np.array_equal(sf.spot_max, sf.spot)
    # And the arrays are independent objects, so a later step mutating one cannot alter `spot`.
    assert sf.spot_min is not sf.spot and sf.spot_max is not sf.spot


def test_bracket_brackets_the_mean_even_when_rounding_would_not():
    # `spot_min <= spot <= spot_max` is documented as an invariant, and the width computation is
    # entitled to rely on it rather than clamp defensively at every use. It does NOT come for free.
    #
    # The trigger is unintuitive enough to be worth stating: THREE IDENTICAL PRICES. `x + x + x`
    # rounds to a value whose quotient by 3 is one ULP ABOVE x, so the mean exceeds the max of its
    # own inputs. Divisors that are powers of two are exact, which is why a full four-quarter hour
    # is safe and a three-quarter one is not — and a three-point bucket is the ordinary shape of an
    # hour with one gap quarter, or of the hour containing the DST spring-forward.
    #
    # A flat price across three quarters is not a contrived input either: it is what a market with
    # no intra-hour movement looks like, which is common in the small hours.
    #
    # The assertions are exact rather than allclose, because a tolerance would hide exactly the
    # failure at issue — a consumer computing `spot - spot_min` as a non-negative width and getting
    # a small negative number.
    flat = 0.41671749
    n_q = HOURS * 4
    prices = np.tile(np.array([flat, flat, flat, np.nan]), HOURS)  # 4th quarter is a gap
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _series("price_spot", "price", 900, _regular_index(_EPOCH, 900, n_q), prices),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert np.all(sf.spot_min <= sf.spot), "spot_min must not exceed the mean, even by an ULP"
    assert np.all(sf.spot <= sf.spot_max), "the mean must not exceed spot_max, even by an ULP"
    # And the bracket still reports the observed price rather than the rounded mean.
    assert np.allclose(sf.spot_min, flat) and np.allclose(sf.spot_max, flat)


def test_bracket_handles_negative_prices():
    # Negative spot prices are real in NL (oversupply on sunny, windy, low-demand hours), which is
    # why the extrema accumulators seed at ±inf rather than 0.0: a maximum seeded at 0.0 would
    # report 0.0 for an hour whose every quarter was negative, inventing a price the market never
    # cleared. Pinned here because the comment in `_resample_price_stats` names this as the reason
    # for the sentinel choice and nothing else exercises it.
    negative = np.array([-0.08, -0.02, -0.15, -0.01])
    n_q = HOURS * 4
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _series("price_spot", "price", 900, _regular_index(_EPOCH, 900, n_q),
                np.tile(negative, HOURS)),
    ])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert np.allclose(sf.spot_min, -0.15)
    assert np.allclose(sf.spot_max, -0.01)
    assert np.allclose(sf.spot, negative.mean())


# ── Frame shape and agreement with reconcile_grid ────────────────────────────────────────────


def test_pv_is_an_all_zero_array_when_no_solar_slot_is_mapped():
    # §4.4: `pv` is always present and always an array, all-zero when there is no PV, so no
    # downstream consumer needs a has_pv branch. `has_pv_series` carries the distinction instead —
    # without it, an all-zero pv from a real but idle array would be indistinguishable from none.
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert sf is not None
    assert isinstance(sf.pv, np.ndarray)
    assert len(sf.pv) == sf.intervals
    assert np.all(sf.pv == 0.0)
    assert sf.has_pv_series is False

    # With a solar slot mapped, the same field carries the real values and the flag flips.
    ds_pv = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ])
    sf_pv = simulation_frame(ds_pv, (_WIN_START, _WIN_END))
    assert sf_pv is not None
    assert np.allclose(sf_pv.pv, 3.0)
    assert sf_pv.has_pv_series is True


def test_energy_arrays_agree_with_reconcile_grid():
    # The simulation frame builds ON reconcile_grid rather than re-deriving the grid, so the band
    # (app/summary_view) and the simulation core can never disagree about the household's energy.
    # Asserted directly: same window in, identical arrays out.
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_import_t2", 2.0),
        _energy("grid_export_t1", 0.5),
        _energy("solar_production", 3.0),
        _quarter_hourly_price(),
    ])
    rec = reconcile_grid(ds, (_WIN_START, _WIN_END))
    sf = simulation_frame(ds, (_WIN_START, _WIN_END))
    assert rec is not None and sf is not None
    assert sf.grid_s == rec.grid_s
    assert sf.window == rec.window
    assert np.array_equal(sf.load, rec.load)
    assert np.array_equal(sf.pv, rec.pv)
    assert np.array_equal(sf.import_obs, rec.imp)
    assert np.array_equal(sf.export_obs, rec.exp)
    # import_obs / export_obs are validation-only (§4.4); the §6.3 balance they came from still
    # closes to CLOSURE_TOL here (no existing battery, no clamped interval in this fixture).
    assert abs(float((sf.import_obs - sf.export_obs + sf.pv - sf.load).sum())) < CLOSURE_TOL


def test_no_covering_grid_meter_returns_none():
    # The SAME guard reconcile_grid uses: no grid meter series covers the window → no simulatable
    # grid → None. An absent PRICE is deliberately NOT such a condition (see the no-price test).
    ds = _dataset([_energy("solar_production", 3.0), _quarter_hourly_price()])
    assert simulation_frame(ds, (_WIN_START, _WIN_END)) is None
    assert reconcile_grid(ds, (_WIN_START, _WIN_END)) is None
