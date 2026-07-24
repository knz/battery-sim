"""The data summary band's view-model, computed from a persisted dataset (specs §2.3a).

Increment 2 of the data summary band: where app/sample_data._data_summary() hard-codes the
"Your data at a glance" figures, this module computes them from the ingested SeriesFrames.
It is the battery-free slice of the §6.11 energy metrics over the §6.3 load reconstruction —
the figures that follow from the household's OWN recorded data before the *simulated* battery
(panel ②) is configured.

What it computes (specs/12-metrics-and-benchmarks.md §6.11, §6.3):
    grid.imported / grid.exported          Σ import, Σ export over the window.
    household.consumption                   Σ reconstructed load (§6.3), per-interval clamped.
    household.self_sufficiency              1 − import.sum() / load.sum(), display-clamped to ≥ 0%.
    household.self_sufficiency_clamped      True when that clamp fired (import > load over window).
    household.net_battery                   True when an existing battery was mapped and stripped.
    solar.produced / solar.self_consumption Σ PV, 1 − export/pv over the PV's OWN coverage window
                                            (omitted when no PV, or when PV is mapped but empty).
    solar.coverage / solar.days / .partial  the PV sub-window, so a short PV history is not misread.
    battery.charged / battery.discharged    Σ of the EXISTING battery's throughput (omitted absent).
    price.avg / price.min / price.max       spot-price aggregates over its own coverage (omitted absent).
    notes                                   data-quality note keys (e.g. "solar_empty"), shown as caveats.

Two policies, both confirmed with the user (see changelog 20260724):

  * **Per-interval align + clamp (§6.3).** The grid energy series (import/export/pv/battery) are
    reconciled onto ONE common grid over the effective window (the coverage overlap the run can
    span, specs §6.2), then the §6.3 balance is applied per interval and negative load is clamped
    to 0. self_sufficiency uses the clamped load, matching §6.11. Energy sums are
    resolution-invariant, so downsampling by summing deltas is exact.
  * **Own-coverage aggregates for price.** The price avg/min/max are taken over the price series'
    own coverage, not the grid window — a spot series bridged past the meter coverage still reports
    honest price stats, and an optional short-coverage series never truncates the grid totals
    (existing battery added mid-window, open question §8.6).

`data_summary_from` returns None when there is no covering energy series (no simulatable grid):
the band has nothing to summarise, so main.py omits it exactly as in the empty state.

Formatting (thousands-separated kWh, integer percent, €/kWh to 3 dp) lives here so the template
stays unchanged from the sample; the values are bare data (no translation).

Main items:
    data_summary_from(dataset) -> dict | None    the §2.3a band view-model, or None if unsummarisable.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from app.dataset import LoadedDataset
from app.domain import normalize
from app.domain.frames import SeriesFrame

# Below this PV total (kWh) self_consumption is undefined — nothing was generated to consume, so
# report it as absent rather than dividing by ~0 (specs §6.11 DIV_GUARD_EPS). A household with a
# PV slot mapped but no production over the window falls here.
DIV_GUARD_EPS = 1e-6


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


def _fmt_kwh(total: float) -> str:
    """kWh total → "1,234 kWh" (thousands-separated, rounded to whole kWh, matching the sample)."""
    return f"{round(total):,} kWh"


def _fmt_pct(fraction: float) -> str:
    """A 0..1 fraction → an integer-percent string like "31%" (the sample's presentation)."""
    return f"{round(100 * fraction)}%"


def _fmt_eur(value: float) -> str:
    """A €/kWh value → "0.142 €/kWh", 3 dp, with a real minus sign for negatives (the sample look)."""
    s = f"{value:.3f}"
    if s.startswith("-"):
        s = "−" + s[1:]  # U+2212 MINUS, as the sample uses for negative spot prices
    return f"{s} €/kWh"


def _price_stats(frame: SeriesFrame | None) -> dict | None:
    """avg/min/max of a price series over its own coverage, or None if absent/empty (§2.3a).

    The average is the plain time-unweighted mean of the per-interval prices — the band's headline
    is "the price you saw", not an energy-weighted cost, which belongs to the cost accounting
    (§6.10). NaNs (gap intervals) are ignored.
    """
    if frame is None or len(frame.values) == 0:
        return None
    vals = np.asarray(frame.values, dtype=np.float64)
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return None
    return {
        "avg": _fmt_eur(float(vals.mean())),
        "min": _fmt_eur(float(vals.min())),
        "max": _fmt_eur(float(vals.max())),
    }


# Slots that DEFINE the band's window. Only the grid meter registers drive coverage — an optional
# series with a short span (a solar array or battery mapped part-way through, e.g. panels installed
# six months into a two-year meter history) must NOT clip the grid/household totals to its own
# sub-window. Each optional group is instead summed over its OWN coverage within this window and
# reports its own span (specs §2.3a "sum over each series' own coverage"). This is the fix for the
# "grid import looks very low" case: the effective window is the meter's, not the intersection.
_WINDOW_SLOTS = ("grid_import_t1", "grid_import_t2", "grid_export_t1", "grid_export_t2")

# A solar series whose total production over the window is below this (kWh) is treated as EMPTY —
# a sensor mapped but not actually reporting (near-zero deltas). We then omit the solar group and
# surface a data-quality note, rather than showing "Produced 0 kWh" or dividing self_consumption by
# ~0 (which produced the −1001532% anomaly). Set well above float noise and the odd stray reading,
# well below any real array's output over a usable window.
PV_PRESENT_FLOOR_KWH = 1.0

# Reliability gate for the load reconstruction. When the §6.3 negative-load clamp discards more
# than this fraction of the (clamped) load, consumption and self-sufficiency are treated as
# UNRELIABLE and suppressed with a warning — the clamp is inflating load by that much, so the two
# figures built on it cannot be trusted. The dominant cause is real PV export the solar sensor did
# not report (or an unmapped battery discharging to the grid). A few clamped intervals are normal
# (sensor noise, minor clock skew); a large share is a broken input. 5% is comfortably above the
# incidental-noise band and well below the ~23% this dataset's missing-PV case produced.
CLAMP_UNRELIABLE_FRAC = 0.05


def data_summary_from(dataset: LoadedDataset) -> dict | None:
    """Build the §2.3a data summary band view-model from a persisted dataset, or None.

    Returns the same shape as sample_data._data_summary() (grid / household / solar / battery /
    price groups, the net_battery flag, coverage + days), computed from the frames per §6.3/§6.11.
    Returns None when no grid meter series covers the window (no simulatable grid) — the band then
    has nothing to summarise and main.py omits it, as in the empty state.

    The window is driven by the GRID METER coverage only (_WINDOW_SLOTS), not the intersection of
    all series, so a short-coverage optional series (solar/battery mapped part-way through) does not
    truncate the grid totals. Optional groups sum over their own coverage within this window.
    """
    frames = dataset.frames
    by_name = {f.name: f for f in frames}

    # Window + grid from the grid meter series alone (not all frames — see _WINDOW_SLOTS).
    window_frames = [f for f in frames if f.name in _WINDOW_SLOTS]
    window = normalize.effective_window(window_frames, dataset.window)
    grid_s = normalize.choose_grid(window_frames, window)
    if grid_s is None:
        return None  # no covering grid meter series → nothing to summarise (band omitted)

    # Grid energy on the common grid. Import/export fold their two tariff registers together; PV
    # and the existing battery are single series. An unmapped slot yields None and contributes 0.
    imp = _combined(
        _grid_sum(by_name.get("grid_import_t1"), grid_s, window),
        _grid_sum(by_name.get("grid_import_t2"), grid_s, window),
    )
    exp = _combined(
        _grid_sum(by_name.get("grid_export_t1"), grid_s, window),
        _grid_sum(by_name.get("grid_export_t2"), grid_s, window),
    )
    if imp is None or exp is None:
        return None  # no grid meter reconciled onto the grid → cannot summarise

    pv = _grid_sum(by_name.get("solar_production"), grid_s, window)
    batt_chg = _grid_sum(by_name.get("battery_charge"), grid_s, window)
    batt_dis = _grid_sum(by_name.get("battery_discharge"), grid_s, window)
    has_battery = batt_chg is not None or batt_dis is not None

    # §6.3 load reconstruction, per interval: load = imp − exp + pv + batt_dis − batt_chg, then
    # clamp negatives to 0. The battery terms strip an EXISTING battery; without it they are 0, so
    # the reconstructed load is net of whatever battery the household already owns (specs §6.3).
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
    # Energy discarded by the clamp: the magnitude of the negative reconstructed load. This is
    # export the reconstruction could NOT explain from import + PV + battery. A large amount means
    # the reconstruction is compromised — typically real PV the solar sensor did not report, or an
    # unmapped battery discharging to the grid (§6.3). Clamping inflates `load` by exactly this
    # much, so consumption and self-sufficiency built on it become untrustworthy.
    clamped_kwh = float(-raw_load[negative].sum())
    # Fraction of the reconstructed household energy that the clamp had to discard. Denominator is
    # load + clamped so it is well-defined even when the clamp zeroed nearly everything (load_total
    # ≈ 0 with heavy clamping is the MOST unreliable case, not a divide-by-zero to swallow): there,
    # clamped_frac → 1. Equivalently, the share of |reconstruction| that came out negative.
    denom = load_total + clamped_kwh
    clamped_frac = clamped_kwh / denom if denom > DIV_GUARD_EPS else 0.0

    # RELIABILITY GATE. When the clamp discarded a material share of the load, consumption and
    # self-sufficiency are unreliable — do not present them as fact. Surface a prominent warning
    # and suppress the two affected figures (grid import/export and price stay: they are measured,
    # not reconstructed). The likely cause is a PV array producing export the solar sensor is not
    # reporting (this dataset: 2,096 kWh exported, solar reads ~0), so the note points the user at
    # their PV/battery sensors. Below the threshold the reconstruction is trusted (specs §2.3a).
    recon_unreliable = clamped_frac > CLAMP_UNRELIABLE_FRAC

    household: dict = {"net_battery": has_battery}
    if recon_unreliable:
        household["consumption"] = None
        household["self_sufficiency"] = None
        household["self_sufficiency_clamped"] = False
    else:
        # self_sufficiency = 1 − import/load (§6.11), on the clamped load (always ≥ 0). Still
        # display-clamped to ≥ 0% for the small-residual case an existing battery causes (ended the
        # window more charged than it started); that caveat is shown via self_sufficiency_clamped.
        ss_raw = 1 - imp_total / load_total if load_total > DIV_GUARD_EPS else 0.0
        household["consumption"] = _fmt_kwh(load_total)
        household["self_sufficiency"] = _fmt_pct(max(0.0, ss_raw))
        household["self_sufficiency_clamped"] = ss_raw < 0

    summary: dict = {
        "coverage": f"{window[0].date().isoformat()} → {window[1].date().isoformat()}",
        "days": (window[1] - window[0]).days,
        "grid": {"imported": _fmt_kwh(imp_total), "exported": _fmt_kwh(exp_total)},
        "household": household,
        # Omit-don't-zero (§2.4): a group whose inputs are absent is None, and the template drops it.
        "solar": None,
        "battery": None,
        "price": _price_stats(by_name.get("price_spot")),
        # Data-quality notes surfaced with the band. Each is (key, **params) the template renders as
        # a caveat; §6.3 / §2.3a discipline: say what happened rather than present a clamped or empty
        # series as clean. "load_unreliable" carries the unexplained-export figures.
        "notes": [],
    }
    if recon_unreliable:
        summary["notes"].append({
            "key": "load_unreliable",
            "clamped_kwh": _fmt_kwh(clamped_kwh),
            "export_kwh": _fmt_kwh(exp_total),
        })

    _add_solar(summary, by_name.get("solar_production"), pv, exp, grid_s, window)

    if has_battery:
        summary["battery"] = {
            "charged": _fmt_kwh(float(batt_chg.sum()) if batt_chg is not None else 0.0),
            "discharged": _fmt_kwh(float(batt_dis.sum()) if batt_dis is not None else 0.0),
        }

    return summary


def _add_solar(
    summary: dict,
    solar_frame: SeriesFrame | None,
    pv: np.ndarray | None,
    exp_full: np.ndarray,
    grid_s: int,
    window: tuple[datetime, datetime],
) -> None:
    """Populate summary['solar'] (or leave it None + add a note) from the PV series (§2.3a).

    The PV series may cover only PART of the grid window — panels installed part-way through a
    longer meter history (a real case: an array added six months into a two-year record). So both
    the produced total AND the self_consumption ratio are computed over the PV's OWN coverage
    sub-window, and export is restricted to that same sub-window — comparing 140 days of PV against
    two years of export would be meaningless. The solar group also reports its own span so it is not
    misread against the (longer) grid window.

    A PV series that sums below PV_PRESENT_FLOOR_KWH over its coverage is treated as EMPTY — mapped
    but not actually reporting. The group is then omitted (omit-don't-zero) and a data-quality note
    is added, rather than showing "Produced 0 kWh" or dividing self_consumption by ~0.
    """
    if solar_frame is None or pv is None:
        return  # no PV slot mapped → no solar group, no note (nothing was claimed)

    cov = solar_frame.coverage()
    if cov is None:
        return
    pv_start, pv_end = cov
    # Restrict both PV and export to the PV coverage sub-window (grid-interval mask over `window`).
    win_start = np.datetime64(window[0].replace(tzinfo=None), "s")
    n = len(pv)
    bucket_start = win_start + (np.arange(n) * grid_s).astype("timedelta64[s]")
    ps = np.datetime64(pv_start.replace(tzinfo=None), "s")
    pe = np.datetime64(pv_end.replace(tzinfo=None), "s")
    in_pv = (bucket_start >= ps) & (bucket_start < pe)

    pv_total = float(pv[in_pv].sum())
    if pv_total < PV_PRESENT_FLOOR_KWH:
        # Mapped but effectively empty: a sensor that never really reported. Say so; show nothing.
        summary["notes"].append({"key": "solar_empty"})
        return

    exp_pv_window = float(exp_full[in_pv].sum())
    span_days = (pv_end - pv_start).days
    solar: dict = {
        "produced": _fmt_kwh(pv_total),
        # self_consumption = 1 − export/pv over the PV window (§6.11); pv_total ≥ floor > 0 here.
        "self_consumption": _fmt_pct(1 - exp_pv_window / pv_total),
        # Its own span, so a short PV history is not read as covering the whole grid window.
        "coverage": f"{pv_start.date().isoformat()} → {pv_end.date().isoformat()}",
        "days": span_days,
        # True when PV covers materially less than the grid window (< 90% of its span), so the
        # template labels it "since <date>" rather than letting the reader assume the whole period.
        "partial": (pv_end - pv_start) < 0.9 * (window[1] - window[0]),
    }
    summary["solar"] = solar
