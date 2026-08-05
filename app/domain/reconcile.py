"""Shared per-interval reconciliation + §6.3 load reconstruction over a window (specs §6.2/§6.3).

The numeric core that both the data-summary band (app/summary_view.py, §2.3a) and the panel-③
results view (app/results_view.py, §2.4) need: given a persisted dataset and a window, pick the
simulation grid from the GRID METER series only, resample each energy series onto that grid over
the window, reconstruct household load per interval, and report the negative-load clamp.

It was extracted from summary_view — which computed all of this inline for the band — so the
results view can run the SAME reconciliation over a SELECTABLE sub-window without a second copy of
the rule. summary_view keeps its formatting, solar own-coverage logic, price stats, and notes; only
the raw reconciliation lives here.

Two policies (unchanged from summary_view, confirmed with the user — see changelog 20260724):

  * **Per-interval align + clamp (§6.3).** The grid energy series (import/export/pv/battery) are
    reconciled onto ONE common grid over the effective window (the coverage overlap the run can
    span, §6.2), then the §6.3 balance `load = imp − exp + pv + batt_dis − batt_chg` is applied per
    interval and negative load is clamped to 0. Energy sums are resolution-invariant, so
    downsampling by summing deltas is exact.
  * **Grid-meter-driven window (_WINDOW_SLOTS).** Only the meter registers define the window and
    grid; an optional series with a short span (solar/battery mapped part-way through) must NOT clip
    the grid totals to its own sub-window.

`reconcile_grid` returns None when no grid meter series covers the window (no simulatable grid):
the caller has nothing to reconcile and omits its view accordingly.

Main items:
    DIV_GUARD_EPS            below this a divisor is treated as ~0 (specs §6.11 guard).
    CLAMP_UNRELIABLE_FRAC    negative-load clamp share above which the reconstruction is unreliable.
    _WINDOW_SLOTS            the grid-meter registers that define the window/grid.
    ReconciledGrid           the structured result (grid, window, per-interval arrays, totals).
    reconcile_grid(dataset, window) -> ReconciledGrid | None   the reconciliation, or None.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.dataset import LoadedDataset
from app.domain import normalize
from app.domain.frames import SeriesFrame

# Below this magnitude (kWh or a fraction denominator) a divisor is treated as ~0 — nothing to
# divide by, so report absence rather than a divide-by-noise (specs §6.11 DIV_GUARD_EPS).
DIV_GUARD_EPS = 1e-6

# Reliability gate for the load reconstruction. When the §6.3 negative-load clamp discards more than
# this fraction of the (clamped) load, consumption and self-sufficiency are treated as UNRELIABLE.
# A few clamped intervals are normal (sensor noise, minor clock skew); a large share is a broken
# input (typically real PV export the solar sensor did not report). 5% is comfortably above the
# incidental-noise band. The two consumers (band + results) share this threshold.
CLAMP_UNRELIABLE_FRAC = 0.05

# Slots that DEFINE the window. Only the grid meter registers drive coverage — an optional series
# with a short span (a solar array or battery mapped part-way through) must NOT clip the grid totals
# to its own sub-window (specs §2.3a "sum over each series' own coverage"; the "grid import looks
# very low" fix). The effective window is the meter's, not the intersection of all series.
_WINDOW_SLOTS = ("grid_import_t1", "grid_import_t2", "grid_export_t1", "grid_export_t2")


def _resample_sum(frame: SeriesFrame, grid_s: int, window: tuple[datetime, datetime]) -> np.ndarray | None:
    """Sum `frame`'s energy onto the `grid_s` grid over `window`, as a per-grid-interval array.

    Energy totals are resolution-invariant (Σ kWh is the same however finely it was recorded), so
    downsampling is a bucketed sum of the native deltas and upsampling never happens here — an
    energy series is never coarser than the grid the run chose (specs §6.2, choose_grid picks the
    MAX covering energy resolution). Returns one value per grid interval in [window[0], window[1]),
    or None for an irregular series (no native spacing to bucket by).

    The bucketing is purely by timestamp: each native interval's energy lands in the grid bucket
    its start falls into. A native series equal to the grid maps one-to-one; a finer one sums
    several natives per bucket. Intervals the series does not cover contribute 0 (own-coverage
    policy — a series shorter than the window simply adds nothing outside its span).
    """
    if frame.resolution_s is None:
        return None
    # frame.index is UTC-naive datetime64 (the pipeline holds UTC, specs §4.4); the window is
    # tz-aware UTC. Drop the tz to compare in the same UTC-naive frame — NOT astimezone(), which
    # would shift to local time and misalign the buckets by the UTC offset.
    start = np.datetime64(window[0].replace(tzinfo=None), "s")
    end = np.datetime64(window[1].replace(tzinfo=None), "s")
    n_buckets = int((end - start).astype("timedelta64[s]").astype(np.int64) // grid_s)
    if n_buckets <= 0:
        return None
    out = np.zeros(n_buckets, dtype=np.float64)
    idx = frame.index.astype("datetime64[s]")
    offset_s = (idx - start).astype("timedelta64[s]").astype(np.int64)
    bucket = offset_s // grid_s
    inside = (bucket >= 0) & (bucket < n_buckets)
    np.add.at(out, bucket[inside], np.nan_to_num(frame.values[inside], nan=0.0))
    return out


def _grid_sum(frame: SeriesFrame | None, grid_s: int, window: tuple[datetime, datetime]) -> np.ndarray | None:
    """The per-grid-interval energy of `frame` (None → None), or None if it cannot be gridded."""
    if frame is None:
        return None
    return _resample_sum(frame, grid_s, window)


def _combined(*arrays: np.ndarray | None) -> np.ndarray | None:
    """Element-wise sum of the present arrays (None means absent), or None if all are absent.

    Used to fold the two tariff registers (T1 + T2) into a single import/export series before the
    load reconstruction, treating an unmapped register as contributing nothing.
    """
    present = [a for a in arrays if a is not None]
    if not present:
        return None
    total = np.zeros_like(present[0])
    for a in present:
        total = total + a
    return total


@dataclass
class ReconciledGrid:
    """The reconciliation of a dataset onto one grid over a window (specs §6.2/§6.3).

    Everything the band and the results view build on: the grid resolution and the EFFECTIVE window
    actually used (grid-meter coverage overlap, which may differ from the requested window), the
    per-interval energy arrays, the reconstructed load, the window totals, and the negative-load
    clamp diagnostics. Consumers format and present; this object is bare numbers.

    Per-interval arrays are one value per grid interval in [window[0], window[1]):
        imp / exp        Σ import / Σ export (tariff registers folded), always present.
        pv               Σ PV, or None when no solar slot is mapped.
        batt_charge      Σ existing-battery charge-in, or None when unmapped.
        batt_discharge   Σ existing-battery discharge-out, or None when unmapped.
        raw_load         imp − exp + pv + batt_dis − batt_chg (before the clamp; may be negative).
        load             max(raw_load, 0) — the §6.3 clamped household load.

    Totals are over the window: imp_total, exp_total, load_total (all kWh).
    clamped_kwh is the energy the clamp discarded (magnitude of negative raw_load); clamped_frac is
    its share of |reconstruction| (load_total + clamped_kwh). has_battery is True when an existing
    battery was mapped (either charge or discharge present).
    """

    grid_s: int
    window: tuple[datetime, datetime]
    imp: np.ndarray
    exp: np.ndarray
    pv: np.ndarray | None
    batt_charge: np.ndarray | None
    batt_discharge: np.ndarray | None
    raw_load: np.ndarray
    load: np.ndarray
    imp_total: float
    exp_total: float
    load_total: float
    clamped_kwh: float
    clamped_frac: float
    has_battery: bool


def reconcile_grid(
    dataset: LoadedDataset, window: tuple[datetime, datetime]
) -> ReconciledGrid | None:
    """Reconcile a dataset's energy series onto one grid over `window`, or None (specs §6.2/§6.3).

    Steps (identical to what summary_view did inline before this extraction):
      1. Pick the window + grid from the GRID METER series alone (_WINDOW_SLOTS), so a short-coverage
         optional series does not truncate the grid totals. The returned `window` is this EFFECTIVE
         window (the grid-meter coverage overlap clipped to `window`), which may differ from the
         requested one.
      2. Resample each energy series onto the grid over the window; fold the two import and the two
         export tariff registers together (T1 + T2). An unmapped slot contributes 0.
      3. Reconstruct load per interval `load = imp − exp + pv + batt_dis − batt_chg` and clamp
         negatives to 0, computing clamped_kwh / clamped_frac.

    Returns None when no grid meter series covers the window (no simulatable grid) — the caller then
    has nothing to reconcile. This is the SAME guard summary_view.data_summary_from used.
    """
    frames = dataset.frames
    by_name = {f.name: f for f in frames}

    # Window + grid from the grid meter series alone (not all frames — see _WINDOW_SLOTS).
    window_frames = [f for f in frames if f.name in _WINDOW_SLOTS]
    eff_window = normalize.effective_window(window_frames, window)
    grid_s = normalize.choose_grid(window_frames, eff_window)
    if grid_s is None:
        return None  # no covering grid meter series → nothing to reconcile

    # Grid energy on the common grid. Import/export fold their two tariff registers together; PV and
    # the existing battery are single series. An unmapped slot yields None and contributes 0.
    imp = _combined(
        _grid_sum(by_name.get("grid_import_t1"), grid_s, eff_window),
        _grid_sum(by_name.get("grid_import_t2"), grid_s, eff_window),
    )
    exp = _combined(
        _grid_sum(by_name.get("grid_export_t1"), grid_s, eff_window),
        _grid_sum(by_name.get("grid_export_t2"), grid_s, eff_window),
    )
    if imp is None or exp is None:
        return None  # no grid meter reconciled onto the grid → cannot reconcile

    pv = _grid_sum(by_name.get("solar_production"), grid_s, eff_window)
    batt_chg = _grid_sum(by_name.get("battery_charge"), grid_s, eff_window)
    batt_dis = _grid_sum(by_name.get("battery_discharge"), grid_s, eff_window)
    has_battery = batt_chg is not None or batt_dis is not None

    # §6.3 load reconstruction, per interval: load = imp − exp + pv + batt_dis − batt_chg, then clamp
    # negatives to 0. The battery terms strip an EXISTING battery; without it they are 0, so the
    # reconstructed load is net of whatever battery the household already owns (specs §6.3).
    raw_load = imp - exp
    if pv is not None:
        raw_load = raw_load + pv
    if has_battery:
        raw_load = raw_load + (batt_dis if batt_dis is not None else 0.0) - (
            batt_chg if batt_chg is not None else 0.0
        )
    negative = raw_load < 0
    load = np.maximum(raw_load, 0.0)

    imp_total = float(imp.sum())
    exp_total = float(exp.sum())
    load_total = float(load.sum())
    # Energy discarded by the clamp: the magnitude of the negative reconstructed load. Export the
    # reconstruction could NOT explain from import + PV + battery. A large amount means the
    # reconstruction is compromised (typically real PV the solar sensor did not report). Clamping
    # inflates `load` by exactly this much (§6.3).
    clamped_kwh = float(-raw_load[negative].sum())
    # Fraction of the reconstructed household energy the clamp had to discard. Denominator is
    # load + clamped so it is well-defined even when the clamp zeroed nearly everything (there,
    # clamped_frac → 1). Equivalently, the share of |reconstruction| that came out negative.
    denom = load_total + clamped_kwh
    clamped_frac = clamped_kwh / denom if denom > DIV_GUARD_EPS else 0.0

    return ReconciledGrid(
        grid_s=grid_s,
        window=eff_window,
        imp=imp,
        exp=exp,
        pv=pv,
        batt_charge=batt_chg,
        batt_discharge=batt_dis,
        raw_load=raw_load,
        load=load,
        imp_total=imp_total,
        exp_total=exp_total,
        load_total=load_total,
        clamped_kwh=clamped_kwh,
        clamped_frac=clamped_frac,
        has_battery=has_battery,
    )
