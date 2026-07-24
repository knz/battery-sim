"""Panel ③ — Results (ENERGY SAVINGS) view-model, computed from a persisted dataset (specs §2.4).

This increment brings panel ③ to life with REAL measured figures over a SELECTABLE window, but
with a deliberate simplification: the simulated battery (panel ②) is not configured yet, so it does
NOTHING — charge ≡ 0 and discharge ≡ 0. The "with battery" scenario therefore equals the baseline:
grid-import-saved = 0, self-sufficiency baseline == battery, equivalent full cycles = 0, throughput
= 0, conversion loss = 0, standby = 0. The panel honestly shows zero savings while every MEASURED
figure (import, export, PV, reconstructed load, self-sufficiency, self-consumption, export) is real.

What is NOT emitted this increment (later phases):
  * the §6.12 perfect-foresight benchmark box — the DP is not built, so no `benchmark` key is
    emitted (Phase 2 guards the template). We do not invent benchmark numbers.
  * the "intervals battery was full / empty" secondary row — meaningless with no battery; omitted.
  * annualisation — a short-window run (< min_annualisation_days) sets `annualisation_disabled`
    with a message so the template can show the §2.4 info box; nothing is annualised here anyway.

The view-model also carries a `data_summary` key: the §2.3a "Your data at a glance" figures repeated
inside panel ③ but computed over the SELECTED window (spot price clamped to it too), rendered from
the shared _data_glance.html macro so it swaps with the panel on every range change.

Omit-don't-zero (§2.4 "Panel ③ without PV"): the self-consumption row is omitted when there is no
PV (its denominator is PV); grid export is shown as a real figure (structurally zero without PV, but
we show the measured value). Numbers are formatted here (thousands-separated kWh, integer percent)
so the template stays dumb, matching app/summary_view.py.

`results_from` returns None when the reconcile helper returns None (no simulatable grid) — the caller
falls back to the empty state, exactly like data_summary_from.

Also here (Deliverable C): `resolve_window` turns a request (a preset period, or an explicit
start/end range) into a concrete UTC window against the dataset's coverage, anchored to the END of
data coverage (§7.4), clamped to coverage, never padding with zeros.

Main items:
    PERIOD_DAYS               preset name → span in days (§7.4 predefined ranges).
    min_annualisation_days    below this a window is too short to annualise (specs appendix-a, §7.4).
    resolve_window(dataset, *, period, start, end) -> (start, end)   the window resolver.
    results_from(dataset, window) -> dict | None   the panel-③ energy-savings view-model, or None.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from app.dataset import LoadedDataset
from app.domain import normalize
from app.domain.reconcile import (
    CLAMP_UNRELIABLE_FRAC,
    DIV_GUARD_EPS,
    _WINDOW_SLOTS,
    ReconciledGrid,
    reconcile_grid,
)
from app.data_view import _fmt_res
from app.summary_view import data_summary_from

# summary_view imports from reconcile/dataset/frames, NOT from results_view, so this top-level
# import does not cycle. The panel-③ copy (results.data_summary) is the SAME "Your data at a glance"
# view-model, but computed over the SELECTED window with the spot price clamped to it too.

# Below this PV total (kWh) self_consumption is undefined — nothing was generated to consume
# (specs §6.11). Kept in step with summary_view.PV_PRESENT_FLOOR_KWH: a PV slot mapped but not
# actually reporting is treated as no-PV for the self-consumption row (omit-don't-zero, §2.4).
PV_PRESENT_FLOOR_KWH = 1.0

# Below this many days a window is too short to annualise without large seasonal error — battery
# savings are strongly seasonal, so scaling e.g. a July week to a year overstates by ~2–3× (specs
# §7.4, appendix-a `min_annualisation_days` = 90). We do not annualise anything this increment; the
# flag just lets the template show the §2.4 short-window info box. There is no config field for this
# yet, so it is a module constant matching the spec default.
min_annualisation_days = 90

# Preset periods, anchored to the END of data coverage (§7.4 — NOT now()). Span in days each preset
# reaches back from the coverage end. The names are the request tokens; the wireframe's human labels
# ("1 week", …) are separate (see _PERIOD_LABELS).
PERIOD_DAYS: dict[str, int] = {
    "last_1_week": 7,
    "last_30_days": 30,
    "last_3_months": 90,
    "last_6_months": 182,
    "last_1_year": 365,
}

# The default request when no period/range is given: the full year, matching the wireframe default
# `period_selected: "1 year"` (sample_data._panel_results). Documented so the choice is not a
# surprise — a caller wanting full coverage passes an explicit range instead.
DEFAULT_PERIOD = "last_1_year"

# Human labels for the period selector, in wireframe order (sample_data._panel_results.periods).
# English source strings; the template wraps them in _() so the existing catalog covers them.
_PERIOD_LABELS = ["1 week", "1 month", "3 months", "6 months", "1 year"]
# The label the selector highlights, keyed off the preset the window was resolved from. Kept as the
# wireframe default ("1 year") for the full-coverage / explicit-range case.
_PERIOD_SELECTED_BY_NAME: dict[str, str] = {
    "last_1_week": "1 week",
    "last_30_days": "1 month",
    "last_3_months": "3 months",
    "last_6_months": "6 months",
    "last_1_year": "1 year",
}

# Short calendar-month names for the monthly chart x-axis (index 1..12).
_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _coverage_window(dataset: LoadedDataset) -> tuple[datetime, datetime]:
    """The dataset's effective grid-meter coverage window (§6.2/§7.4 anchoring).

    Anchoring must be to the data, not to wall-clock now(), so preset periods reach back from the
    LAST timestamp in the meter data (§7.4). This uses the SAME grid-meter-driven effective window
    reconcile_grid/results_from use, so the anchor the presets clamp against and the window the
    results are computed over agree.
    """
    window_frames = [f for f in dataset.frames if f.name in _WINDOW_SLOTS]
    return normalize.effective_window(window_frames, dataset.window)


def _as_utc(dt: datetime) -> datetime:
    """Normalise a datetime to tz-aware UTC (naive read as UTC, per the §4.4 UTC pipeline)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_window(
    dataset: LoadedDataset,
    *,
    period: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve a request into a concrete (start, end) UTC window against the dataset's coverage.

    Two request shapes (specs §7.4 window anchoring):
      * A preset `period` (one of PERIOD_DAYS): the window ends at the dataset's coverage END (the
        last timestamp present in the data, NOT now()) and starts `period` days before it, clamped
        to coverage start — never before the data begins ("clamp to coverage and say so; never pad
        with zeros"). A short history simply yields a shorter window.
      * An explicit `(start, end)` range: both ends clamped to coverage; must be non-empty.

    No arguments → the DEFAULT_PERIOD preset (last_1_year), matching the wireframe default. A
    `period` and an explicit range are mutually exclusive.

    Raises ValueError on an invalid/empty request (unknown preset, end <= start, or a range that
    clamps to empty) so the route can turn it into a 400.
    """
    cov_start, cov_end = _coverage_window(dataset)

    if period is not None and (start is not None or end is not None):
        raise ValueError("give either a preset period or an explicit start/end range, not both")

    if start is not None or end is not None:
        # Explicit range. Default an open end to the coverage end, an open start to coverage start,
        # then clamp both into coverage. Validate non-empty AFTER clamping (a range entirely outside
        # coverage clamps to empty and is rejected rather than silently zero-length).
        r_start = _as_utc(start) if start is not None else cov_start
        r_end = _as_utc(end) if end is not None else cov_end
        if r_end <= r_start:
            raise ValueError(f"empty range: end {r_end} <= start {r_start}")
        w_start = max(r_start, cov_start)
        w_end = min(r_end, cov_end)
        if w_end <= w_start:
            raise ValueError("requested range does not overlap the dataset coverage")
        return w_start, w_end

    # Preset (or the default when nothing was asked).
    name = period if period is not None else DEFAULT_PERIOD
    days = PERIOD_DAYS.get(name)
    if days is None:
        raise ValueError(f"unknown period preset: {name!r}")
    # Anchor the END to coverage end (§7.4); reach back `days`, clamped to coverage start.
    w_end = cov_end
    w_start = max(cov_end - timedelta(days=days), cov_start)
    if w_end <= w_start:
        # Degenerate coverage (zero-length dataset window); nothing to span.
        raise ValueError("dataset coverage is empty")
    return w_start, w_end


def _period_selected_for(dataset: LoadedDataset, window: tuple[datetime, datetime]) -> str:
    """The selector label to highlight for `window`, inferred from its span (best effort).

    The results view is given a resolved window, not the preset name it came from, so we map the
    window's day-span back to the closest preset label. This drives which selector button reads as
    active; it is presentation only. Defaults to the wireframe "1 year".
    """
    span_days = (window[1] - window[0]).days
    # Nearest preset by day count; ties resolve to the first (shortest) match.
    best_name = min(PERIOD_DAYS, key=lambda n: abs(PERIOD_DAYS[n] - span_days))
    return _PERIOD_SELECTED_BY_NAME.get(best_name, "1 year")


def _fmt_kwh(total: float) -> str:
    """kWh total → "1,234 kWh" (thousands-separated, rounded to whole kWh, matching summary_view)."""
    return f"{round(total):,} kWh"


def _fmt_pct(fraction: float) -> str:
    """A 0..1 fraction → an integer-percent string like "31%" (the sample's presentation)."""
    return f"{round(100 * fraction)}%"


def _self_sufficiency(rec: ReconciledGrid) -> float:
    """1 − import/load over the window (§6.11), display-clamped to ≥ 0. 0 when load is ~0."""
    if rec.load_total <= DIV_GUARD_EPS:
        return 0.0
    return max(0.0, 1 - rec.imp_total / rec.load_total)


def _pv_self_consumption(dataset: LoadedDataset, rec: ReconciledGrid) -> float | None:
    """1 − export/pv over the PV's OWN coverage window (§6.11), or None when there is no usable PV.

    Mirrors summary_view._add_solar: PV may cover only part of the grid window (panels installed
    part-way through), so both PV and the export it is compared against are restricted to the PV
    coverage sub-window. Returns None when no PV slot is mapped, the PV frame is empty, or its total
    over its coverage is below PV_PRESENT_FLOOR_KWH (a sensor mapped but not really reporting) — all
    the omit-don't-zero cases for the self-consumption row (§2.4 "Panel ③ without PV").
    """
    if rec.pv is None:
        return None
    solar_frame = next((f for f in dataset.frames if f.name == "solar_production"), None)
    if solar_frame is None:
        return None
    cov = solar_frame.coverage()
    if cov is None:
        return None
    pv_start, pv_end = cov
    # Grid-interval mask over the effective window, restricting to the PV coverage sub-window.
    win_start = np.datetime64(rec.window[0].replace(tzinfo=None), "s")
    n = len(rec.pv)
    bucket_start = win_start + (np.arange(n) * rec.grid_s).astype("timedelta64[s]")
    ps = np.datetime64(pv_start.replace(tzinfo=None), "s")
    pe = np.datetime64(pv_end.replace(tzinfo=None), "s")
    in_pv = (bucket_start >= ps) & (bucket_start < pe)

    pv_total = float(rec.pv[in_pv].sum())
    if pv_total < PV_PRESENT_FLOOR_KWH:
        return None  # mapped but effectively empty → omit the row
    exp_pv_window = float(rec.exp[in_pv].sum())
    return 1 - exp_pv_window / pv_total


def _monthly_import(rec: ReconciledGrid) -> dict:
    """Monthly Σ grid-import over the window for the chart, as {"months": [...], "values": [...]}.

    A real series (not sample data): each grid interval's import is bucketed by the calendar month
    its start falls in, summed, and rounded to whole kWh. Months are short names in chronological
    order across the window. This stays in scope (no simulation needed) while being an honest,
    dataset-derived monthly breakdown of measured grid import.
    """
    n = len(rec.imp)
    win_start = np.datetime64(rec.window[0].replace(tzinfo=None), "s")
    bucket_start = win_start + (np.arange(n) * rec.grid_s).astype("timedelta64[s]")
    # (year, month) key per interval, kept in first-seen (chronological) order.
    years = bucket_start.astype("datetime64[Y]").astype(int) + 1970
    months = bucket_start.astype("datetime64[M]").astype(int) % 12 + 1
    labels: list[str] = []
    values: list[float] = []
    seen: dict[tuple[int, int], int] = {}
    for i in range(n):
        key = (int(years[i]), int(months[i]))
        if key not in seen:
            seen[key] = len(values)
            labels.append(_MONTH_ABBR[key[1]])
            values.append(0.0)
        values[seen[key]] += float(rec.imp[i])
    return {"months": labels, "values": [round(v) for v in values]}


def results_from(
    dataset: LoadedDataset, window: tuple[datetime, datetime]
) -> dict | None:
    """Build the panel-③ ENERGY SAVINGS view-model over `window`, zero-battery (specs §2.4).

    Shape-compatible with sample_data._panel_results() EXCEPT: no `benchmark` key (the §6.12 DP is
    not built this increment) and the "intervals battery full/empty" secondary row is omitted (no
    battery). Returns None when reconcile_grid returns None (no simulatable grid) — the caller then
    falls back to the empty state, exactly like data_summary_from.

    With charge ≡ discharge ≡ 0, the "with battery" import equals the baseline import, so every
    savings figure is honestly zero while the measured figures (import, export, PV, load,
    self-sufficiency, self-consumption) are real.
    """
    rec = reconcile_grid(dataset, window)
    if rec is None:
        return None

    eff = rec.window  # the effective window actually reconciled (may differ from the requested one)
    intervals = len(rec.imp)
    res_label = _fmt_res(rec.grid_s)

    # The picker's coverage line, split in two so the template can insert the day count between
    # them: "<dates> · N days · simulated hourly · 8,760 intervals". The day count is the
    # template's to render because "day"/"days" needs ngettext, whereas these parts are bare
    # literals. The data-glance section below the picker used to repeat this span; it no longer
    # does, so the selected range's length is stated once per panel, here.
    period_dates = f"{eff[0].date().isoformat()} → {eff[1].date().isoformat()}"
    period_run = f"simulated {res_label} · {intervals:,} intervals"
    period_days = (eff[1] - eff[0]).days
    # `period` stays the whole line as one string for any consumer that wants it unsplit (and so
    # the sample view-model's shape is unchanged); the template renders the parts.
    period = f"{period_dates} · {period_run}"

    # Baseline == battery under the zero-battery assumption.
    ss = _self_sufficiency(rec)  # baseline self-sufficiency == battery self-sufficiency
    ss_str = _fmt_pct(ss)
    self_consumption = _pv_self_consumption(dataset, rec)  # None when no usable PV

    # ── KPI tiles (§2.4). All savings are zero this increment; self-sufficiency baseline == battery.
    kpis = [
        {"title": "GRID IMPORT SAVED", "value": "0", "unit": "kWh", "delta": "0 %"},
        {"title": "SELF-SUFFICIENCY", "value": f"{ss_str} → {ss_str}", "delta": "+0 pp"},
        {"title": "EQUIVALENT FULL CYCLES", "value": "0",
         "delta": "0.00 / day", "extra": "0 kWh throughput"},
    ]

    # ── "Where the energy comes from" breakdown (§2.4). Import with battery == import no battery,
    # so avoided = 0. Everything the battery would move is 0 (it does nothing this increment). Label
    # msgids match the sample so existing translations apply.
    imp_str = _fmt_kwh(rec.imp_total)
    energy_breakdown = [
        {"label": "Grid import, no battery", "value": imp_str},
        {"label": "Grid import, with battery", "value": imp_str},
        {"label": "Grid import avoided", "value": "0 kWh", "rule_above": True},
        {"label": "Charged into the battery", "value": "0 kWh", "gap_above": True},
        {"label": "Discharged from the battery", "value": "0 kWh"},
        {"label": "Conversion losses", "value": "0 kWh"},
        {"label": "Standby consumption", "value": "0 kWh"},
    ]

    # ── Secondary metrics (§2.4). Self-consumption omitted without usable PV (omit-don't-zero); it
    # is baseline == battery when shown. Grid export is the measured figure, equal on both sides.
    exp_str = _fmt_kwh(rec.exp_total)
    secondary = []
    if self_consumption is not None:
        sc_str = _fmt_pct(self_consumption)
        secondary.append({"label": "Self-consumption ratio", "value": f"{sc_str} → {sc_str}"})
    secondary.append({"label": "Grid export", "value": f"{exp_str} → {exp_str}"})
    # "Intervals battery was full / empty" omitted — meaningless with no battery this increment.

    # ── Caveats: real data-quality notes (§2.4). Plain English strings; the template wraps them in
    # _() and a later phase extracts them to the catalog. Order: reconstruction reliability, then
    # price granularity, then ALWAYS the honest "battery not configured → savings are zero" note.
    caveats: list[str] = []
    if rec.clamped_frac > CLAMP_UNRELIABLE_FRAC:
        caveats.append(
            f"Reconstructed household load was negative in a large share of intervals and clamped "
            f"to zero ({_fmt_kwh(rec.clamped_kwh)} discarded against {exp_str} exported). This "
            f"usually means solar export the PV sensor did not report, or an unmapped battery — "
            f"so the load and self-sufficiency figures here are unreliable."
        )
    price_lost = normalize.price_granularity_lost(dataset.frames, rec.grid_s)
    if price_lost["lost"]:
        native = _fmt_res(price_lost["native_resolution_s"])
        caveats.append(
            f"Spot prices are recorded every {native} but the run is {res_label}, so the battery "
            f"would act on an averaged price and could not chase within-interval swings."
        )
    # Always: the honest headline for this increment. No battery is configured, so the simulator
    # moves no energy and every savings figure above is zero by construction — the measured figures
    # (import, export, self-sufficiency) are real, but the "with battery" columns equal the baseline.
    caveats.append(
        "No battery is configured yet, so the simulated battery does nothing: every savings figure "
        "is zero and the “with battery” columns equal your measured baseline. Configure a "
        "battery to see what it would have saved."
    )

    # The "Your data at a glance" figures, repeated inside panel ③ but over the SELECTED range (the
    # effective reconcile window), with the spot price clamped to that range too — unlike the
    # panel-① copy, which prices over the series' own full coverage (decision confirmed with
    # the user, changelog 20260724). It renders from the SAME shared macro (_data_glance.html), so
    # it re-renders on every range change inside the swappable #panel-results region. Defensive
    # None-guard: data_summary_from should not return None once reconcile_grid succeeded here, but
    # if it does the template guards `results.data_summary`.
    data_summary = data_summary_from(dataset, window=eff, clamp_price_to_window=True)

    result: dict = {
        "period": period,
        "period_dates": period_dates,
        "period_days": period_days,
        "period_run": period_run,
        "periods": list(_PERIOD_LABELS),
        "period_selected": _period_selected_for(dataset, eff),
        "data_summary": data_summary,
        "kpis": kpis,
        "energy_breakdown": energy_breakdown,
        # No `benchmark` key this increment (§6.12 DP not built); Phase 2 guards the template.
        "secondary": secondary,
        "chart": _monthly_import(rec),
        "caveats": caveats,
    }

    # Short-window guard (§7.4): below min_annualisation_days annualisation is disabled. We annualise
    # nothing here; the flag + message let the template show the §2.4 info box. Uses the EFFECTIVE
    # span (what the run actually covers), not the requested one.
    span_days = (eff[1] - eff[0]).days
    if span_days < min_annualisation_days:
        result["annualisation_disabled"] = True
        result["annualisation_message"] = (
            f"Annualised projection is disabled for ranges under {min_annualisation_days} days. "
            "Battery savings are strongly seasonal; scaling a short window to a year can overstate "
            "annual savings by a factor of roughly 2–3. Select 6 months or 1 year to see an annual "
            "figure."
        )

    return result
