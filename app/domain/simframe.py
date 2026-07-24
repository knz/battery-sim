"""The `SimulationFrame` — every series on ONE grid, ready for the §6.6–§6.9 core (specs §4.4).

`app/domain/reconcile.py` already puts the ENERGY series on a common grid and reconstructs the
§6.3 household load. What the simulation core additionally needs is the SPOT PRICE on that same
grid, and a single container carrying the per-interval arrays together. That is this module.

**Why a separate module rather than more of reconcile.py.** reconcile.py scopes itself, in its own
top comment, to energy reconciliation + load reconstruction, and it is shared with the data-summary
band (app/summary_view.py) and the panel-③ results view, neither of which has any use for `spot`.
Price resampling also obeys different rules from energy resampling (mean / forward-fill / NaN
rather than sum), and its consumer is the simulation core, not the band. So the two stay apart —
but `simulation_frame` BUILDS ON `reconcile_grid` rather than re-deriving the grid, so there is
exactly one reconciliation path and the band and the simulation cannot drift apart on the energy
numbers.

**Price resampling is by MEAN, never by sum (specs §6.2 `resample_price`).** Energy is extensive —
Σ kWh is the same however finely it was recorded, which is why `reconcile._resample_sum` sums
deltas. A price is intensive: the hourly price corresponding to four quarter-hourly prices is their
arithmetic mean (energy-unweighted, as §6.2 states — energy weighting belongs to the §6.10 cost
accounting, not to the dispatch signal). Summing would produce a number 4× too large that still
looks like a plausible price, which is exactly the kind of error the §6.14 fixture 21 exists to
catch.

**A price may be COARSER than the grid.** §6.2's `choose_grid` lets only ENERGY series vote, so an
hourly price against 15-minute meters is reachable. §4.4 defines a price value as "EUR/kWh valid
from" its timestamp — a step function, not an interval total — so the price in force at the grid
interval's START applies: forward-fill (reconciliation `held`, lossless per the §6.2 table).

**The forward-fill hold is BOUNDED to the price point's own interval.** This is a POLICY CHOICE,
and a deliberate one: a price point declared at 3600 s spacing says what the price is for its own
hour and says nothing at all about the hour after. An unbounded hold would let a single price point
supply the dispatch signal arbitrarily far past its coverage — a year of 15-minute meters with one
day of hourly prices would come out as one stale price repeated 35,040 times — and, worse, would
report that as fully priced. So on the coarse-REGULAR path the hold stops one `resolution_s` past
the last good point and goes NaN, which makes it symmetric with the bucket-mean path. Only the
truly-IRREGULAR path (`resolution_s is None`) has no interval length to bound by; there the hold
stays unbounded, and the extrapolated intervals are COUNTED and reported instead of being hidden.

**An uncovered interval is NaN, never 0.** §4.4: `spot` "has no neutral value: an all-zero `spot`
would not mean 'no prices', it would mean 'prices are zero everywhere', and every band comparison
would silently take a definite and wrong branch". So absence is NaN and the frame reports it
(`spot_complete`, `spot_missing_intervals`) rather than hiding it in the array. `spot_complete`
means "every interval has an OBSERVED price": NaN intervals and extrapolated ones both make it
False, because the flag exists for a run precondition to gate on and a dispatch signal built from
extrapolation past coverage is not one a run should silently proceed on.

Fields of §4.4's `SimulationFrame` deliberately NOT built here, because the concerns that define
them are later increments — omitted rather than filled with invented values:
    spot_min / spot_max   the §6.16 price bracket.
    epoch_id              §6.15 configuration epochs.
    tariff_zone           §6.4 register/zone identification.
    quality               needs the per-interval ingest bitfield reconciled onto the grid, which
                          no producer writes yet.

Main items:
    CLOSURE_TOL                       float slack for sum-of-parts identities (specs §6.14).
    SimulationFrame                   the per-interval arrays on one grid (§4.4).
    simulation_frame(dataset, window) -> SimulationFrame | None   the builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.dataset import LoadedDataset
from app.domain.frames import SeriesFrame
from app.domain.reconcile import ReconciledGrid, reconcile_grid

# The floating-point slack below which a sum-of-parts identity counts as exact (specs §6.14
# "Conservation and closure identities are asserted to CLOSURE_TOL (a module constant, 1e-6)").
# It lives in the domain layer so the §6.14 conservation and waterfall-closure fixtures — and any
# runtime assertion of the same identities — share ONE number rather than each picking a tolerance.
# Numerically distinct in purpose from reconcile.DIV_GUARD_EPS (which guards a DIVISOR against being
# ~0) even though both happen to be 1e-6; they are not the same constant and should not be aliased.
CLOSURE_TOL = 1e-6

# The series name the spot price is mapped to (specs §4.1 vocabulary / series_vocab). Only the bare
# spot price is read here; `price_spot_min` / `price_spot_max` belong to the §6.16 bracket.
_SPOT_SLOT = "price_spot"


def _grid_starts(window: tuple[datetime, datetime], grid_s: int, n: int) -> np.ndarray:
    """The `n` grid interval START timestamps as UTC-naive datetime64[s] from `window[0]`.

    tz convention matches reconcile._resample_sum and summary_view._price_stats_in_window: the
    frames' indices are UTC-naive datetime64 (the pipeline holds UTC throughout, specs §4.4), so a
    tz-aware window has to lose its tz before it can be compared with them, and that is done with
    `.replace(tzinfo=None)`.

    PRECONDITION, stated plainly: the window must be tz-aware **UTC**. `.replace(tzinfo=None)` keeps
    the wall-clock reading and discards the offset, so it is correct only when the offset is zero.
    Handed a `+02:00` window it would take 12:00+02:00 to a naive 12:00 and misalign every bucket by
    two hours. The safe general form is `.astimezone(timezone.utc).replace(tzinfo=None)`.

    This is NOT fixed here on purpose. `reconcile._resample_sum` uses the identical convention, and
    every current caller passes a UTC window, so the issue is latent rather than live; diverging
    from reconcile.py would be worse than the shared latent bug, because the two would then disagree
    about bucket alignment. Known issue shared with reconcile.py; fixing it belongs there, for both.
    """
    start = np.datetime64(window[0].replace(tzinfo=None), "s")
    return start + (np.arange(n, dtype=np.int64) * grid_s).astype("timedelta64[s]")


def _resample_price_mean(
    frame: SeriesFrame, grid_s: int, window: tuple[datetime, datetime], n: int
) -> np.ndarray:
    """Bucket-MEAN of a price finer than (or equal to) the grid — specs §6.2 `resample_price`.

    Each native price point lands in the grid bucket its interval-start falls into, and the bucket's
    value is the arithmetic mean of the points that landed in it. The mean is time-/energy-
    UNWEIGHTED by §6.2's explicit choice; weighting by consumption would be a cost model, and the
    grid is coarser than the price precisely because consumption at the finer resolution is unknown.

    NOT a sum: a price is intensive (see the module comment). Buckets that received no price point
    are NaN — absence, not a zero price (§4.4).

    NaN native values (gap intervals) are excluded from both the numerator and the count, so a
    bucket with three good quarters and one gap averages the three rather than poisoning the hour.
    """
    out = np.full(n, np.nan, dtype=np.float64)
    idx = frame.index.astype("datetime64[s]")
    start = np.datetime64(window[0].replace(tzinfo=None), "s")
    offset_s = (idx - start).astype("timedelta64[s]").astype(np.int64)
    bucket = offset_s // grid_s
    values = np.asarray(frame.values, dtype=np.float64)
    inside = (bucket >= 0) & (bucket < n) & ~np.isnan(values)
    if not inside.any():
        return out
    totals = np.zeros(n, dtype=np.float64)
    counts = np.zeros(n, dtype=np.int64)
    np.add.at(totals, bucket[inside], values[inside])
    np.add.at(counts, bucket[inside], 1)
    seen = counts > 0
    out[seen] = totals[seen] / counts[seen]
    return out


def _resample_price_hold(
    frame: SeriesFrame, window: tuple[datetime, datetime], grid_s: int, n: int
) -> tuple[np.ndarray, np.ndarray]:
    """Forward-fill a price onto the grid — specs §6.2 `reindex(target_index).ffill()`, `held`.

    Returns `(spot, extrapolated)`: the per-interval price, and a boolean mask of the intervals
    whose price was held PAST the last price point's own declared interval, i.e. extrapolated
    rather than observed. The caller reports that count; see `SimulationFrame.spot_complete`.

    Used when the price is COARSER than the grid (hourly price, 15-minute meters — reachable
    because §6.2 lets only energy series vote on the grid) and when the price series is IRREGULAR
    (`resolution_s is None`), where there is no native spacing to bucket by at all.

    A price value is "EUR/kWh valid from" its timestamp (§4.4) — a step function that genuinely
    persists — so the price in force at a grid interval's START is the price of that interval. This
    is exact, not an approximation: the §6.2 table lists `held` with information cost "None".

    Grid intervals BEFORE the first price point have no price in force and stay NaN (§4.4: absence
    is not a zero price).

    **Past the LAST price point the hold is BOUNDED, when the frame knows by how much.** For a
    coarse REGULAR series the declared `resolution_s` IS the length of a price point's interval, so
    the last point covers `[t_last, t_last + resolution_s)` and makes no statement beyond it; past
    that the array goes NaN. That is a policy choice, and it is a change from holding forever: an
    unbounded hold lets one price point drive the dispatch signal arbitrarily far past coverage
    while still reading as fully priced. Bounding it also makes this path symmetric with the
    bucket-mean path, where an empty bucket is knowably price-less.

    The IRREGULAR path (`resolution_s is None`) is the one remaining case where an extrapolated
    price can run arbitrarily far past coverage. There is genuinely no interval length to bound it
    by — irregular means the series never declared one, and inferring one from the observed gaps
    would be inventing a resolution the source did not claim — and NaN-ing everything past the last
    point would discard the only statement such a series does support ("valid from"). So the hold
    stays unbounded there, and every interval past the last point is flagged in `extrapolated` so
    the frame can report it rather than hide it.

    NaN native values are skipped so a gap holds the last GOOD price rather than propagating it.

    Applying forward-fill to the irregular case at all is a resolution of a gap in §6.2, which
    specifies only regular price series (open question §8.20 leaves irregular ingest unsettled): it
    needs no `resolution_s`, follows directly from the §4.4 "valid from" definition, and coincides
    with the regular `held` case whenever the spacing happens to be uniform.
    """
    idx = frame.index.astype("datetime64[s]")
    values = np.asarray(frame.values, dtype=np.float64)
    good = ~np.isnan(values)
    idx, values = idx[good], values[good]
    out = np.full(n, np.nan, dtype=np.float64)
    extrapolated = np.zeros(n, dtype=bool)
    if len(idx) == 0:
        return out, extrapolated
    order = np.argsort(idx)  # searchsorted needs a sorted haystack; ingest order is not guaranteed
    idx, values = idx[order], values[order]

    starts = _grid_starts(window, grid_s, n)
    # Index of the last price point at or before each grid-interval start (-1 → none yet).
    pos = np.searchsorted(idx, starts, side="right") - 1
    have = pos >= 0
    out[have] = values[pos[have]]

    # Where the held value came from the FINAL price point, the interval sits past that point's own
    # start; whether it is still inside the point's declared interval decides observed vs
    # extrapolated. Interior points are never extrapolation — the next point bounds them.
    beyond = have & (pos == len(idx) - 1)
    if frame.resolution_s is None:
        extrapolated = beyond & (starts > idx[-1])
    else:
        covered_until = idx[-1] + np.timedelta64(int(frame.resolution_s), "s")
        past_coverage = starts >= covered_until
        out[past_coverage] = np.nan  # bounded hold: no statement past the last point's interval
    return out, extrapolated


def _spot_on_grid(
    frame: SeriesFrame | None, grid_s: int, window: tuple[datetime, datetime], n: int
) -> tuple[np.ndarray, np.ndarray]:
    """The per-grid-interval spot price: mean if finer/equal, forward-filled if coarser/irregular.

    Returns `(spot, extrapolated)`, the second being the mask of intervals priced by extrapolation
    past the last price point's own interval — only the irregular hold can produce those.

    Returns an all-NaN array when the price slot is absent. `price_spot` is a REQUIRED slot
    (series_vocab), but slot-first sources fill slots one at a time, so a dataset can legitimately
    exist without it yet; refusing to build a frame at all would make the builder unusable during
    that window. The gate on "no prices, cannot dispatch" belongs to the run precondition, which can
    read `spot_complete` — not to frame construction, which should not crash.
    """
    if frame is None:
        return np.full(n, np.nan, dtype=np.float64), np.zeros(n, dtype=bool)
    if frame.resolution_s is None or frame.resolution_s > grid_s:
        return _resample_price_hold(frame, window, grid_s, n)
    # The bucket-mean path never extrapolates: an empty bucket is knowably price-less, so absence
    # shows up as NaN and is counted by `spot_missing_intervals` instead.
    return _resample_price_mean(frame, grid_s, window, n), np.zeros(n, dtype=bool)


@dataclass
class SimulationFrame:
    """Every series on ONE uniform grid over one window — the simulation core's input (specs §4.4).

    All arrays have the same length: one entry per grid interval in [window[0], window[1]).

        index         UTC-naive datetime64[s], interval START, left-closed and uniform. The
                      pipeline holds UTC throughout (§4.4), so there is no local-time axis here and
                      DST transitions do not perturb the spacing.
        window        the EFFECTIVE window reconciled (grid-meter coverage clipped to the request),
                      which may be narrower than what the caller asked for.
        grid_s        the simulation grid in seconds (§6.2), the spacing of `index`.
        dt_hours      grid_s / 3600 — the per-interval duration the battery step integrates over.

        pv            kWh of PV per interval. ALWAYS PRESENT AND ALWAYS AN ARRAY: all-zero when the
                      household has no PV, filled once here. Deliberately not None and not optional
                      (§4.4) — every downstream consumer is already correct on an all-zero array, so
                      a nullable field would only push a `has_pv` branch into each of them. Whether
                      the household declared PV is carried on the config object, not here.
        load          kWh of household load per interval: the §6.3 reconstructed, battery-free,
                      standby-free load, negative-clamped. Straight from reconcile_grid.
        spot          EUR/kWh per interval, bare (mean within the interval, or the price held from
                      before it). NaN where no price covers the interval — never 0, because a zero
                      spot is a real price that would make every band comparison take a definite and
                      wrong branch (§4.4).

        import_obs    kWh imported, as measured.
        export_obs    kWh exported, as measured.
                      These two are NEVER read by the battery model (§4.4). They exist for
                      validation and diagnostics only — the §7.1 overlap diagnostic needs both, and
                      the §6.14 conservation fixture checks the reconstruction against them. Keep
                      them; do not dispatch on them.

        spot_complete            True when every interval has an OBSERVED price. Defined
                      explicitly, because this is the flag a run precondition gates on:
                      `spot_complete` requires BOTH no NaN interval AND no extrapolated one, i.e.
                      `spot_missing_intervals == 0 and spot_extrapolated_intervals == 0`. An
                      extrapolated price is a real number in the array but not an observation, and
                      a run that dispatches on it would be reported as fully priced while most of
                      its signal came from one stale point — so it does not count as complete.
        spot_missing_intervals   how many intervals have NO price (NaN) — so a caller can report
                      "prices cover 8,412 of 8,760 intervals" rather than discovering NaN
                      mid-simulation.
        spot_extrapolated_intervals   how many intervals were priced by holding the last price
                      point PAST its own declared interval. Only the irregular-price path can
                      produce these (the coarse-regular hold is bounded by `resolution_s`), so this
                      is normally 0. Reported separately from `spot_missing_intervals` because the
                      two are different failures: one has no number at all, the other has a number
                      that is an extrapolation and looks exactly like an observation.
        has_pv_series            True when a solar slot was actually mapped. Reported separately
                      precisely BECAUSE `pv` is unconditionally an array: without this, an all-zero
                      `pv` from a real but idle array is indistinguishable from no array at all.

    Not built in this increment (out of scope, see the module comment): spot_min/spot_max (§6.16),
    epoch_id (§6.15), tariff_zone (§6.4), quality. They are omitted rather than defaulted, so no
    consumer can read an invented value and believe it.
    """

    index: np.ndarray
    window: tuple[datetime, datetime]
    grid_s: int
    dt_hours: float
    pv: np.ndarray
    load: np.ndarray
    spot: np.ndarray
    import_obs: np.ndarray
    export_obs: np.ndarray
    spot_complete: bool
    spot_missing_intervals: int
    spot_extrapolated_intervals: int
    has_pv_series: bool

    @property
    def intervals(self) -> int:
        """The number of grid intervals — the common length of every array."""
        return len(self.index)


def simulation_frame(
    dataset: LoadedDataset, window: tuple[datetime, datetime]
) -> SimulationFrame | None:
    """Build the §4.4 `SimulationFrame` for `dataset` over `window`, or None (specs §6.2/§6.3).

    Steps:
      1. Run `reconcile_grid` — the SAME reconciliation the data-summary band and the results view
         use. It picks the window and grid from the grid meter series alone, resamples each energy
         series onto that grid, and reconstructs the §6.3 clamped load. Reusing it (rather than
         re-deriving the grid here) is what guarantees the simulation and the band never disagree
         about the household's energy.
      2. Resample `price_spot` onto that same grid — by MEAN when finer or equal, forward-filled
         when coarser or irregular, NaN where uncovered (see the module comment). The coarse hold
         is bounded by the price's own `resolution_s`; the irregular hold is not, and whatever it
         extrapolates is counted in `spot_extrapolated_intervals`.
      3. Fill `pv` with zeros when no solar slot is mapped, so the field is unconditionally an
         array (§4.4).

    Returns None on exactly the condition `reconcile_grid` returns None on: no grid meter series
    covers the window, so there is no simulatable grid. An ABSENT PRICE is deliberately NOT such a
    condition — the frame is still built, with an all-NaN `spot` and `spot_complete = False`.
    """
    rec: ReconciledGrid | None = reconcile_grid(dataset, window)
    if rec is None:
        return None

    n = len(rec.load)
    eff_window = rec.window
    index = _grid_starts(eff_window, rec.grid_s, n)

    by_name = {f.name: f for f in dataset.frames}
    spot, extrapolated = _spot_on_grid(by_name.get(_SPOT_SLOT), rec.grid_s, eff_window, n)
    missing = int(np.count_nonzero(np.isnan(spot)))
    # Disjoint by construction (an extrapolated interval carries a value, so it is not NaN), but
    # masked anyway so the two counts can never double-count the same interval if that changes.
    extra = int(np.count_nonzero(extrapolated & ~np.isnan(spot)))

    # §4.4: `pv` is always an array. reconcile_grid returns None for an unmapped solar slot; the
    # zero-fill happens exactly once, here, so no consumer downstream needs a has_pv branch.
    pv = rec.pv if rec.pv is not None else np.zeros(n, dtype=np.float64)

    return SimulationFrame(
        index=index,
        window=eff_window,
        grid_s=rec.grid_s,
        dt_hours=rec.grid_s / 3600.0,
        pv=pv,
        load=rec.load,
        spot=spot,
        import_obs=rec.imp,
        export_obs=rec.exp,
        # "Every interval OBSERVED" — extrapolation is not observation, see the dataclass docstring.
        spot_complete=missing == 0 and extra == 0,
        spot_missing_intervals=missing,
        spot_extrapolated_intervals=extra,
        has_pv_series=rec.pv is not None,
    )
