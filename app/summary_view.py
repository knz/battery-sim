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
from app.domain.frames import SeriesFrame
from app.domain.reconcile import (
    CLAMP_UNRELIABLE_FRAC,
    DIV_GUARD_EPS,
    reconcile_grid,
)

# The per-interval reconciliation + §6.3 load reconstruction were extracted to
# app/domain/reconcile.py so the panel-③ results view (app/results_view.py) can reuse the same
# numeric core over a selectable window. DIV_GUARD_EPS and CLAMP_UNRELIABLE_FRAC now live there and
# are imported back here. This module keeps the formatting, the solar own-coverage logic, the price
# stats, and the notes — i.e. everything that shapes the band's presentation.


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


# A solar series whose total production over the window is below this (kWh) is treated as EMPTY —
# a sensor mapped but not actually reporting (near-zero deltas). We then omit the solar group and
# surface a data-quality note, rather than showing "Produced 0 kWh" or dividing self_consumption by
# ~0 (which produced the −1001532% anomaly). Set well above float noise and the odd stray reading,
# well below any real array's output over a usable window.
PV_PRESENT_FLOOR_KWH = 1.0


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

    # The per-interval reconciliation + §6.3 load reconstruction now live in reconcile_grid: window
    # + grid from the grid meter series alone (not all frames), each energy series resampled onto the
    # grid, load reconstructed and the negative clamp measured. Returns None on no covering grid
    # meter — the same guard the band had inline (nothing to summarise; main.py omits it).
    rec = reconcile_grid(dataset, dataset.window)
    if rec is None:
        return None

    # Bind the reconciliation result to the names the rest of the band already used, so the
    # formatting, notes, solar and battery blocks below are unchanged.
    window = rec.window
    grid_s = rec.grid_s
    pv = rec.pv
    exp = rec.exp
    batt_chg = rec.batt_charge
    batt_dis = rec.batt_discharge
    has_battery = rec.has_battery
    imp_total = rec.imp_total
    exp_total = rec.exp_total
    load_total = rec.load_total
    clamped_frac = rec.clamped_frac
    clamped_kwh = rec.clamped_kwh

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
