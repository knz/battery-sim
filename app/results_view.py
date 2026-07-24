"""Panel ③ — Results (ENERGY SAVINGS) view-model, computed from a persisted dataset (specs §2.4).

Panel ③ now shows REAL SIMULATED battery figures. The previous increment hard-zeroed every
battery-side number because there was no simulation core; there is one now (§6.6–§6.9,
`app/domain/simulate.py`) and a §6.11 metrics layer over it (`app/domain/metrics.py`), so this
module builds a `SimulationFrame`, runs A/B/C, and reports what the battery actually did.

The pipeline per request:

    reconcile_grid   →  the energy series on one grid + the §6.3 reconstructed load
    simulation_frame →  the same, plus the spot price on that grid (§4.4)
    run_all          →  runs A (baseline), B (battery, no standby), C (battery + standby)
    energy_metrics   →  the §6.11 figures
    (here)           →  KPI tiles, the energy breakdown, secondary metrics, caveats

**The configuration is appendix-A defaults, not the user's.** Panel ② is not wired to a config
object yet (Phase 6), so `SimulationConfig()` is constructed with its documented defaults — 10 kWh
usable, 10–100% SoC, 5/5 kW, 90% round trip, 30 W standby, charge P3, discharge D1, no grid export,
1×25 A connection, cost simulation off. The figures below are therefore "what THIS battery would
have done", not "what YOUR battery would have done", and a caveat says so until Phase 6 binds the
form. That is a deliberately visible placeholder rather than a hidden assumption.

What is NOT emitted this increment (later phases):
  * the §6.12 perfect-foresight benchmark box — the DP is not built, so no `benchmark` key is
    emitted (the template guards on it). We do not invent benchmark numbers.
  * the "intervals battery was full / empty" secondary row — it needs a SoC-bound comparison the
    metrics layer does not own yet; omitted rather than guessed.
  * annualisation — a short-window run (< min_annualisation_days) sets `annualisation_disabled`
    with a message so the template can show the §2.4 info box; nothing is annualised here anyway.
  * any euro figure — `simulate_cost` is false, so §6.10 does not run.

The view-model also carries a `data_summary` key: the §2.3a "Your data at a glance" figures repeated
inside panel ③ but computed over the SELECTED window (spot price clamped to it too), rendered from
the shared _data_glance.html macro so it swaps with the panel on every range change.

Two presentation rules that are not cosmetic:

  * **Omit-don't-zero** (§2.4 "Panel ③ without PV"): the self-consumption row is omitted when
    there is no usable PV, because its denominator is PV and §6.11 says the metric is null there —
    never 0 and never 1, both of which would assert something the data cannot support.
  * **A negative saving is reported honestly** (§7.2 item 9). A no-PV battery under an energy-only
    objective can spend more kWh on round-trip losses and standby than its bands recover, and the
    spec is explicit that this is correct output. So the KPI tile carries the sign, `saved_pct`
    keeps it, and the breakdown row is relabelled "Extra grid import" rather than showing a
    negative number under a label reading "avoided".

**Self-sufficiency is display-clamped to `max(0, ·)` on BOTH sides** (§2.3a). The metric can go
negative when import exceeds the reconstructed load — the battery ending the window more charged
than it started, or round-trip losses — and a negative percentage reads as broken. The clamp is
presentation only; `app/domain/metrics.py` returns the unclamped value, and a caveat fires here
whenever the clamp actually bites.

**The self-sufficiency tile compares run A against run C, never the meter against run C** (§7.1).
Both halves come from `EnergyMetrics`. The measured figure `1 − rec.imp_total/rec.load_total` is a
different information set: the meter's import exceeds run A's simulated import by the energy that
reversed direction inside a grid interval, which the reconstruction nets out and no simulated
battery can recover. §7.1 is explicit — "Using observed import as the denominator while computing
the battery case from reconstructed data would mix two information sets and produce a number that
is wrong in a direction nobody can reason about" — and the bias is one-sided and flattering. The
measured import keeps its place in the data-glance band, which is labelled as the meter's, and a
caveat states the kWh difference so the two numbers on the panel are legible rather than
contradictory (§7.1: "Report the observed import alongside it, with the difference labelled as
resolution loss").

**Self-consumption is measured over the PV series' OWN coverage on both sides** (§2.3a: "comparing
six months of production against two years of export would be meaningless"). `frame.pv` is
zero-filled outside PV coverage, so the whole-window figure silently widens the export window while
leaving the PV total unchanged. `_pv_coverage_mask` builds the mask once and hands it to
`energy_metrics`, so the two scenarios cannot end up on different windows.

Numbers are formatted here (thousands-separated kWh, integer percent) so the template stays dumb,
matching app/summary_view.py.

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
from app.domain.metrics import EnergyMetrics, energy_metrics
from app.domain.reconcile import (
    CLAMP_UNRELIABLE_FRAC,
    DIV_GUARD_EPS,
    _WINDOW_SLOTS,
    ReconciledGrid,
    reconcile_grid,
)
from app.domain.simconfig import SimulationConfig
from app.domain.simframe import simulation_frame
from app.domain.simulate import run_all
from app.data_view import _fmt_res
from app.sample_data import _N
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
    """kWh total → "1,234 kWh" (thousands-separated, rounded to whole kWh, matching summary_view).

    Every caller passes a non-negative quantity, so the sign is not expected to appear — but when
    it does it is rendered with U+2212 MINUS SIGN, matching `_fmt_signed_kwh` and `_fmt_signed_pct`.
    Python's `format` emits ASCII "-", which would put two different minus glyphs on one panel.
    """
    return f"{round(total):,} kWh".replace("-", "−")


def _fmt_pct(fraction: float) -> str:
    """A 0..1 fraction → an integer-percent string like "31%" (the sample's presentation)."""
    return f"{round(100 * fraction)}%"


def _fmt_signed_kwh(total: float) -> str:
    """A kWh figure that may be NEGATIVE → "1,234 kWh" / "−1,234 kWh" (U+2212, matching the app).

    Used for the saving, which §7.2 item 9 says may legitimately come out negative. `round()` is
    applied to the MAGNITUDE so a value between −0.5 and 0 prints "0 kWh" rather than "−0 kWh":
    a signed zero is a formatting artefact, not a measurement, and it reads as a bug.
    """
    whole = round(abs(total))
    sign = "−" if total < 0 and whole != 0 else ""
    return f"{sign}{whole:,} kWh"


def _fmt_signed_pct(pct: float) -> str:
    """A percentage that may be negative → "−34.2 %" / "+12.0 %" (one decimal, §2.4's tile).

    Explicitly signed, because the tile's delta line has to distinguish a saving from a cost and
    an unsigned "34.2 %" beside a negative saving would read as the opposite of the truth. Same
    minus-zero guard as `_fmt_signed_kwh`: a value rounding to 0.0 prints without a sign.
    """
    rounded = round(abs(pct), 1)
    if rounded == 0.0:
        return "0.0 %"
    return f"{'−' if pct < 0 else '+'}{rounded:.1f} %"


def _clamped_pct(fraction: float | None) -> tuple[str, bool]:
    """A §6.11 ratio → (integer-percent string, did-the-display-clamp-fire) per §2.3a.

    `max(0, ·)` is applied to the DISPLAYED value only; the caller raises a caveat when the second
    element is True. `None` (the metric is not computable) formats as "n/a" and does not count as
    a clamp — absence and a clamped negative are different statements.
    """
    if fraction is None:
        return "n/a", False
    if fraction < 0:
        return _fmt_pct(0.0), True
    return _fmt_pct(fraction), False


def _self_sufficiency(rec: ReconciledGrid) -> float:
    """1 − import/load over the window (§6.11), display-clamped to ≥ 0. 0 when load is ~0.

    Retained for the measured/battery-free figure; the simulated scenarios' self-sufficiency comes
    from `app/domain/metrics.py` (which returns it UNCLAMPED) and is clamped by `_clamped_pct`.
    """
    if rec.load_total <= DIV_GUARD_EPS:
        return 0.0
    return max(0.0, 1 - rec.imp_total / rec.load_total)


def _pv_coverage_mask(dataset: LoadedDataset, rec: ReconciledGrid) -> np.ndarray | None:
    """Boolean per grid interval: does the PV SERIES' own coverage span this interval? (§2.3a)

    Mirrors summary_view._add_solar's masking. PV may cover only part of the grid window (panels
    installed part-way through a longer meter history), and §2.3a is explicit that self-consumption
    must compare PV against export over the PV's own window — "comparing six months of production
    against two years of export would be meaningless". This is the mask that expresses that window,
    computed ONCE here and used for both the measured figure and the simulated ones (it is handed to
    `energy_metrics`), so the two cannot end up on different windows.

    Returns None when no PV slot is mapped or the PV frame has no coverage at all — the cases where
    there is no PV window to speak of. A None mask means "use the whole window", which is what a
    dataset with no PV needs and what a fully-covering PV series amounts to anyway.
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
    win_start = np.datetime64(rec.window[0].replace(tzinfo=None), "s")
    n = len(rec.pv)
    bucket_start = win_start + (np.arange(n) * rec.grid_s).astype("timedelta64[s]")
    ps = np.datetime64(pv_start.replace(tzinfo=None), "s")
    pe = np.datetime64(pv_end.replace(tzinfo=None), "s")
    return (bucket_start >= ps) & (bucket_start < pe)


def _pv_present(rec: ReconciledGrid, pv_mask: np.ndarray | None) -> bool:
    """Is there enough PV over its own coverage for the self-consumption row to mean anything?

    The omit-don't-zero gate for the self-consumption row (§2.4 "Panel ③ without PV"): False when no
    PV slot is mapped, when the PV frame has no coverage, or when its total over that coverage is
    below PV_PRESENT_FLOOR_KWH (a sensor mapped but not really reporting). §6.11 makes the metric
    null in all three cases, and both 0 and 1 would assert something the data cannot support.
    """
    if rec.pv is None or pv_mask is None:
        return False
    return float(rec.pv[pv_mask].sum()) >= PV_PRESENT_FLOOR_KWH


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
    """Build the panel-③ ENERGY SAVINGS view-model over `window` from a real run (specs §2.4).

    Shape-compatible with sample_data._panel_results() EXCEPT: no `benchmark` key (the §6.12 DP is
    Phase 5) and the "intervals battery full/empty" secondary row is omitted. Returns None when
    reconcile_grid returns None (no simulatable grid) — the caller then falls back to the empty
    state, exactly like data_summary_from.

    The battery figures come from runs A/B/C over a `SimulationFrame` under appendix-A defaults;
    see the module comment for why the config is not the user's yet, and for the sign, clamp and
    omit rules the presentation below obeys.

    `should_cancel` is deliberately not passed to `run_all`: there is no run-orchestration layer
    (§3.3/§5.3) to cancel from, and a hook nothing can trip would be dead weight. The run is
    ~0.1 s over a year of hourly data (measured, changelog 20260725), which is why this is
    computed inline per request rather than behind a cache.
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

    # ── Run the simulation (§6.9) and compute the §6.11 metrics ────────────────────────────────
    # simulation_frame re-runs reconcile_grid internally rather than taking `rec`. That is one
    # duplicated reconciliation per request (~4 ms on a year of hourly data, measured); the
    # alternative — a frame builder that accepts a pre-reconciled grid — would change a Phase-1
    # module's signature, which is out of scope here. Both paths run the SAME reconcile_grid over
    # the SAME window, so the band's numbers and the run's cannot disagree.
    frame = simulation_frame(dataset, window)
    cfg = SimulationConfig()  # appendix-A defaults; Phase 6 binds the panel-② form
    # The PV series' own coverage as a per-interval mask (§2.3a). Handed to `energy_metrics` so BOTH
    # scenarios' self-consumption is measured over that one window; see `_pv_coverage_mask`.
    pv_mask = _pv_coverage_mask(dataset, rec)
    pv_present = _pv_present(rec, pv_mask)
    metrics: EnergyMetrics | None = None
    if frame is not None and frame.intervals > 0:
        # `rec` and `frame` come from the same reconcile_grid over the same window, so `pv_mask`
        # (built against `rec`) indexes `frame`'s arrays too — same length, same interval starts.
        metrics = energy_metrics(run_all(frame, cfg), frame, cfg, pv_mask=pv_mask)

    imp_str = _fmt_kwh(rec.imp_total)
    exp_str = _fmt_kwh(rec.exp_total)

    clamp_fired = False
    negative_saving = False

    if metrics is None:
        # Defensive: `reconcile_grid` succeeded, so `simulation_frame` should too (it returns None
        # on exactly the same condition). If it somehow did not, show the measured figures and no
        # invented battery numbers rather than raising on a page the user is looking at. This is
        # the ONE place the MEASURED self-sufficiency is shown as a tile value, and it is safe
        # precisely because there is no simulated figure beside it to be compared against.
        ss_str = _fmt_pct(_self_sufficiency(rec))
        kpis = [
            {"title": "GRID IMPORT SAVED", "value": "n/a", "unit": "kWh", "delta": ""},
            {"title": "SELF-SUFFICIENCY", "value": f"{ss_str} → n/a", "delta": ""},
            {"title": "EQUIVALENT FULL CYCLES", "value": "n/a", "delta": "", "extra": ""},
        ]
        energy_breakdown = [
            {"label": "Grid import, no battery", "value": imp_str},
        ]
        secondary = [{"label": "Grid export", "value": exp_str}]
    else:
        # ── KPI tiles (§2.4) ───────────────────────────────────────────────────────────────────
        # The saving is SIGNED throughout: §7.2 item 9 makes a negative saving a legitimate result
        # (an energy-only run of a no-PV battery pays round-trip losses and standby for a price
        # spread it does not price), so nothing here may assume it is positive.
        negative_saving = metrics.saved_kwh < 0
        saved_value = _fmt_signed_kwh(metrics.saved_kwh).removesuffix(" kWh")
        saved_delta = (
            _fmt_signed_pct(metrics.saved_pct) if metrics.saved_pct is not None else "n/a"
        )

        # Self-sufficiency: BOTH halves from the run (§7.1). The baseline is run A's simulated
        # figure, NOT the measured `1 − rec.imp_total/rec.load_total`, because the arrow is a
        # COMPARISON and §7.1 requires both scenarios to see the same information set: "Using
        # observed import as the denominator while computing the battery case from reconstructed
        # data would mix two information sets and produce a number that is wrong in a direction
        # nobody can reason about." The measured import is higher than run A's by the §7.1
        # resolution loss (within-interval import/export overlap the hourly grid nets out), so a
        # measured left half made the arrow systematically flattering — on the real dataset it
        # showed +12 pp where like-for-like is +10 pp. The measured figures keep their place in
        # the data-glance band above, which is separately labelled as measured.
        #
        # Both halves are display-clamped to ≥ 0 (§2.3a) and the delta is in percentage POINTS,
        # computed on the clamped values so it agrees with the two numbers shown beside it.
        ss_base_str, ss_base_clamped = _clamped_pct(metrics.self_sufficiency_baseline)
        ss_batt_str, ss_batt_clamped = _clamped_pct(metrics.self_sufficiency_battery)
        clamp_fired = ss_base_clamped or ss_batt_clamped
        # Both sides are None together (§6.11's symmetric null guard: a household with ~no load is
        # not self-sufficient in either scenario), so the delta is omitted rather than computed
        # against an invented zero.
        if (metrics.self_sufficiency_baseline is None
                or metrics.self_sufficiency_battery is None):
            ss_delta = ""
        else:
            ss_base_frac = max(0.0, metrics.self_sufficiency_baseline)
            ss_batt_frac = max(0.0, metrics.self_sufficiency_battery)
            ss_delta_pp = round(100 * ss_batt_frac) - round(100 * ss_base_frac)
            ss_delta = f"{ss_delta_pp:+d} pp"
        kpis = [
            {"title": "GRID IMPORT SAVED", "value": saved_value, "unit": "kWh",
             "delta": saved_delta},
            {"title": "SELF-SUFFICIENCY",
             "value": f"{ss_base_str} → {ss_batt_str}",
             "delta": ss_delta},
            {"title": "EQUIVALENT FULL CYCLES",
             "value": f"{metrics.efc:,.0f}" if metrics.efc is not None else "n/a",
             "delta": (f"{metrics.cycles_per_day:.2f} / day"
                       if metrics.cycles_per_day is not None else ""),
             "extra": f"{_fmt_kwh(metrics.throughput_kwh)} throughput"},
        ]

        # ── "Where the energy comes from" breakdown (§2.4) ─────────────────────────────────────
        # The "no battery" figure is run A's SIMULATED import, not the meter's — it is the
        # denominator `saved_pct` uses and the number the row below it is a difference of, so
        # showing the measured import here would leave the subtraction visibly not adding up.
        # (The measured import is stated in the data-glance band above, labelled as measured.)
        #
        # The third row's LABEL follows the sign (§7.2 item 9): "avoided" is a claim, and printing
        # a negative number under it would state the opposite of what happened.
        #
        # `_N` so `pybabel extract -k _N` finds "Extra grid import". Every other breakdown label
        # reaches the catalog via app/sample_data.py's parallel copy, but this one has no sample
        # counterpart — the sample shows a positive saving — so without the tag a Dutch user on the
        # negative-saving path got one English row among translated peers.
        avoided_label = _N("Extra grid import") if negative_saving else "Grid import avoided"
        energy_breakdown = [
            {"label": "Grid import, no battery",
             "value": _fmt_kwh(metrics.baseline_import_kwh)},
            {"label": "Grid import, with battery",
             "value": _fmt_kwh(metrics.battery_import_kwh)},
            {"label": avoided_label,
             "value": _fmt_kwh(abs(metrics.saved_kwh)), "rule_above": True},
            {"label": "Charged into the battery",
             "value": _fmt_kwh(metrics.charge_ac_kwh), "gap_above": True},
            {"label": "Discharged from the battery",
             "value": _fmt_kwh(metrics.discharge_ac_kwh)},
            {"label": "Conversion losses", "value": _fmt_kwh(metrics.conversion_loss_kwh)},
            {"label": "Standby consumption", "value": _fmt_kwh(metrics.standby_kwh)},
        ]

        # ── Secondary metrics (§2.4) ───────────────────────────────────────────────────────────
        # Self-consumption is omitted without usable PV (omit-don't-zero): §6.11 makes it null
        # there, and the row's whole content would be an assertion the data cannot support.
        #
        # BOTH halves come from the run, over the PV series' OWN coverage window (`pv_mask`, passed
        # into `energy_metrics` above). §2.3a is the authority and it is a statement about the
        # metric, not about one copy of it: "comparing six months of production against two years
        # of export would be meaningless". It was previously true of the baseline half only, while
        # the battery half spanned the whole window against a PV array zero-filled outside its
        # coverage — so on the real dataset (162 days of PV in a 365-day window) roughly two points
        # of the apparent 34% → 60% jump were purely the window changing under the reader.
        secondary = []
        if (pv_present
                and metrics.self_consumption_baseline is not None
                and metrics.self_consumption_battery is not None):
            sc_base, _ = _clamped_pct(metrics.self_consumption_baseline)
            sc_batt, _ = _clamped_pct(metrics.self_consumption_battery)
            secondary.append({"label": "Self-consumption ratio", "value": f"{sc_base} → {sc_batt}"})
        secondary.append({
            "label": "Grid export",
            "value": f"{_fmt_kwh(metrics.baseline_export_kwh)} → "
                     f"{_fmt_kwh(metrics.battery_export_kwh)}",
        })
        # "Intervals battery was full / empty" omitted — needs a SoC-bound comparison the metrics
        # layer does not compute yet; omitted rather than guessed.

    # ── Caveats (§2.4). Plain English strings; the template wraps them in _() and a later phase
    # extracts them to the catalog. Order: reconstruction reliability, price granularity, then the
    # run-specific notes (negative saving, SoC drift, self-sufficiency clamp), then the standing
    # note that the battery parameters are defaults rather than the user's.
    caveats: list[str] = []
    if rec.clamped_frac > CLAMP_UNRELIABLE_FRAC:
        caveats.append(
            f"Reconstructed household load was negative in a large share of intervals and clamped "
            f"to zero ({_fmt_kwh(rec.clamped_kwh)} discarded against {exp_str} exported). This "
            f"usually means solar export the PV sensor did not report, or an unmapped battery — "
            f"so the load and self-sufficiency figures here are unreliable."
        )
    if metrics is not None:
        # §7.1's own instruction: "Report the observed import alongside it, with the difference
        # labelled as resolution loss." The band above shows the METER's import; the Energy savings
        # section below shows run A's SIMULATED no-battery import, which is smaller by the energy
        # that flowed both ways inside a single interval — the reconstructed load nets that out and
        # no simulated battery can recover it. Two grid-import numbers on one panel read as a
        # contradiction unless the difference is named, so it is named here in kWh.
        #
        # Raised only when the gap rounds to at least 1 kWh: below that the two figures print
        # identically and a caveat explaining a difference the reader cannot see would be noise.
        resolution_loss = rec.imp_total - metrics.baseline_import_kwh
        if round(resolution_loss) >= 1:
            caveats.append(
                f"Your meter recorded {imp_str} imported over this period; the simulation's "
                f"no-battery baseline is {_fmt_kwh(metrics.baseline_import_kwh)}. The difference "
                f"of {_fmt_kwh(resolution_loss)} is energy that flowed both into and out of your "
                f"house within a single {res_label} interval, which data at this resolution cannot "
                f"see. Everything under Energy savings is computed from the simulated baseline, so "
                f"that the battery and no-battery cases are built from the same information; the "
                f"figures above it are as your meter recorded them. That is why the two sets of "
                f"numbers do not match exactly."
            )
    price_lost = normalize.price_granularity_lost(dataset.frames, rec.grid_s)
    if price_lost["lost"]:
        native = _fmt_res(price_lost["native_resolution_s"])
        caveats.append(
            f"Spot prices are recorded every {native} but the run is {res_label}, so the battery "
            f"acted on an averaged price and could not chase within-interval swings."
        )
    if negative_saving and metrics is not None:
        # §7.2 items 9 and 10. Without PV the battery's value is in the price SPREAD — a euro
        # quantity — so an energy-only run measures the cost of moving the energy and none of the
        # benefit. Say that plainly rather than presenting a negative kWh figure as a verdict.
        caveats.append(
            f"This battery imported {_fmt_kwh(abs(metrics.saved_kwh))} MORE from the grid than "
            f"the same household without one. That is a real result, not an error: round-trip "
            f"losses and standby cost energy, and the value of charging cheaply and discharging "
            f"when prices are high is a price spread — a euro quantity this energy-only run does "
            f"not compute. An energy-only run cannot tell you whether the battery is worth buying."
        )
    if metrics is not None and metrics.soc_drift_significant:
        # §6.11's SoC drift correction. Without a cost model there is no median import price, so
        # the euro valuation (`soc_delta_value_eur`) is null and is not shown — only the kWh.
        direction = "more" if metrics.soc_delta_kwh > 0 else "less"
        caveats.append(
            f"The battery ended the period {_fmt_kwh(abs(metrics.soc_delta_kwh))} {direction} "
            f"charged than it started. That residual energy is not part of the saving above and "
            f"is large relative to it, so the headline figure would move if the period ended at a "
            f"different state of charge."
        )
    if clamp_fired:
        # §2.3a's display clamp, on EITHER half of the tile. Only the presentation is clamped; the
        # metric itself is negative. Worded to cover both sides rather than naming the battery one:
        # the baseline half is now run A's simulated figure and can clamp too (the same round-trip
        # and drift mechanics apply to a household with an EXISTING battery in the reconstruction).
        caveats.append(
            "Self-sufficiency came out below zero and is shown as zero. Grid "
            "import exceeded the reconstructed household load over this period — the battery ended more "
            "charged than it started, or round-trip losses consumed imported energy. It evens out "
            "over full charge/discharge cycles; select a longer period to see it."
        )
    # Standing note until Phase 6 binds panel ② to a config object: the battery above is the
    # appendix-A default, not the user's. Stated rather than hidden — a figure computed from an
    # unstated parameter set is the kind of number that propagates unchallenged.
    #
    # **No literal "%" in any caveat string.** The template renders these through `_()`, and the
    # Jinja i18n extension is installed with `newstyle=True`, which applies %-formatting to the
    # translated result: "90% round-trip" comes out as "90{}ound-trip" because "% r" is read as a
    # conversion specifier. Escaping it as "%%" would work but pushes the escape onto every
    # translator of every catalog, so the caveats are worded without the sign instead — hence
    # "0.90 round-trip" below rather than "90% round-trip". (The KPI tiles and breakdown rows are
    # unaffected: they are values, rendered without `_()`.)
    caveats.append(
        f"These figures are for a default battery — {cfg.battery.usable_capacity_kwh:g} kWh usable, "
        f"{cfg.battery.max_charge_kw:g}/{cfg.battery.max_discharge_kw:g} kW, "
        f"{cfg.battery.roundtrip_efficiency:.2f} round-trip efficiency, "
        f"charge {cfg.policy.charge_policy.value} / discharge {cfg.policy.discharge_policy.value} — "
        f"because the parameters panel is not wired up yet. They are not yet based on a battery "
        f"you chose."
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
