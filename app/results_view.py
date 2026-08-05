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

**The configuration is the USER'S, threaded in by the caller.** `results_from` takes a
`SimulationConfig` and no longer constructs one: panel ② is wired now (app/params_view.py,
app/simconfig_store.py), and every route that renders panel ③ passes the same persisted config, so
a parameter change moves these figures. `cfg=None` falls back to `SimulationConfig()` — the
appendix-A defaults — which is the state a workspace is in before anything has been configured and
which keeps every existing caller and test valid.

Panel ③ also now carries §2.4's **"Benchmark: grid import avoided"** box, from the §6.12
perfect-foresight DP (`app/domain/benchmark.py`, run D). The `benchmark` key the template has been
guarding on is emitted, with the wireframe's rows and the capture-ratio gloss.

**The DP is LAZY.** It is ~4.6 s against ~0.12 s for everything else, so `results_from` runs it
only under `with_benchmark=True`, which only `POST /results/benchmark` passes. `GET /` and
`POST /results` paint panel ③ without it and the box fills in afterwards. Nothing is cached.

`_benchmark_block` does NOT print the capture ratio unconditionally: §6.12's terminal constraint is
asymmetric with the policy run, so a policy that liquidates its opening charge can produce a ratio
no percentage can mean. See that function for the four shapes and why the fix belongs in the view.

Panel ③ now also carries §2.4's **COST SAVINGS section**, under `cfg.simulate_cost`. The euro
pipeline sits alongside the energy one and never inside it:

    price_curves     →  §6.5's per-interval EUR/kWh arrays for this window
    compute_costs    →  runs A and C billed under §6.10 (a MARGINAL bill — fixed costs excluded)
    waterfall        →  §6.10's eight-line decomposition of the difference
    (here)           →  the MONEY SAVED tile, the money benchmark box, "Where the money comes
                        from", the monthly euro series, the §6.16 uncertainty width (reported as
                        a caveat — D5′ — beside the price-granularity one), and the euro caveats

**`cost` is emitted or it is absent — never an object of null fields** (§4.5, which singles out
"a `waterfall` array of eight null-valued entries, which would invite a template to render eight
empty rows"). Same convention for `cost_benchmark` and `monthly_saved_eur`, and the template
branches the whole section on the one key.

**Fixture 18 is the constraint the cost path is written under**: every energy figure must be
bit-identical with cost simulation on and off, down to the per-interval SoC trace. That holds
structurally rather than by care — the cost functions are pure functions of the flows, they are
called after `run_all` and feed nothing back into it, and `economic_guard` (the one cost term
that could reach the dispatch path) is forced off by `SimulationConfig` itself when
`simulate_cost` is false.

**The euro capture ratio has THREE shapes, not the energy box's four.** §6.12's drift correction
is exact in kWh and has no sound euro analogue (follow-up H10, and `CostBenchmark`'s docstring),
so the money box does not restate a drift-funded ratio on a corrected basis — it says the
comparison is unavailable on that basis. That case is COMMON, not exceptional: 48 of 144 swept
configurations produce a euro ratio above 1, all in the liquidating half. See
`_cost_benchmark_block`.

What is NOT emitted this increment (later phases):
  * the "intervals battery was full / empty" secondary row — it needs a SoC-bound comparison the
    metrics layer does not own yet; omitted rather than guessed.
  * annualisation — a short-window run (< min_annualisation_days) sets `annualisation_disabled`
    with a message so the template can show the §2.4 info box; nothing is annualised here anyway.
  * §6.13's euro-basis resolution bias — a cost-only §4.5 field with no domain-layer
    implementation to render.

**§6.16's pricing-uncertainty width is computed here** (`_price_bracket`, `PriceBracket`). It is
one dispatch billed three times — at the grid interval's cheapest native price, at its dearest,
and at the mean — which bounds how far the saving could be off given that hourly energy data
cannot say when inside an hour the energy moved. It is a top-level `price_bracket` key, NOT a
`cost.price_bracket` block: the decision (changelog D5′) was to report only the WIDTH as a
caveat, so §4.5's `cost` object is untouched and no figure already on screen moves. `None` when
the supplier bills the hourly mean (D10 — the hourly price is then what the household paid) or
when no interval carries a spread. The caveat that prints it (in `_caveats`' section below) is
scoped to the SAVING figure and to nothing else on the page: all three evaluations are
differences of two bills, so the width bounds the difference, while each individual bill — which
the KPI sentence and the waterfall also show — moves by MORE than the stated width.

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

That divergence is surfaced in THREE places, because it produces two pairs of figures a reader can
compare and each pair needs its own explanation where it is met:

  * the kWh caveat above, and the SAME message on an ⓘ beside the "Grid import, no battery"
    breakdown row (one msgid, built once — the caveat states it unprompted, the ⓘ puts it at the
    figure);
  * a second caveat stating the same divergence in PERCENTAGES — the household card's measured
    self-sufficiency against this panel's simulated baseline — which is the pair a reader actually
    compares and which the kWh caveat never names. Gated on the two rounding differently;
  * an ⓘ on the self-sufficiency tile itself, explaining what its left half is.

All three ⓘ use the shared `.slot-info-btn` / `#slot-info-dialog` affordance (one delegated handler
in `ha_fetch.js`), so they survive the panel's fragment swaps.

**Self-consumption is measured over the PV series' OWN coverage on both sides** (§2.3a: "comparing
six months of production against two years of export would be meaningless"). `frame.pv` is
zero-filled outside PV coverage, so the whole-window figure silently widens the export window while
leaving the PV total unchanged. `_pv_coverage_mask` builds the mask once and hands it to
`energy_metrics`, so the two scenarios cannot end up on different windows.

Numbers are formatted here (thousands-separated kWh, integer percent) so the template stays dumb,
matching app/summary_view.py.

Every user-facing SENTENCE, by contrast, is emitted as a `(msgid, params)` pair rather than as a
formatted string — `_msg` / `_msg_n`, imported from `app/i18n.py` and rendered by
`templates/_msg.html`. They used to be defined here; they moved to `i18n` when `data_view` needed
them too, since this module already imports from `data_view` and the reverse import would cycle.

`results_from` returns None when the reconcile helper returns None (no simulatable grid) — the caller
falls back to the empty state, exactly like data_summary_from.

Also here (Deliverable C): `resolve_window` turns a request (a preset period, or an explicit
start/end range) into a concrete UTC window against the dataset's coverage, anchored to the END of
data coverage (§7.4), clamped to coverage, never padding with zeros.

**Sentences are `(msgid, params)` pairs and figures are `i18n.num()` pairs** — neither is turned
into text here. A sentence assembled with an f-string is a msgid no `pybabel extract` run can see;
a figure formatted with `f"{x:,.0f}"` is formatted before the request's locale is known, and Dutch
writes 3.924 kWh and 0,094 €/kWh where English writes 3,924 kWh and 0.094 €/kWh. Both are resolved
by `templates/_msg.html` at render time, which is the only place the locale exists. The `_fmt_*`
helpers below therefore return figures rather than strings, and `_arrow` exists because an
"A → B" comparison is two figures and so cannot be joined into one string either.

Main items:
    PERIOD_DAYS               preset name → span in days (§7.4 predefined ranges).
    min_annualisation_days    below this a window is too short to annualise (specs appendix-a, §7.4).
    resolve_window(dataset, *, period, start, end) -> (start, end)   the window resolver.
    results_from(dataset, window) -> dict | None   the panel-③ view-model, or None.
    _cost_block / _cost_benchmark_block / _monthly_saved_eur   the §2.4 COST SAVINGS section.
    WATERFALL_DISPLAY_EPS_EUR  below this a waterfall line is dropped from the DISPLAY only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from app.dataset import LoadedDataset
from app.domain import normalize
from app.domain.benchmark import (
    CostBenchmark,
    EnergyBenchmark,
    _capture_ratio,
    cost_benchmark,
    energy_benchmark,
)
from app.domain.costs import WATERFALL_LINES, CostResult, compute_costs, waterfall
from app.domain.pricing import price_curves
from app.domain.metrics import SOC_DRIFT_WARN_FRAC, EnergyMetrics, energy_metrics
from app.domain.reconcile import (
    CLAMP_UNRELIABLE_FRAC,
    DIV_GUARD_EPS,
    _WINDOW_SLOTS,
    ReconciledGrid,
    reconcile_grid,
)
from app.domain.simconfig import SimulationConfig, SupplierSettlement
from app.domain.simframe import simulation_frame
from app.domain.simulate import run_all
from app.data_view import _fmt_res, _res_msg
from app.i18n import format_num, msg as _msg, msg_n as _msg_n, num
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

# §2.4: the "…if export allowed" benchmark row renders only when the unconstrained fields are
# non-null AND the two capture ratios differ by more than this. Appendix A's
# `benchmark_divergence_display_threshold`, default 0.02 and flagged there as **provisional** — an
# untested guess that experiment X10 is meant to revisit once real runs show how far the two bounds
# usually sit apart. A PRESENTATION constant: it changes no computed number, only whether a
# near-duplicate line that "says nothing" (§2.4) is shown, which is why it lives here rather than on
# SimulationConfig beside dp_soc_levels.
benchmark_divergence_display_threshold = 0.02

# Preset periods, anchored to the END of data coverage (§7.4 — NOT now()). Span in days each preset
# reaches back from the coverage end. The names are the request tokens; the wireframe's human labels
# ("1 week", …) are hardcoded in _panel_results.html beside the tokens, so the view-model emits
# only `period_selected` (which of them to highlight).
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

# The label the selector highlights when the window came from an EXPLICIT RANGE rather than a
# preset. It is not a span: no number of days makes a range "custom", which is exactly why the
# caller has to say so (`results_from(..., custom_range=True)`) instead of it being inferred here.
# The selector uses it to highlight its "custom" button and to reveal the date fields; without it
# an applied range snapped to whichever preset happened to be nearest in length, and the picker the
# user had just used disappeared behind a highlighted preset they had not chosen.
PERIOD_SELECTED_CUSTOM = "custom"

# The label the selector highlights, keyed off the preset the window was resolved from. Kept as the
# wireframe default ("1 year") for the full-coverage case.
_PERIOD_SELECTED_BY_NAME: dict[str, str] = {
    "last_1_week": "1 week",
    "last_30_days": "1 month",
    "last_3_months": "3 months",
    "last_6_months": "6 months",
    "last_1_year": "1 year",
}

# The shape-4 benchmark gloss (see `_benchmark_block`), shared by the "ratio above the bound with
# no drift to explain it" and "drift-corrected ratio is itself out of range" paths. A module
# constant so both paths reference ONE literal and `pybabel extract` sees one msgid. `_N` because
# a module-level assignment is not a call the extractor recognises — every other msgid in this file
# reaches the catalog through `_msg`/`_msg_n`, which are extraction keywords; this one needs its
# own marker.
_FAULT_GLOSS = _N(
    "The comparison against a perfectly-informed battery did not come out usable over this "
    "period: your policy appears to have avoided more grid import than the best possible "
    "dispatch, which cannot happen and means the two figures are not comparable here. No "
    "capture ratio is shown. Selecting a longer period usually resolves it."
)

# The monthly chart's x-axis labels used to be a table of English month abbreviations here. They
# are gone: `_monthly_import` now emits month NUMBERS and the template's locale-bound `monthname`
# filter (app/i18n.month_abbr) renders them, so a Dutch axis reads "jan feb mrt" rather than
# "Jan Feb Mar". Babel's CLDR data owns the abbreviations for every locale, which is one fewer
# table to translate and one fewer to keep in step with a new language.


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


def _g(value) -> dict:
    """A config value for a caveat sentence: a figure at its OWN natural precision (`%g`-style).

    The precision was decided by whoever typed the value into panel ②, so this kind keeps it
    (`i18n._NUM_KINDS["general"]`) rather than imposing a digit count — "10 kWh usable, 0.95
    round-trip" reads as the user set it. Under A6 it emits a figure rather than a string, so a
    Dutch reader sees "0,95 round-trip".

    Only VALID configs are persisted, so in practice these are always numbers. But
    `SimulationConfig` is constructible from anything (its construction never raises, by design),
    and a caller may hand this function a config that has not been validated. `i18n.format_num`
    keeps the old defensiveness for that case — a non-number renders as itself and a None as "—",
    rather than raising on a page the user is looking at.
    """
    return num(value, "general")


def _policy_key(value) -> str:
    """A policy enum's short key ("P3"), or the raw stored value. Same defensiveness as `_g`."""
    return value.value if hasattr(value, "value") else str(value)


# ── Figures (A6: locale-aware, formatted at RENDER time) ─────────────────────────────────────
#
# These returned finished strings ("1,234 kWh") built while this module ran, which is before the
# request's locale is known — so a Dutch page showed English separators (Dutch writes 1.234 kWh,
# 0,094 €/kWh, +15,9 %). They now return `i18n.num()` dicts: the NUMBER plus the name of a
# convention, formatted by `templates/_msg.html`'s locale-bound `numfmt` filter at render time.
# The convention table is `i18n._NUM_KINDS`, shared with `summary_view`, so "how the app writes a
# kWh figure" — including the U+2212 minus and the minus-zero guard these functions used to own
# individually — has one definition rather than four.
#
# The unit suffixes ("kWh", "%") stay literal in that table and out of the catalogs: they are
# written identically in Dutch, and routing a symbol through gettext invites a translator to
# change one of the two places it appears.


def _fmt_kwh(total: float) -> dict:
    """kWh total → a number rendered as "1,234 kWh" / "1.234 kWh" in the render locale."""
    return num(total, "kwh")


def _fmt_pct(fraction: float) -> dict:
    """A 0..1 fraction → a number rendered as an integer percent ("31%")."""
    return num(fraction, "pct")


def _fmt_signed_kwh(total: float) -> dict:
    """A kWh figure that may be NEGATIVE → a number rendered "1,234 kWh" / "−1,234 kWh" (U+2212).

    Used for the saving, which §7.2 item 9 says may legitimately come out negative. The minus-zero
    guard (a value between −0.5 and 0 prints "0 kWh", not "−0 kWh" — a signed zero is a formatting
    artefact, not a measurement) now lives in `i18n.format_num`'s signed branch.
    """
    return num(total, "kwh_signed")


def _fmt_signed_pct(pct: float) -> dict:
    """A percentage that may be negative → a number rendered "−34.2 %" / "+12.0 %" (§2.4's tile).

    Explicitly signed, because the tile's delta line has to distinguish a saving from a cost and
    an unsigned "34.2 %" beside a negative saving would read as the opposite of the truth.
    """
    return num(pct, "pct_signed")


def _clamped_pct(fraction: float | None) -> tuple[dict | str, bool]:
    """A §6.11 ratio → (a percent figure, did-the-display-clamp-fire) per §2.3a.

    `max(0, ·)` is applied to the DISPLAYED value only; the caller raises a caveat when the second
    element is True. `None` (the metric is not computable) gives the literal "n/a" and does not
    count as a clamp — absence and a clamped negative are different statements. "n/a" stays a
    string rather than becoming a figure because it is not one; it is the same abbreviation in
    Dutch, so it needs neither formatting nor a msgid.
    """
    if fraction is None:
        return "n/a", False
    if fraction < 0:
        return _fmt_pct(0.0), True
    return _fmt_pct(fraction), False


def _arrow(before, after) -> dict:
    """A "before → after" comparison, as a message pair whose halves are formatted at render time.

    §2.4's self-sufficiency tile, the self-consumption row and the grid-export row all state a
    change as `A → B`. Each half is a figure, so under A6 neither can be turned into text here —
    which means the pair cannot be joined with an f-string either. Making the whole thing a
    `_msg` pair with the arrow in the msgid lets the two halves be formatted in the render locale
    (`templates/_msg.html` renders a param that is itself a figure) and, incidentally, lets a
    translator move the arrow if some language wants it elsewhere.

    Either half may also be the literal "n/a" (`_clamped_pct`), which passes through as a string.
    """
    return _msg("%(before)s → %(after)s", before=before, after=after)


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


def _drift_is_material(bench: EnergyBenchmark) -> bool:
    """Is the POLICY run's SoC drift materially NEGATIVE — i.e. did it fund part of its saving?

    The gate on the capture ratio's presentation (see `_benchmark_block`). Two conditions:

      * **The drift is negative.** Only a battery that ended MORE EMPTY than it started can have
        booked import-avoidance it did not pay to store. A POSITIVE drift makes the policy look
        WORSE than it was (energy it bought and still holds is counted as consumed), which needs no
        intervention: the ratio is then conservative, and understating a policy is not the failure
        mode this guards.
      * **It is large relative to the saving**, by §6.11's OWN threshold. `SOC_DRIFT_WARN_FRAC` (2%)
        is reused rather than a second constant being invented: §6.11 already defines it as the
        point at which residual SoC is large enough to matter to the headline figure, and a ratio
        built on that headline figure inherits exactly the same question. Using one threshold also
        means the box's drift-corrected wording and the panel's SoC-drift caveat fire together,
        rather than the reader seeing one without the other.

    The degenerate branch matches `metrics.soc_drift_significant`'s: with no saving to be relative
    to, any drift above `DIV_GUARD_EPS` counts, because there is nothing for it to be small against.
    """
    delta = bench.policy_soc_delta_kwh
    if delta >= 0:
        return False
    base = abs(bench.policy_saved_kwh)
    if base > DIV_GUARD_EPS:
        return abs(delta) > SOC_DRIFT_WARN_FRAC * base
    return abs(delta) > DIV_GUARD_EPS


def _benchmark_block(bench: EnergyBenchmark, eta_d: float) -> dict:
    """§2.4's "Benchmark: grid import avoided" box, from the §6.12 energy block.

    Four rows in the wireframe's order — No battery, Your policy, Perfect foresight, and the
    conditional "…if export allowed" — plus the capture-ratio gloss beneath them.

    ## The capture ratio is NOT printed unconditionally, and that is the point of most of this

    `EnergyBenchmark.capture_ratio` is deliberately unclamped — its docstring says a value > 1 is a
    detectable fault and a clamp would turn it into a plausible number. That is right for a test
    consumer. It is wrong for a page: printing it raw produced "captures −493 percent" on a
    reproducible configuration, and, in the `None` case, a gloss reading "even a perfectly-informed
    battery could not have avoided any grid import" directly above a visible row reading "Your
    policy 9 kWh". So the metric keeps its honesty and the FIX is here, in the view.

    The mechanism is §6.12's terminal constraint being **asymmetric with the policy run**: the DP
    must end at or above its starting SoC, the policy run need not, and §6.11 deliberately does not
    net the drift out. A policy that liquidates its opening charge therefore books a saving the DP
    is forbidden to book, and the ratio divides a drift-FUNDED numerator by a drift-NEUTRAL
    denominator. The spec does not address this; it is recorded as a spec finding in the phase-5
    changelog.

    **The resolution: restate the ratio on drift-corrected figures rather than suppress it.** The
    correction is `saved + soc_delta × eta_d` — the residual SoC valued at what the inverter could
    still have delivered — which is the same basis `tests/test_benchmark._saving_drift_corrected`
    already asserts fixture 6 on, so the box and the test agree on what a comparable saving is.

    **Why this does not violate §6.11's "report drift rather than net it out".** §6.11's rule
    governs the drift METRIC, and that metric is untouched: `metrics.soc_delta_kwh` is reported in
    full and the panel's SoC-drift caveat states it in kWh, unnetted, beside this box. What is
    corrected here is a RATIO whose denominator is drift-constrained by §6.12's terminal
    constraint. Leaving the numerator uncorrected does not preserve information — it produces a
    quotient of two incompatible quantities, which is not a measurement of anything. The box says
    in words that the figure is drift-corrected, so nothing is netted out silently.

    Four shapes, each with its own gloss:

      1. **normal** — drift immaterial and `0 ≤ ratio ≤ 1`. Renders as a plain percentage.
      2. **drift-funded** — `_drift_is_material`. Renders the DRIFT-CORRECTED ratio, labelled as
         such, with a sentence naming the opening charge. Falls through to shape 4 if the
         corrected ratio is itself out of range.
      3. **bound ≈ 0** (`capture_ratio is None`). The gloss BRANCHES on the policy saving: the old
         "could not have avoided any grid import" wording is true only when the policy saved ~0
         too. With a visible positive policy row it contradicts the page, so the box instead says
         the policy's apparent saving is not one a perfectly-informed battery could reproduce under
         the terminal constraint.
      4. **ratio > 1 with no drift to explain it** — a fault (fixture 6 says the bound cannot be
         beaten). No number is stated; the box says the comparison did not come out usable over
         this period. Presenting a fault as a result is the one thing the box must not do.

    The ROWS are unaffected in all four shapes. They are honest figures — §7.2 item 9 makes a
    negative saving a legitimate result and the drift caveat explains it — and the defect was never
    the bars.

    **`frac` is the bar fill relative to the WIDEST baseline shown**, not to the perfect-foresight
    bound. The bars are a visual comparison of the rows against each other, so they have to share
    one scale; scaling to the inheriting bound would push a larger unconstrained row past the end of
    its track. The "No battery" row is 0 by definition (§2.4 prints "0 kWh"), which anchors the
    left end.

    **A negative saving is floored to 0 for the BAR only.** §7.2 item 9 makes a negative saving a
    legitimate result, and the row's VALUE carries the sign — but a bar cannot render a negative
    width, and a bar clipped to zero beside a signed number is legible where a negative width is
    not. Nothing here changes the figure.

    **The conditional fourth row** (§2.4). It renders only when the unconstrained fields are
    non-null — i.e. `allow_grid_export` is off, so a second DP actually ran — AND the two capture
    ratios differ by more than `benchmark_divergence_display_threshold`. Otherwise it is omitted,
    because §2.4 is explicit that a near-duplicate line in a dense box "says nothing". Note that on
    the ENERGY objective the two dispatches usually coincide exactly even with export off:
    exporting battery energy earns revenue but avoids no grid import, so the export permission
    cannot change an import-minimising dispatch. The row is therefore expected to be rare here and
    to earn its keep on the §6.12 COST benchmark, where export does pay. That is the threshold
    behaving as designed, not the DP failing to find something.

    **The gloss is a `_msg` pair, not a string.** Every shape below returns a constant msgid plus
    its runtime values, so the sentence is extractable and translatable; `_benchmark_box.html`
    translates the msgid and substitutes afterwards. The one composed shape (the normal case with
    the export sentence appended) is a msgid of its own rather than two glued together — the two
    orderings are not interchangeable across languages.

    The gloss states the ratio in words ("captures 57 percent of") rather than with a "%" sign.
    That began as a workaround for the old `newstyle=True` %-formatting and is no longer required
    (`app/i18n.py` now installs with `newstyle=False`, so a literal "%" is inert), but the wording
    is kept: changing it would change the English text, which this restructuring must not do.
    """
    pf = bench.perfect_foresight_saved_kwh
    unc = bench.perfect_foresight_saved_kwh_unconstrained

    show_unconstrained = (
        unc is not None
        and bench.capture_ratio is not None
        and bench.capture_ratio_unconstrained is not None
        and abs(bench.capture_ratio - bench.capture_ratio_unconstrained)
        > benchmark_divergence_display_threshold
    )

    # The shared bar scale: the widest row actually shown. Guarded against a non-positive maximum
    # (every bound ~0 or negative), where every bar is simply empty rather than a division by zero.
    scale = max(bench.policy_saved_kwh, pf, unc if show_unconstrained else pf, 0.0)

    def frac(value: float) -> float:
        if scale <= DIV_GUARD_EPS:
            return 0.0
        return max(0.0, min(1.0, value / scale))

    rows = [
        {"label": "No battery", "value": _fmt_kwh(0.0), "frac": 0.0, "dot": False},
        {"label": "Your policy", "value": _fmt_signed_kwh(bench.policy_saved_kwh),
         "frac": frac(bench.policy_saved_kwh), "dot": True},
        {"label": "Perfect foresight", "value": _fmt_signed_kwh(pf),
         "frac": frac(pf), "dot": True},
    ]
    if show_unconstrained:
        assert unc is not None  # narrowed by show_unconstrained; restated for the type reader
        rows.append({"label": "…if export allowed", "value": _fmt_signed_kwh(unc),
                     "frac": frac(unc), "dot": True})

    # ── The gloss (§2.4) — see the docstring's four shapes ─────────────────────────────────────
    #
    # Each shape is ONE constant msgid. The §7.2-item-6 floor sentence used to be a `floor_note`
    # variable appended to two of them; it is now written out inside each, because a msgid assembled
    # from two fragments is not a sentence a translator can reorder, and gettext has no way to see
    # the join. Same reason the shape-4 wording, shared by two paths, is a module-level constant
    # rather than a local: one literal, referenced twice, is still one extractable msgid.
    #
    # The shape-4 wording states NO number: a capture above 100 percent contradicts fixture 6, so
    # whatever it is, it is not a result.
    fault_gloss = _msg(_FAULT_GLOSS)

    # Float slack on the "is the corrected ratio in range" test. The correction subtracts one
    # computed quantity from another and the two can agree to the last bit and still land at
    # 1.0000000000000024 — measured on the 20 kWh / 100→10 percent SoC reproduction, where the
    # corrected saving and the bound are the SAME number to 14 digits. Without the slack a ratio of
    # exactly 1 is reported as a fault, which is the opposite of the truth: a policy that matches
    # the bound is the best possible outcome, not a broken one. The tolerance is a display
    # tolerance on a rounding artefact, not a correctness allowance — a genuine breach of fixture 6
    # is orders of magnitude larger (the raw ratios reproduced were −4.93 and 28.59).
    RATIO_RANGE_EPS = 1e-6
    drift_funded = _drift_is_material(bench)
    # The drift-corrected pair. Only the NUMERATOR needs correcting: §6.12's terminal constraint
    # already holds the DP to a non-negative drift, so its saving is on the corrected basis
    # already. `× eta_d` because the residual is STORED energy and only that fraction of it would
    # ever have reached the AC bus, which is the side the saving is measured on.
    corrected_saved = bench.policy_saved_kwh + bench.policy_soc_delta_kwh * eta_d
    corrected_ratio = _capture_ratio(corrected_saved, pf)

    if bench.capture_ratio is None:
        # Shape 3: the bound is ~0. The old single wording asserted that nothing could have been
        # avoided, which is a claim about the DP — and it reads as a contradiction whenever the
        # "Your policy" row above shows a positive figure. Branch on the visible row.
        if abs(bench.policy_saved_kwh) <= DIV_GUARD_EPS:
            gloss = _msg(
                "Over this period even a perfectly-informed battery could not have avoided any "
                "grid import, so there is no capture ratio to report."
            )
        else:
            gloss = _msg(
                "The best possible dispatch over this period could not have avoided any grid "
                "import, yet your policy shows %(policy)s avoided. "
                "That figure is not something a perfectly-informed battery could reproduce: the "
                "benchmark must return the battery to the state of charge it started from, and "
                "your policy did not. There is no capture ratio to report for this period.",
                policy=_fmt_signed_kwh(bench.policy_saved_kwh),
            )
    elif drift_funded:
        # Shape 2: the saving is partly opening charge. State the corrected ratio, and say so.
        if corrected_ratio is None or not (
            -RATIO_RANGE_EPS <= corrected_ratio <= 1.0 + RATIO_RANGE_EPS
        ):
            gloss = fault_gloss
        else:
            gloss = _msg(
                "Your battery ended this period "
                "%(residual)s less charged than it started, so "
                "part of the grid import it avoided was paid for out of the charge it began with "
                "rather than earned by its dispatch. The benchmark is not allowed to do that — it "
                "must finish at the state of charge it started from — so the two are only "
                "comparable once that residual is accounted for. On that basis your policy "
                "captures %(pct)s percent of the grid import a "
                "perfectly-informed battery could have avoided. "
                "Perfect foresight knows every future price exactly and no real controller "
                "reaches it, so treat this as a floor on what a better policy could achieve, not "
                "as a target.",
                residual=_fmt_kwh(abs(bench.policy_soc_delta_kwh)),
                pct=num(round(100 * corrected_ratio), "count"),
            )
    elif bench.capture_ratio > 1.0 + RATIO_RANGE_EPS:
        # Shape 4: above the bound with no drift to explain it. Fixture 6 says this cannot happen.
        gloss = fault_gloss
    elif show_unconstrained and bench.capture_ratio_unconstrained is not None:
        # Shape 1 with the export sentence. A SEPARATE msgid rather than the plain shape-1 msgid
        # with a second one concatenated: gettext cannot see a join made in Python, and the two
        # sentences' order and phrasing are the translator's to decide as one unit.
        gloss = _msg(
            "Your policy captures %(pct)s percent of the grid import a "
            "perfectly-informed battery could have avoided. "
            "Perfect foresight knows every future price exactly and no real controller reaches "
            "it, so treat this as a floor on what a better policy could achieve, not as a "
            "target. Allowed to export, that ceiling rises to %(ceiling)s "
            "(a %(unc_pct)s percent capture) — the extra "
            "is arbitrage your export setting currently forbids.",
            pct=num(round(100 * bench.capture_ratio), "count"),
            ceiling=_fmt_kwh(unc),
            unc_pct=num(round(100 * bench.capture_ratio_unconstrained), "count"),
        )
    else:
        # Shape 1: the normal case. A NEGATIVE ratio reaches here only with an immaterial drift,
        # which means the policy genuinely spent energy (§7.2 item 9) against a positive bound —
        # a real result the negative-saving caveat already explains, and one the reader should see.
        gloss = _msg(
            "Your policy captures %(pct)s percent of the grid import a "
            "perfectly-informed battery could have avoided. "
            "Perfect foresight knows every future price exactly and no real controller reaches "
            "it, so treat this as a floor on what a better policy could achieve, not as a target.",
            pct=num(round(100 * bench.capture_ratio), "count"),
        )

    return {"rows": rows, "gloss": gloss}


def _monthly_import(rec: ReconciledGrid) -> dict:
    """Monthly Σ grid-import over the window for the chart, as {"months": [...], "values": [...]}.

    A real series (not sample data): each grid interval's import is bucketed by the calendar month
    its start falls in, summed, and rounded to whole kWh. Months are in chronological order across
    the window. This stays in scope (no simulation needed) while being an honest, dataset-derived
    monthly breakdown of measured grid import.

    `months` carries MONTH NUMBERS (1–12), not names (A6). The names used to come from a module-level
    English table, which put "Jan Feb Mar" on the x-axis of a Dutch page — babel knows the Dutch
    abbreviations ("jan feb mrt"), and the template's locale-bound `monthname` filter applies them
    at render time, which is where the locale is. The year is not carried: a window can span the
    same month in two years and the axis then shows it twice, which is what it did before.
    """
    n = len(rec.imp)
    win_start = np.datetime64(rec.window[0].replace(tzinfo=None), "s")
    bucket_start = win_start + (np.arange(n) * rec.grid_s).astype("timedelta64[s]")
    # (year, month) key per interval, kept in first-seen (chronological) order.
    years = bucket_start.astype("datetime64[Y]").astype(int) + 1970
    months = bucket_start.astype("datetime64[M]").astype(int) % 12 + 1
    labels: list[int] = []
    values: list[float] = []
    seen: dict[tuple[int, int], int] = {}
    for i in range(n):
        key = (int(years[i]), int(months[i]))
        if key not in seen:
            seen[key] = len(values)
            labels.append(key[1])
            values.append(0.0)
        values[seen[key]] += float(rec.imp[i])
    return {"months": labels, "values": [round(v) for v in values]}


# ── §2.4's COST SAVINGS section ──────────────────────────────────────────────────────────────
#
# Everything below runs only under `cfg.simulate_cost`. §4.5 is explicit that `cost` is null
# WHOLESALE when the toggle is off — "not an object of null fields, and in particular not a
# `waterfall` array of eight null-valued entries, which would invite a template to render eight
# empty rows" — so the key is ABSENT from the view-model rather than present and empty, matching
# how `benchmark` is already handled. The template guards on it.
#
# Fixture 18 is the constraint the whole section is written under: every energy figure must be
# bit-identical with cost simulation on and off, down to the per-interval SoC trace. That holds
# here structurally rather than by care — `price_curves` and `compute_costs` are pure functions of
# the flows, they are called AFTER `run_all` and never feed back into it, and `economic_guard` is
# forced off by `SimulationConfig` itself when `simulate_cost` is false. Nothing in this section
# can reach the dispatch path.

# §6.10's eight waterfall keys → the English label §2.4's wireframe prints for each. The DOMAIN
# key (`costs.WATERFALL_LINES`) is not display text — `costs.WaterfallLine`'s docstring says so —
# so the mapping lives here, in the view, and the labels are marked with `_N` so `pybabel extract`
# finds them. The order is `WATERFALL_LINES`' order, which is §6.10's, and it is asserted against
# that tuple at import time below so a line added to the domain layer cannot silently render
# unlabelled.
#
# Two labels differ from §6.10's key names because §2.4's wireframe writes them differently:
# `added_grid_import_charging` is shown as "Grid import for charging" (the wireframe folds it into
# its "Avoided grid import" line's neighbourhood without naming the mechanism), and
# `standby_consumption` carries its kWh figure as a parenthetical in the wireframe. The kWh
# parenthetical is NOT reproduced: it would make the row's label a runtime string, and the standby
# kWh is already stated in the energy breakdown directly above.
_WATERFALL_LABELS: dict[str, str] = {
    "avoided_grid_import": _N("Avoided grid import"),
    "added_grid_import_charging": _N("Grid import for charging"),
    "avoided_terugleverkosten": _N("Avoided terugleverkosten"),
    "lost_feedin_compensation": _N("Lost feed-in compensation"),
    "arbitrage_export_revenue": _N("Grid arbitrage export revenue"),
    "standby_consumption": _N("Standby consumption"),
    "feedin_floor_topup": _N("Feed-in floor top-up"),
    "degradation": _N("Degradation cost"),
}
assert tuple(_WATERFALL_LABELS) == WATERFALL_LINES, (
    "the waterfall's display labels must cover §6.10's lines, in §6.10's order"
)

# Below this magnitude in euros a waterfall line is treated as ZERO and dropped from the display
# (§2.4: "lines that evaluate to zero are dropped from the display, never from `cost.waterfall`").
#
# **Tied to the rows' rounding, not to the currency's precision.** The rows render with pattern
# `#,##0` — whole euros — so every value under €0.50 prints as "€ 0" whatever its true magnitude.
# A half-CENT threshold would therefore keep exactly the rows §2.4 wants dropped: a line at €0.30
# is not zero, but it reaches the reader as "€ 0", and a column of "€ 0" says nothing while
# suggesting the figures failed to compute. Rounding is what the reader sees, so rounding is what
# the rule keys on.
#
# The cost of this is that a line genuinely worth €0.40 is dropped rather than shown as "€ 0" —
# which is the right trade while the rows are whole euros. Give them cents and this constant
# should follow them down; the two must not drift apart, which is why the pattern is named here.
#
# It is a DISPLAY threshold — `cost.waterfall` carries every line at full precision whatever this
# is set to, and the closing row is `saved_eur` from the bills, never a sum of what survived.
WATERFALL_DISPLAY_EPS_EUR = 0.5


def _fmt_eur(value: float) -> dict:
    """A euro amount → a number rendered "€ 1,153" / "€ 1.153" in the render locale."""
    return num(value, "eur")


def _fmt_signed_eur(value: float) -> dict:
    """A euro amount that may be negative → "€ 331" / "− € 331" (§7.2 item 9, in euros)."""
    return num(value, "eur_signed")


def _cost_block(
    cost_a, cost_c, lines, cfg: SimulationConfig
) -> dict:
    """§4.5's `cost` object plus the §2.4 presentation the COST SAVINGS section renders from.

    `cost_a` / `cost_c` are `costs.CostResult`s for runs A and C — the §6.10 marginal bill, fixed
    costs excluded (see `app/domain/costs.py`'s module comment; this is deliberately NOT the number
    at the bottom of an invoice, and the section says so in a caveat).

    The §4.5 fields, computed here and not re-derived anywhere else:

        baseline_eur / battery_eur   the two bills.
        saved_eur     `cost(A) − cost(C)`, SIGNED. §7.2 item 9's negative-saving case exists in
                      euros too, and nothing here clamps it.
        saved_pct     `100 × saved / baseline`, or None when the baseline bill is ~0 — a household
                      whose marginal bill is nothing has no percentage to have saved, and 0 or 100
                      would both assert something the data cannot support.
        waterfall     EVERY line from `costs.waterfall`, at full precision, in §6.10's order. This
                      is the JSON-shaped list and it is complete; the display list beside it is the
                      one §2.4 prunes.

    **`waterfall_rows` drops zero lines; `waterfall` keeps them** (§2.4, and §4.5's no-PV section:
    "lines that evaluate to zero are dropped from the display, never from `cost.waterfall` in the
    result JSON, which must continue to close against `cost(A) − cost(C)`"). The two lists are
    built from the same `lines` so they cannot disagree about a value, and only the display one is
    filtered. On a no-PV household that is four of the eight rows.

    **The degradation line is the exception to the drop rule.** §4.5 shows it carrying an
    `"enabled": false` flag, and `costs.py`'s module comment is explicit that deciding a line is
    disabled is a statement about the CONFIG (`degradation_eur_per_kwh == 0`) rather than about the
    computed number — a run can produce a 0.00 degradation line while degradation is perfectly
    enabled. So when the RATE is zero the row is shown with the word "disabled" in place of a
    figure, which is what §2.4's wireframe prints; when the rate is nonzero the row is a figure and
    obeys the ordinary drop rule. Dropping a disabled row would lose the statement that a
    parameter is off, which is not the same as a term that came out to nothing.

    **The closing row is the NET SAVING, and it is `saved_eur` rather than a sum of the rows.**
    §2.4 puts "Net saving" under a rule at the foot of the box. Taking it from the two bills rather
    than from the line values means the row states the quantity the KPI tile above it states —
    they are the same number by construction, not by the eight lines happening to add up. The
    closure identity that makes those two agree is fixture 4's, asserted in `tests/test_costs.py`,
    and it belongs there rather than being re-checked on a page.
    """
    baseline_eur = cost_a.eur
    battery_eur = cost_c.eur
    saved_eur = baseline_eur - battery_eur
    saved_pct = (
        100.0 * saved_eur / baseline_eur if abs(baseline_eur) > DIV_GUARD_EPS else None
    )

    degradation_disabled = cfg.pricing.degradation_eur_per_kwh == 0

    rows: list[dict] = []
    for line in lines:
        label = _WATERFALL_LABELS[line.label]
        if line.label == "degradation" and degradation_disabled:
            # §4.5's `"enabled": false`. The word, not a figure — "€ 0" beside a rate the user set
            # to zero would read as a measurement rather than as a switch that is off.
            rows.append({"label": label, "value": _msg("disabled"), "disabled": True})
            continue
        # `<=`, not `<`: the rows round half-to-even, so a line worth exactly €0.50 renders
        # "€ 0" like everything below it. A strict `<` would keep that one value as the single
        # zero-printing row the rule exists to remove.
        if abs(line.eur) <= WATERFALL_DISPLAY_EPS_EUR:
            continue
        rows.append({"label": label, "value": num(line.eur, "eur_force_signed")})
    rows.append({
        "label": _N("Net saving"),
        "value": num(saved_eur, "eur_force_signed"),
        "rule_above": True,
    })

    return {
        "currency": "EUR",
        "baseline_eur": baseline_eur,
        "battery_eur": battery_eur,
        "saved_eur": saved_eur,
        "saved_pct": saved_pct,
        # §4.5's shape, complete and unpruned. `enabled` rides on the degradation entry only,
        # matching §4.5's example, where it is the one line carrying the flag.
        "waterfall": [
            ({"label": line.label, "eur": line.eur, "enabled": False}
             if line.label == "degradation" and degradation_disabled
             else {"label": line.label, "eur": line.eur})
            for line in lines
        ],
        # ── Presentation (§2.4) ─────────────────────────────────────────────────────────────
        "kpi": {
            "title": _N("MONEY SAVED"),
            "value": num(saved_eur, "eur_bare"),
            "unit": "€",
            "delta": (_fmt_signed_pct(saved_pct) if saved_pct is not None else "n/a"),
            # The wireframe's sentence beside the tile: the two bills, in the order the reader
            # reads them. One msgid with two figures rather than an arrow pair, because it is a
            # sentence rather than a comparison of two like quantities.
            "sentence": _msg(
                "%(baseline)s without a battery → %(battery)s with one",
                baseline=_fmt_eur(baseline_eur),
                battery=_fmt_eur(battery_eur),
            ),
            "note": _msg(
                "Priced under the 2027 regime from the contract you entered. See the caveats "
                "below."
            ),
        },
        "waterfall_rows": rows,
    }


@dataclass(frozen=True)
class PriceBracket:
    """§6.16's pricing-uncertainty width over one window — how far off the saving could be.

    The question it answers: hourly energy data cannot say WHEN inside an hour the kWh moved,
    so when the supplier bills each quarter-hour at its own cleared price, the same dispatch
    could have been billed anywhere between the hour's cheapest and dearest quarter. This is
    the size of that band, in euros.

        width_eur     `(saved_high − saved_low) / 2`, i.e. the ± half-width the caveat prints.
                      Always ≥ 0 (see the ordering note below). Zero when nothing is bracketed.
        bracketed_fraction   the share of PRICED intervals (those with a non-NaN spot) whose
                      `spot_max > spot_min`. Distinguishes "no uncertainty at all" (0.0 — the
                      price was natively at grid resolution everywhere) from "uncertainty over
                      part of the window" (e.g. 0.6 on a window straddling 2025-10-01, when
                      EPEX moved to quarter-hourly settlement). The caveat text needs the
                      difference; the width alone cannot express it.
        saved_low / saved_central / saved_high   the three evaluations, INTERNAL. D5′ reports
                      only the width: over seven synthetic price shapes the endpoints were a
                      true worst-case envelope but a poor uncertainty estimate — three had a
                      width exceeding the central estimate and two went negative at the low
                      end, which reads as "you might lose money" when it means no such thing.
                      Carried anyway so tests can pin the ordering, which is the property the
                      construction is designed to give.

    **The split of min/max prices is BY DIRECTION OF FLOW.** cost = import·p_import −
    export·p_export_net, so billing imports at the hour's cheapest price AND crediting exports
    at its dearest minimises a bill, and the reverse maximises it. An earlier prototype split
    by "charging vs everything else" instead, which does not have that property; it is recorded
    in the changelog because it nearly drove the wrong conclusion.

    **The envelope is chosen PER INTERVAL, because a bounded BILL is not a bounded SAVING.**
    Each of `cost(A)` and `cost(C)` is genuinely bracketed by billing the whole window at one
    extreme. Their DIFFERENCE is not. The saving is
    `Σᵢ (impAᵢ − impCᵢ)·p_importᵢ − Σᵢ (expAᵢ − expCᵢ)·p_export_netᵢ`, which is SEPARABLE, so its
    extremum picks each interval's price on the sign of that interval's own flow difference. A
    window-uniform extreme evaluates only a corner of the price box, and on a window mixing
    grid-charging intervals (`impA − impC < 0`) with import-cutting ones the two corners cancel
    against each other. In the symmetric limit they cancel exactly — a measured four-hour case
    with equal spreads and alternating flow signs reported a width of €0.00 against a true
    envelope of ±€0.48, i.e. "no uncertainty" printed exactly where uncertainty is largest.
    Sign-alternating windows are not exotic: 182 of 200 realistic windows contain both.

    **The three evaluations are still sorted, with the central figure taking part.** The
    per-interval choice is exact for the affine part of §6.5 (`price_curves` is affine and
    monotone in spot for every shipped configuration), but `compute_costs` also carries the
    feed-in floor top-up, which under `FeedinFloorMode.MONTHLY` is a WINDOW-level `max(0, ...)`
    and so is not separable. Where that floor binds, the greedy per-interval pick can fall short
    of the true extremum — measured only when spot straddles the binding boundary, and it errs by
    UNDER-stating. Sorting makes `saved_low ≤ saved_central ≤ saved_high` and `width_eur ≥ 0`
    hold unconditionally rather than only where the floor is slack, and costs nothing.

    So the number is a worst case over intra-interval price placement, exact where the floor is
    slack and a lower bound where it binds. `test_the_band_still_contains_the_headline_when_the_
    two_extremes_do_not` pins the containment invariant on a window that violated it under the
    superseded corner-based construction.

    This is a WORST CASE and the caveat says so (D9). A statistically typical error would be
    far narrower, since errors across thousands of hours partially cancel — but claiming that
    needs an independence assumption that household load does not satisfy (load has strong
    intra-hour structure and battery charging is deliberately timed). Not attempted.
    """

    width_eur: float
    bracketed_fraction: float
    saved_low: float
    saved_central: float
    saved_high: float


def _price_bracket(
    cfg: SimulationConfig,
    frame,
    runs,
    saved_central: float,
) -> PriceBracket | None:
    """§6.16's width, from THREE COST EVALUATIONS OVER ONE UNCHANGED DISPATCH.

    Nothing here re-runs the simulation. `runs.a` and `runs.c` are the flows the central figure
    was billed from, and they are re-billed at two other price vectors — which is the whole
    design: the uncertainty being measured is about the PRICE the household was charged, not
    about what the battery would have done, and a second dispatch would conflate the two. It
    also keeps fixture 18 structural: like the rest of this section, this runs after `run_all`
    and feeds nothing back into it.

    Returns None — not a zero-width bracket — when the width is not a meaningful quantity:

      * the supplier bills the HOURLY mean (D10). The hourly price is then exactly what the
        household paid, and there is no uncertainty to report at all. This is appendix A's
        default and most Dutch dynamic contracts today.
      * no interval carries a spread: `spot_max == spot_min` everywhere. That is the natively
        hourly case (§6.16's D1/D2) — the intra-hour variation is unobservable rather than
        absent, and reporting "±€0" would assert it was absent.
      * the window has no priced interval at all (every `spot` NaN), which reaches the same
        `nanmax` of an empty selection and is handled by the same guard.

    None rather than a zero: a caller can then tell "we know the width and it is nothing" from
    "the width is not a thing we can state", and the caveat in the next step suppresses itself
    on the None rather than printing a confident zero.
    """
    if not cfg.simulate_cost:
        return None
    if cfg.pricing.supplier_settlement != SupplierSettlement.QUARTER_HOURLY:
        return None

    spot_min = np.asarray(frame.spot_min, dtype=np.float64)
    spot_max = np.asarray(frame.spot_max, dtype=np.float64)
    spread = spot_max - spot_min
    # NaN discipline. `spread` is NaN exactly where `spot` was (step 1 guarantees `spot_min` and
    # `spot_max` are NaN on precisely those intervals), so `np.nanmax` over an ALL-NaN window
    # both warns and returns NaN — and `NaN > 0` is False, which would silently take the "no
    # spread" branch for the right reason but by accident. The explicit `priced` count makes the
    # empty case a decision rather than an IEEE side effect, and keeps the fraction's denominator
    # from being zero.
    priced = np.count_nonzero(~np.isnan(spread))
    if priced == 0:
        return None
    bracketed = int(np.count_nonzero(spread > 0))
    if bracketed == 0:
        return None

    # ── The two extreme price vectors ────────────────────────────────────────────────────────
    #
    # **This looks like a bug and is not.** `price_curves` builds all four arrays from ONE spot
    # array, but the bracket needs the IMPORT side priced off one spot vector and the EXPORT
    # side off the other — that is the by-direction-of-flow split `PriceBracket` documents. So
    # each extreme is assembled from TWO curve sets, taking `p_import` from one and
    # `p_export_net` / `compensation` from the other. Reading a single line in isolation
    # ("optimistic imports come from the min curves, optimistic exports from the MAX curves")
    # is what makes it look transposed; the pairing is the point.
    #
    # Both spot vectors are run through the full §6.5 curve construction rather than having the
    # bracket applied to the finished prices, because the contract's markup, energy tax, VAT and
    # terugleverkosten are not all affine in spot for every configuration — deriving the extreme
    # curves from the extreme SPOT is the only construction that stays correct if §6.5 gains a
    # non-linear term.
    lo_curves = price_curves(cfg.pricing, spot_min)   # cheap energy
    hi_curves = price_curves(cfg.pricing, spot_max)   # dear energy

    def _saved(p_import, p_export_net, compensation) -> float:
        """cost(A) − cost(C) at one price vector, on the flows already computed."""
        args = (p_import, p_export_net, compensation, frame.index, cfg.pricing)
        return compute_costs(runs.a, *args).eur - compute_costs(runs.c, *args).eur

    # ── The envelope is chosen PER INTERVAL, not by picking a corner of the price box ─────────
    #
    # This is the crux, and the first implementation got it wrong in a way that mattered. The
    # saving is
    #       Σᵢ (impAᵢ − impCᵢ)·p_importᵢ  −  Σᵢ (expAᵢ − expCᵢ)·p_export_netᵢ
    # which is SEPARABLE: each interval contributes independently, so the extremum over the price
    # box picks each interval's price on the sign of THAT interval's flow difference. Billing the
    # whole window at `spot_min` (and the reverse) evaluates just two of the box's corners — the
    # right pair for a single BILL, but not for a DIFFERENCE of bills.
    #
    # The difference is not academic. Where the battery grid-charges, `impA − impC` is negative
    # and that interval wants the OPPOSITE extreme from an interval where the battery cuts import.
    # A window mixing the two — 182 of 200 realistic windows do — has the uniform corners cancel
    # against each other. In the symmetric limit they cancel exactly: a measured case with four
    # equal-spread hours and alternating flow signs reported a width of €0.00 against a true
    # envelope of ±€0.48. That is the caveat printing "no uncertainty" exactly where uncertainty
    # is largest, which is the one failure mode a worst-case claim must not have.
    #
    # Costs two np.where passes over arrays already in hand — no extra `price_curves` calls, no
    # extra simulation, and the one-dispatch constraint is untouched.
    #
    # Sign convention: the export term is SUBTRACTED, so an interval with `d_exp > 0` wants the
    # LOW export price to maximise the saving. The four `np.where`s below are not copy-paste
    # variants of each other; the export pair is deliberately mirrored relative to the import pair.
    d_imp = np.asarray(runs.a.imp, dtype=np.float64) - np.asarray(runs.c.imp, dtype=np.float64)
    d_exp = np.asarray(runs.a.exp, dtype=np.float64) - np.asarray(runs.c.exp, dtype=np.float64)

    hi_import = np.where(d_imp > 0, hi_curves.p_import, lo_curves.p_import)
    lo_import = np.where(d_imp > 0, lo_curves.p_import, hi_curves.p_import)
    hi_export = np.where(d_exp > 0, lo_curves.p_export_net, hi_curves.p_export_net)
    lo_export = np.where(d_exp > 0, hi_curves.p_export_net, lo_curves.p_export_net)
    hi_comp = np.where(d_exp > 0, lo_curves.compensation, hi_curves.compensation)
    lo_comp = np.where(d_exp > 0, hi_curves.compensation, lo_curves.compensation)

    saved_optimistic = _saved(hi_import, hi_export, hi_comp)
    saved_pessimistic = _saved(lo_import, lo_export, lo_comp)

    # Sorted, with `saved_central` taking part. The per-interval choice above is exact for the
    # affine part of §6.5 — `price_curves` is affine and monotone in spot for every shipped
    # configuration — but `compute_costs` also carries the §6.5 feed-in floor top-up, which under
    # `FeedinFloorMode.MONTHLY` is a WINDOW-level `max(0, ...)` and therefore not separable. Where
    # that floor binds, the greedy per-interval pick can fall short of the true extremum (measured:
    # only when spot straddles the binding boundary, and it errs by UNDER-stating). Sorting keeps
    # the two invariants the caveat depends on — a non-negative width whose band contains the
    # headline figure — true unconditionally rather than only where the floor is slack.
    saved_low = min(saved_optimistic, saved_pessimistic, saved_central)
    saved_high = max(saved_optimistic, saved_pessimistic, saved_central)
    return PriceBracket(
        width_eur=(saved_high - saved_low) / 2.0,
        bracketed_fraction=bracketed / priced,
        saved_low=saved_low,
        saved_central=saved_central,
        saved_high=saved_high,
    )


def _share_pct(fraction: float) -> dict:
    """Format `bracketed_fraction` for the §6.16 caveat, keeping a small share visible.

    The partial branch of that caveat fires for anything below 0.95, so the value spans nearly
    the whole 0..1 range, and no ONE `_NUM_KINDS` entry is right across it. `"pct"` rounds to a
    whole percent, which prints "0%" for a 365-day window carrying three spread hours (fraction
    0.00034) — a sentence that says "for 0% of the priced hours … that shifts the saving by € 2"
    contradicts itself. `"pct_dec2"` everywhere fixes that but writes an ordinary half-window
    straddle as "50.00%", two digits of precision the interval count does not carry meaning to
    and which reads as a measurement rather than a share.

    A single `"#,##0.##"` pattern (trailing zeros suppressed) would fix both ends — "0.03%" and
    "50%" — and was rejected because it writes 22 of 24 hours as "91.67%", which is worse than
    "92%" for the same reason: the value is a ratio of small integers and the extra digits assert
    a precision it does not have.

    So: whole percent where the value survives that rounding, two decimals where it does not.
    Both kinds already exist and are documented for exactly these two cases (`pct_dec2`'s
    docstring names "a share too small to survive rounding to a whole percent"); no new kind is
    introduced.

    The test for "survives the rounding" is to RENDER it and look, rather than to compare against
    a 0.005 cut. `#,##0` rounds half-to-even, so 0.005 itself prints "0%" and a `>= 0.005` cut
    would let exactly that value through — the one case the whole helper exists to catch. The
    rendering is locale-dependent only in its separators, never in whether the digits are all
    zero, so checking one locale settles it for both.
    """
    whole = num(fraction, "pct")
    if any(ch.isdigit() and ch != "0" for ch in format_num(whole["num"], whole["fmt"], "en")):
        return whole
    return num(fraction, "pct_dec2")


def _cost_benchmark_block(bench, cfg: SimulationConfig) -> dict:
    """§2.4's "Benchmark: money saved" box, from the §6.12 COST block (run E).

    The sibling of `_benchmark_block`, and it renders through the same `_benchmark_box.html`
    partial — the partial takes a `rows` list and a `gloss` and knows nothing about kWh, so it
    generalised without a change. Only the box's TITLE differs, which is why the block carries a
    `title` and the partial reads it (with the energy box's title as its default, so a view-model
    built before this phase still renders).

    ## The capture ratio: THREE shapes here, not the energy box's four

    `_benchmark_block` has four, and **shape 2 — restate on the drift-corrected basis — does not
    carry over.** `CostBenchmark`'s docstring is the authority and follow-up H10 records the
    measurement behind it. §6.12's correction is `saved_kwh + soc_delta_kwh × eta_d`, which is
    exact in kWh because a residual kWh is worth exactly one avoided kWh whenever it is used. In
    euros the residual's worth depends on WHEN it is used, and the two sides use it at different
    times by construction: the DP's terminal constraint forces it to carry charge through (or
    repurchase at) the expensive hours, while a liquidating policy dumps it into the cheap ones and
    never buys back. Valuing at §6.11's median import price — the obvious analogue, and the reason
    `median_import_price_eur_kwh` is a field — leaves fixture-6 violations up to €0.91, measured;
    valuing at the window maximum nearly restores the ordering, which is evidence that the BASIS is
    wrong rather than the DP. There is no sound euro correction to reach for, so this box does not
    reach for one.

    What it does instead is what `CostBenchmark`'s docstring instructs: **branch on
    `policy_soc_delta_kwh` and say the comparison is unavailable on that basis.** That is a
    weaker statement than the energy box's, and deliberately so — a restated percentage the reader
    could act on would be more useful and would not be true.

    **This is the COMMON case, not an edge case.** Measured over `_fixture_6_cost_configs`'
    144-configuration sweep, 48 produce a euro capture ratio above 1 (up to 1.60), all of them in
    the liquidating half. A box that treated it as a rare fault would be wrong on a third of runs.

    The three shapes:

      1. **normal** — drift immaterial and `0 ≤ ratio ≤ 1`. A plain percentage, with §2.4's
         one-line note that this ceiling and the energy one come from different dispatches ("buying
         cheaply is not the same as importing little"), and the export sentence when the fourth row
         is shown.
      2. **drift-funded** — `policy_soc_delta_kwh` materially negative, by `_drift_is_material`'s
         test. NO ratio is printed and none is restated. The box says the battery ended less
         charged than it started, that the benchmark may not do that, and that the comparison is
         not available in euros on that basis.
      3. **bound ≈ 0, or a ratio above 1 with non-negative drift.** The first is `capture_ratio is
         None` and branches on the policy row exactly as the energy box does. The second is the
         case `CostBenchmark`'s docstring calls "a genuine fault", and it reuses the energy box's
         `_FAULT_GLOSS` wording: one literal, one msgid, and the reader sees the same sentence for
         the same condition on either box.

    The ROWS and the bar scale follow `_benchmark_block` exactly, including the negative-saving
    floor on the bar only. See that function; the reasoning is identical with euros substituted for
    kWh, and it is not repeated here.

    **`floor_binds` is disclosed, and here is why it is a sentence rather than a suppression**
    (follow-up H11). The floor top-up is `max(0, −Σ_period export × compensation)`, a function of a
    whole assessment period's dispatch, so run E cannot price it inside `transition_cost` without a
    second DP state dimension; it minimises the per-interval bill and the top-up is applied
    afterwards. In a window where the floor binds, the bound is on the pre-top-up bill and a policy
    could in principle beat the full-bill figure by stumbling into a larger top-up than the DP's
    dispatch earns. H11 records that HOW LARGE such a violation could get has not been measured.

    So: the rows and the ratio are shown as computed, and one sentence is appended saying the
    ceiling is not exact over this window and in which direction it is soft. Suppressing the box
    would be an overreaction — the floor binds only when a whole assessment period's export earned
    a net negative amount, which is rare, and the bound is still informative — and printing the
    figure unqualified would be the thing `floor_binds` exists to prevent. The sentence is
    appended to whatever gloss the shape produced rather than replacing it, because the two say
    different things and the reader needs both.
    """
    pf = bench.perfect_foresight_eur
    unc = bench.perfect_foresight_eur_unconstrained

    show_unconstrained = (
        unc is not None
        and bench.capture_ratio is not None
        and bench.capture_ratio_unconstrained is not None
        and abs(bench.capture_ratio - bench.capture_ratio_unconstrained)
        > benchmark_divergence_display_threshold
    )

    scale = max(bench.policy_eur, pf, unc if show_unconstrained else pf, 0.0)

    def frac(value: float) -> float:
        if scale <= DIV_GUARD_EPS:
            return 0.0
        return max(0.0, min(1.0, value / scale))

    rows = [
        {"label": "No battery", "value": _fmt_eur(0.0), "frac": 0.0, "dot": False},
        {"label": "Your policy", "value": _fmt_signed_eur(bench.policy_eur),
         "frac": frac(bench.policy_eur), "dot": True},
        {"label": "Perfect foresight", "value": _fmt_signed_eur(pf),
         "frac": frac(pf), "dot": True},
    ]
    if show_unconstrained:
        assert unc is not None  # narrowed by show_unconstrained; restated for the type reader
        rows.append({"label": "…if export allowed", "value": _fmt_signed_eur(unc),
                     "frac": frac(unc), "dot": True})

    # The same display tolerance `_benchmark_block` uses, and for the same reason: a policy that
    # exactly matches the bound is the best possible outcome, and a ratio of 1.0000000000000024
    # must not be reported as broken.
    RATIO_RANGE_EPS = 1e-6
    # `_drift_is_material` reads `policy_soc_delta_kwh` and `policy_saved_kwh`, neither of which
    # `CostBenchmark` spells the same way, so the test is written out here against the euro saving.
    # It is the SAME test — §6.11's `SOC_DRIFT_WARN_FRAC` with a sign condition, per §2.4's "reuse
    # SOC_DRIFT_WARN_FRAC rather than introducing a second threshold" — with the relative base in
    # euros, since that is the figure the ratio is built on. A drift small against a large euro
    # saving cannot have funded it.
    delta = bench.policy_soc_delta_kwh
    base = abs(bench.policy_eur)
    if delta >= 0:
        drift_funded = False
    elif base > DIV_GUARD_EPS:
        # The residual valued at §6.11's own basis, compared against the saving it might have
        # funded. Note this uses the median price to size the QUESTION, not to answer it: whether
        # the drift is material is a magnitude comparison, which a single price can settle; what
        # the drift is worth to each side is the thing H10 says no single price can settle.
        price = bench.median_import_price_eur_kwh
        residual_eur = abs(delta) * cfg.eta_d * (price if price is not None else 0.0)
        drift_funded = residual_eur > SOC_DRIFT_WARN_FRAC * base
    else:
        drift_funded = abs(delta) > DIV_GUARD_EPS

    fault_gloss = _msg(_FAULT_GLOSS)

    if bench.capture_ratio is None:
        # Shape 3a: the bound is ~0. Branch on the visible policy row, exactly as the energy box
        # does — a box must never assert that nothing was achievable above a non-zero figure.
        if abs(bench.policy_eur) <= DIV_GUARD_EPS:
            gloss = _msg(
                "Over this period even a perfectly-informed battery could not have saved any "
                "money, so there is no capture ratio to report."
            )
        else:
            gloss = _msg(
                "The best possible dispatch over this period could not have saved any money, yet "
                "your policy shows %(policy)s saved. That figure is not something a "
                "perfectly-informed battery could reproduce: the benchmark must return the "
                "battery to the state of charge it started from, and your policy did not. There "
                "is no capture ratio to report for this period.",
                policy=_fmt_signed_eur(bench.policy_eur),
            )
    elif drift_funded:
        # Shape 2: drift-funded. NO ratio, and no restatement — see this function's docstring and
        # follow-up H10. The sentence names the residual in kWh, which is the quantity that is
        # actually measured; converting it to euros here would be the correction the block does
        # not have.
        gloss = _msg(
            "Your battery ended this period %(residual)s less charged than it started, so part "
            "of the money it saved was paid for out of the charge it began with rather than "
            "earned by its dispatch. The benchmark is not allowed to do that — it must finish at "
            "the state of charge it started from. In kilowatt-hours the two can be put back on a "
            "comparable footing; in euros they cannot, because what that leftover charge was "
            "worth depends on when it was used, and the two dispatches use it at different times. "
            "So no capture ratio is shown for this period. Selecting a period that starts and "
            "ends at a similar state of charge gives a comparison in euros.",
            residual=_fmt_kwh(abs(bench.policy_soc_delta_kwh)),
        )
    elif bench.capture_ratio > 1.0 + RATIO_RANGE_EPS:
        # Shape 3b: above the bound with NON-negative drift. `CostBenchmark`'s docstring calls this
        # the genuine fault, and it gets the energy box's fault wording — the same condition
        # described the same way on both boxes.
        gloss = fault_gloss
    elif show_unconstrained and bench.capture_ratio_unconstrained is not None:
        gloss = _msg(
            "Your policy captures %(pct)s percent of the money a perfectly-informed battery "
            "could have saved. A different ceiling from the energy benchmark, and a different "
            "dispatch behind it: buying cheaply is not the same as importing little. Allowed to "
            "export, that ceiling rises to %(ceiling)s (a %(unc_pct)s percent capture) — the "
            "extra is arbitrage your export setting currently forbids.",
            pct=num(round(100 * bench.capture_ratio), "count"),
            ceiling=_fmt_eur(unc),
            unc_pct=num(round(100 * bench.capture_ratio_unconstrained), "count"),
        )
    else:
        gloss = _msg(
            "Your policy captures %(pct)s percent of the money a perfectly-informed battery "
            "could have saved. A different ceiling from the energy benchmark, and a different "
            "dispatch behind it: buying cheaply is not the same as importing little.",
            pct=num(round(100 * bench.capture_ratio), "count"),
        )

    block = {
        "title": _N("Benchmark: money saved"),
        "rows": rows,
        "gloss": gloss,
    }
    if bench.floor_binds:
        # H11's disclosure. A SECOND message rather than a variant of each gloss above: it
        # qualifies the ceiling regardless of which shape was chosen, it fires rarely, and folding
        # it into four msgids would make four sentences a translator has to keep in step.
        block["note"] = _msg(
            "Over this period the statutory feed-in floor paid out, and the benchmark cannot see "
            "it: the floor is assessed over a whole billing period while the benchmark optimises "
            "each interval on its own. The ceiling above is therefore approximate for this "
            "period, and it is a floor on the ceiling rather than a hard one — a policy could in "
            "principle earn a larger top-up than the benchmark's dispatch does."
        )
    return block


def _monthly_saved_eur(
    rec: ReconciledGrid, per_interval_saved_eur: np.ndarray
) -> list[float]:
    """Monthly Σ of the per-interval euro saving, bucketed like `_monthly_import` (§4.5 `monthly`).

    §2.4's *Monthly savings (€)* chart option and §4.5's `monthly[].saved_eur`. The bucketing is
    the SAME calendar-month bucketing `_monthly_import` performs over the same intervals, so the
    two series' bars line up under the two chart options — a euro bar and a kWh bar for one month
    describe one window.

    `per_interval_saved_eur` is `(A − C)` per interval on the PRE-TOP-UP bill, which is the only
    part of §6.10's bill that HAS a per-interval decomposition. The feed-in floor top-up is a
    period-level scalar with no per-interval allocation at all (`app/domain/costs.py`'s module
    comment: pushing it into a per-interval line "would require choosing an allocation across
    intervals"), so it is excluded here rather than smeared. The consequence is stated rather than
    hidden: in the rare window where the floor binds, these monthly bars sum to slightly less than
    the headline `saved_eur`, and the section's caveat says so.

    `np.nansum` per bucket for the same reason every sum in the cost layer is one: a gap interval
    is NaN on both sides and must contribute zero euros rather than poisoning a whole month.
    """
    n = len(rec.imp)
    win_start = np.datetime64(rec.window[0].replace(tzinfo=None), "s")
    bucket_start = win_start + (np.arange(n) * rec.grid_s).astype("timedelta64[s]")
    years = bucket_start.astype("datetime64[Y]").astype(int) + 1970
    months = bucket_start.astype("datetime64[M]").astype(int) % 12 + 1
    values: list[float] = []
    seen: dict[tuple[int, int], int] = {}
    saved = np.asarray(per_interval_saved_eur, dtype=np.float64)
    for i in range(n):
        key = (int(years[i]), int(months[i]))
        if key not in seen:
            seen[key] = len(values)
            values.append(0.0)
        v = saved[i]
        if not np.isnan(v):
            values[seen[key]] += float(v)
    return values


def results_from(
    dataset: LoadedDataset,
    window: tuple[datetime, datetime],
    *,
    cfg: SimulationConfig | None = None,
    with_benchmark: bool = False,
    custom_range: bool = False,
) -> dict | None:
    """Build the panel-③ ENERGY SAVINGS view-model over `window` from a real run (specs §2.4).

    **`with_benchmark` defaults to False and that is the whole latency story.** §6.12's DP is
    ~2.3 s per pass on a year of hourly data against ~0.13 s for everything else on this page, and
    it ran inline on every `GET /` — measured at 4.72 s. The box is now fetched separately (`POST
    /results/benchmark`, which calls this with `with_benchmark=True`) and fills in when ready, so
    the panel paints from the §6.11 figures at the old speed. Cost scales linearly with window
    length (1 week 0.04 s, 1 year 2.29 s per DP), so only long windows were ever slow. No cache was
    added — see the phase-5 changelog; lazy loading was the option chosen.

    Shape-compatible with sample_data._panel_results() EXCEPT: the "intervals battery full/empty"
    secondary row is omitted. Returns None when
    reconcile_grid returns None (no simulatable grid) — the caller then falls back to the empty
    state, exactly like data_summary_from.

    The battery figures come from runs A/B/C over a `SimulationFrame` under `cfg` — the caller's
    persisted panel-② parameter set, or appendix-A defaults when it is None (nothing configured
    yet). See the module comment, and for the sign, clamp and omit rules the presentation obeys.

    **`custom_range` says the window came from an explicit start/end, not a preset.** The window
    itself cannot answer that — it is two datetimes, and `_period_selected_for` can only map a span
    back to the nearest preset — so the caller that parsed the request says so. It sets
    `period_selected` to PERIOD_SELECTED_CUSTOM, which is what makes the selector highlight its
    "custom" button and keep the date fields visible instead of snapping the highlight to whichever
    preset was closest in length.

    `should_cancel` is deliberately not passed to `run_all`: there is no run-orchestration layer
    (§3.3/§5.3) to cancel from, and a hook nothing can trip would be dead weight. The run is
    ~0.1 s over a year of hourly data (measured, changelog 20260725). The §6.12 DP added below is
    the part that is NOT cheap — ~4.5 s for the two passes — and it too is computed inline per
    request rather than behind a cache; see the note at its call site.
    """
    rec = reconcile_grid(dataset, window)
    if rec is None:
        return None

    eff = rec.window  # the effective window actually reconciled (may differ from the requested one)
    intervals = len(rec.imp)
    res_label = _fmt_res(rec.grid_s)      # English, for the untranslated `period` fallback only
    res_msg = _res_msg(rec.grid_s)        # the same label as a nested message, for the sentences

    # The picker's coverage line, split in two so the template can insert the day count between
    # them: "<dates> · N days · simulated hourly · 8,760 intervals". The day count is the
    # template's to render (it needs ngettext against `period_days`); `period_dates` is pure data
    # (two ISO dates) and stays a bare string. The data-glance section below the picker used to
    # repeat this span; it no longer does, so the selected range's length is stated once per panel.
    #
    # `period_run` is a COUNTED message (`_msg_n`): the interval count drives its plural, so a
    # one-interval window used to read "1 intervals". The resolution rides as a NESTED message
    # (`data_view._res_msg`) rather than as the bare English word `_fmt_res` returns: interpolation
    # runs after translation, so a bare string would put "hourly" into a Dutch sentence.
    period_dates = f"{eff[0].date().isoformat()} → {eff[1].date().isoformat()}"
    period_run = _msg_n(
        "simulated %(res)s · %(n)s interval",
        "simulated %(res)s · %(n)s intervals",
        intervals,
        res=res_msg,
        # The count reaching ngettext (the positional `intervals`) and the count PRINTED are the
        # same value by construction; the printed one is now a figure formatted in the render
        # locale ("8,760" / "8.760") rather than an f-string's English grouping.
        n=num(intervals, "count"),
    )
    period_days = (eff[1] - eff[0]).days
    # `period` stays the whole line as one PLAIN string for any consumer that wants it unsplit (the
    # template falls back to it only for a view-model that predates the split). It is not
    # translated — the template renders `period_run` instead whenever the split keys are present.
    period = f"{period_dates} · simulated {res_label} · {intervals:,} intervals"

    # ── Run the simulation (§6.9) and compute the §6.11 metrics ────────────────────────────────
    # simulation_frame re-runs reconcile_grid internally rather than taking `rec`. That is one
    # duplicated reconciliation per request (~4 ms on a year of hourly data, measured); the
    # alternative — a frame builder that accepts a pre-reconciled grid — would change a Phase-1
    # module's signature, which is out of scope here. Both paths run the SAME reconcile_grid over
    # the SAME window, so the band's numbers and the run's cannot disagree.
    frame = simulation_frame(dataset, window)
    # The caller's config (the persisted panel-② parameter set). None means "nothing configured
    # yet", which is exactly appendix-A defaults — the same object this function used to build
    # unconditionally, so an un-updated caller gets its previous behaviour rather than a crash.
    if cfg is None:
        cfg = SimulationConfig()
    # The PV series' own coverage as a per-interval mask (§2.3a). Handed to `energy_metrics` so BOTH
    # scenarios' self-consumption is measured over that one window; see `_pv_coverage_mask`.
    pv_mask = _pv_coverage_mask(dataset, rec)
    pv_present = _pv_present(rec, pv_mask)
    metrics: EnergyMetrics | None = None
    bench: EnergyBenchmark | None = None
    cost: dict | None = None
    cost_bench: CostBenchmark | None = None
    monthly_saved_eur: list[float] | None = None
    price_bracket: PriceBracket | None = None
    if frame is not None and frame.intervals > 0:
        # `rec` and `frame` come from the same reconcile_grid over the same window, so `pv_mask`
        # (built against `rec`) indexes `frame`'s arrays too — same length, same interval starts.
        runs = run_all(frame, cfg)
        metrics = energy_metrics(runs, frame, cfg, pv_mask=pv_mask)
        # ── §6.5 + §6.10: the euro side, ONLY under `cfg.simulate_cost` (§4.5, §6.12's table) ──
        #
        # Everything here runs AFTER `run_all` and feeds nothing back into it, which is what makes
        # fixture 18 hold structurally: `price_curves` and `compute_costs` are pure functions of
        # the flows, and `economic_guard` — the one cost term that could reach the dispatch path —
        # is forced off by `SimulationConfig` itself whenever `simulate_cost` is false. The energy
        # figures above are computed identically either way, including the SoC trace.
        #
        # Cost is CHEAP (a handful of array passes, no DP), so unlike the benchmark it runs on
        # every request rather than behind `with_benchmark`. Only run E below is expensive.
        if cfg.simulate_cost:
            curves = price_curves(cfg.pricing, frame.spot)
            cost_a = compute_costs(
                runs.a, curves.p_import, curves.p_export_net, curves.compensation,
                frame.index, cfg.pricing,
            )
            cost_c = compute_costs(
                runs.c, curves.p_import, curves.p_export_net, curves.compensation,
                frame.index, cfg.pricing,
            )
            # The flat terugleverkosten rate, recovered as §6.5's `PriceCurves` documents it. A
            # scalar, matching `waterfall`'s signature; `nanmax` rather than an element because
            # every element is NaN wherever `spot` was, and the rate is one constant across the
            # window under TlkMode.FLAT. A window with NO priced interval at all leaves it NaN,
            # which would poison the two export lines, so it falls back to 0.0 — in that window
            # every flow-times-price product is NaN anyway and every line is zero regardless.
            tlk_arr = np.asarray(curves.compensation, dtype=np.float64) - np.asarray(
                curves.p_export_net, dtype=np.float64
            )
            tlk = float(np.nanmax(tlk_arr)) if np.any(~np.isnan(tlk_arr)) else 0.0
            lines = waterfall(
                runs.a, runs.b, runs.c, curves.p_import, curves.compensation, tlk,
                cfg.pricing, frame.index, curves.p_export_net,
            )
            cost = _cost_block(cost_a, cost_c, lines, cfg)
            # §4.5's `monthly[].saved_eur`, on the PRE-TOP-UP per-interval bill — the only part of
            # the bill that decomposes per interval. See `_monthly_saved_eur`.
            p_imp = np.asarray(curves.p_import, dtype=np.float64)
            p_exp = np.asarray(curves.p_export_net, dtype=np.float64)
            def _per_interval_bill(flows):
                return (np.asarray(flows.imp, dtype=np.float64) * p_imp
                        - np.asarray(flows.exp, dtype=np.float64) * p_exp)
            monthly_saved_eur = _monthly_saved_eur(
                rec, _per_interval_bill(runs.a) - _per_interval_bill(runs.c)
            )
            # §6.16's pricing-uncertainty width: the same dispatch, billed at the hour's
            # cheapest and dearest native price points. Passed the CENTRAL saving that
            # `_cost_block` just published, so the band is guaranteed to contain the figure on
            # screen rather than a re-derivation of it. None when there is no width to state —
            # hourly settlement, or no intra-interval spread anywhere. See `_price_bracket`.
            price_bracket = _price_bracket(cfg, frame, runs, cost_a.eur - cost_c.eur)
        # §6.12's perfect-foresight DP — ONLY when the caller asked for it. Runs A and C are
        # passed in rather than re-run, so the policy saving inside the benchmark block is the
        # SAME number the KPI tile shows.
        #
        # **This is the expensive part of the request**: the A/B/C runs take 0.12 s and the two
        # DPs take ~4.6 s on a year of hourly data at appendix A's 101 × 41 grids. It is therefore
        # off by default and fetched separately; see this function's docstring and the phase-5
        # changelog. Nothing is cached — that option was considered and not chosen.
        if with_benchmark:
            bench = energy_benchmark(runs.a, runs.c, frame, cfg)
            # Run E — §6.12's COST DP. Gated on `with_benchmark` for the same latency reason run D
            # is (another ~4.6 s for its two passes, doubling the box's cost), AND on
            # `cfg.simulate_cost`, which is §6.12's own table: the cost benchmark runs "only when
            # cfg.simulate_cost". `cost_benchmark` deliberately does not check the flag itself —
            # its docstring says a function returning None on a config flag would make "cost
            # simulation is off" and "the DP failed" the same result — so the check is here, at the
            # one caller.
            if cfg.simulate_cost:
                cost_bench = cost_benchmark(runs.a, runs.c, frame, cfg, curves)

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
        # The tile VALUES carry no prose — "n/a" is the same abbreviation in Dutch, and the rest
        # are figures, so none of them needs a msgid. They are no longer plain strings either: a
        # figure is a `num()` dict formatted in the render locale (A6), and the `A → n/a`
        # comparison is an `_arrow` pair so its numeric half can be. `delta`/`extra` carry words
        # ("/ day", "throughput") and stay `_msg` pairs with their figures riding as params.
        ss_str = _fmt_pct(_self_sufficiency(rec))
        kpis = [
            {"title": "GRID IMPORT SAVED", "value": "n/a", "unit": "kWh", "delta": ""},
            {"title": "SELF-SUFFICIENCY", "value": _arrow(ss_str, "n/a"), "delta": ""},
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
        # The tile renders its unit itself, in its own smaller type, so this half carries the
        # figure WITHOUT the "kWh" suffix — the `kwh_bare` kind, rather than formatting the signed
        # kWh figure and stripping the suffix back off, which under A6 would mean stripping a
        # string this module no longer has.
        saved_value = num(metrics.saved_kwh, "kwh_bare")
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
            # "pp" (percentage points) is a UNIT, and it is the same abbreviation in Dutch, so it
            # stays literal for the same reason "kWh" does — see the figures block above. The
            # number is a signed integer count of points, hence `pct_signed` on an already-integer
            # value rather than a second signed-integer kind: the pattern rounds to one decimal,
            # which for a whole number of points is exact and prints "+10.0". That WOULD have
            # changed the English render, so it does not: `dec0_signed` keeps "+10 pp".
            ss_delta = _msg("%(pp)s pp", pp=num(ss_delta_pp, "dec0_signed"))
        kpis = [
            {"title": "GRID IMPORT SAVED", "value": saved_value, "unit": "kWh",
             "delta": saved_delta},
            # The ⓘ exists because the left half is NOT the figure the household card shows, and
            # the two sit on one screen a scroll apart. Both are `1 − import/load` over the same
            # window on the same load; they differ ONLY in the numerator — the card uses the
            # METERED import, this tile uses run A's simulated one, which the §7.1 note above
            # explains is systematically lower (the hourly grid nets out within-interval
            # import/export overlap). On the local dataset over six months that is 1366 vs 1304
            # kWh, i.e. 44% on the card against 47% here. Without the ⓘ a reader has no way to
            # tell that apart from a bug, so the blurb names the difference rather than leaving
            # them to find it. The blurb carries no runtime figures, so it is a plain `_N` msgid
            # that the template's `_()` looks up at render time — the same shape `title` uses.
            # Not an `_msg` pair: those are for sentences with values interpolated into them, and
            # the ⓘ's data-* attribute takes a string. ONE paragraph, because ha_fetch.js sets
            # the body with `textContent` into a single <p> — a newline would render as a space,
            # so every existing blurb is one paragraph and this one matches.
            {"title": "SELF-SUFFICIENCY",
             "value": _arrow(ss_base_str, ss_batt_str),
             "delta": ss_delta,
             "info_title": _N("Self-sufficiency"),
             "info_body": _N(
                 "The share of your household consumption met without drawing from the grid: "
                 "1 − grid import ÷ consumption. The left figure is the baseline — what this same "
                 "period would have looked like without a battery — and the right figure is the "
                 "simulated result with the battery you configured. Both come from the "
                 "simulation, so the two are a like-for-like comparison. This is why the left "
                 "figure can differ by a point or two from the self-sufficiency shown for your "
                 "household higher up the page: that one is measured straight from your meter. "
                 "Your meter records importing and exporting at separate moments within the same "
                 "hour, whereas the simulation works in whole intervals, so those partly cancel "
                 "out and it reproduces slightly less grid import. Comparing your measured figure "
                 "against a simulated one would overstate what the battery adds."
             )},
            # `delta` and `extra` carry WORDS ("/ day", "throughput"), so they are `_msg` pairs;
            # their figures ride as params and are formatted in the render locale like every other.
            {"title": "EQUIVALENT FULL CYCLES",
             "value": num(metrics.efc, "count") if metrics.efc is not None else "n/a",
             "delta": (_msg("%(n)s / day", n=num(metrics.cycles_per_day, "dec2"))
                       if metrics.cycles_per_day is not None else ""),
             "extra": _msg("%(kwh)s throughput", kwh=_fmt_kwh(metrics.throughput_kwh))},
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

        # The resolution-loss explanation, built ONCE here and used TWICE: as the ⓘ on the "Grid
        # import, no battery" row below (this is the figure it is about — the row is where a reader
        # meets the simulated import and wonders why it is not the meter's) and as the caveat in
        # the list further down. One msgid rather than two near-identical ones: the sentences would
        # drift apart under editing, and a translator would have to render the same explanation
        # twice. §7.1 asks for the difference to be "labelled as resolution loss"; the caveat is
        # where it is stated unprompted, the ⓘ is where it is available at the figure itself.
        #
        # None below the 1 kWh threshold: the two figures then print identically, and neither an
        # ⓘ nor a caveat should point at a difference the reader cannot see.
        resolution_loss = rec.imp_total - metrics.baseline_import_kwh
        resolution_loss_msg = None
        if round(resolution_loss) >= 1:
            resolution_loss_msg = _msg(
                "Your meter recorded %(meter)s imported over this period; the simulation's "
                "no-battery baseline is %(baseline)s. The difference "
                "of %(difference)s is energy that flowed both into and out of your "
                "house within a single %(res)s interval, which data at this resolution cannot "
                "see. Everything under Energy savings is computed from the simulated baseline, so "
                "that the battery and no-battery cases are built from the same information; the "
                "figures above it are as your meter recorded them. That is why the two sets of "
                "numbers do not match exactly.",
                meter=imp_str,
                baseline=_fmt_kwh(metrics.baseline_import_kwh),
                difference=_fmt_kwh(resolution_loss),
                res=res_msg,
            )

        energy_breakdown = [
            {"label": "Grid import, no battery",
             "value": _fmt_kwh(metrics.baseline_import_kwh),
             # `info_title` is the row's own label; the body is the shared pair above. Omitted
             # entirely when there is no discrepancy, so the ⓘ appears only when it has something
             # to say (the template branches on `info_body`).
             **({"info_title": _N("Grid import, no battery"),
                 "info_body": resolution_loss_msg} if resolution_loss_msg else {})},
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
            secondary.append({"label": "Self-consumption ratio",
                              "value": _arrow(sc_base, sc_batt)})
        secondary.append({
            "label": "Grid export",
            "value": _arrow(_fmt_kwh(metrics.baseline_export_kwh),
                            _fmt_kwh(metrics.battery_export_kwh)),
        })
        # "Intervals battery was full / empty" omitted — needs a SoC-bound comparison the metrics
        # layer does not compute yet; omitted rather than guessed.

    # ── Caveats (§2.4). Each is a `_msg` (msgid, params) PAIR, not a formatted string: a sentence
    # assembled here with an f-string is a msgid `pybabel extract` cannot see, so the template's
    # `_()` around it matched nothing and Dutch readers got all of these in English. The constant
    # text is the msgid; the figures ride alongside and are substituted after translation
    # (_msg's docstring, and templates/_msg.html).
    #
    # Order: reconstruction reliability, price granularity (and the §6.16 pricing-uncertainty width,
    # which is the same fact stated in euros), then the run-specific notes (negative saving, SoC
    # drift, self-sufficiency clamp), then the standing note stating the parameter set.
    caveats: list[dict] = []
    if rec.clamped_frac > CLAMP_UNRELIABLE_FRAC:
        caveats.append(_msg(
            "Reconstructed household load was negative in a large share of intervals and clamped "
            "to zero (%(discarded)s discarded against %(exported)s exported). This "
            "usually means solar export the PV sensor did not report, or an unmapped battery — "
            "so the load and self-sufficiency figures here are unreliable.",
            discarded=_fmt_kwh(rec.clamped_kwh),
            exported=exp_str,
        ))
    if metrics is not None:
        # §7.1's own instruction: "Report the observed import alongside it, with the difference
        # labelled as resolution loss." The band above shows the METER's import; the Energy savings
        # section below shows run A's SIMULATED no-battery import, which is smaller by the energy
        # that flowed both ways inside a single interval — the reconstructed load nets that out and
        # no simulated battery can recover it. Two grid-import numbers on one panel read as a
        # contradiction unless the difference is named, so it is named here in kWh.
        #
        # The message itself is built where `energy_breakdown` is, because the "Grid import, no
        # battery" row's ⓘ carries the SAME pair — see there, including the 1 kWh threshold that
        # makes it None when the two figures print identically. `None` here means there was no
        # visible discrepancy to explain, not that the caveat was forgotten.
        if resolution_loss_msg is not None:
            caveats.append(resolution_loss_msg)
        # The self-sufficiency counterpart of the caveat above, and raised on the SAME condition:
        # the two are one discrepancy expressed in two units. The one above reconciles the two
        # grid-import figures in kWh; this one reconciles the two self-sufficiency PERCENTAGES,
        # which is the pair a reader actually compares (44% in the household card against 47% in
        # the tile) and which the kWh caveat never names. Both figures are quoted so the caveat
        # stands on its own rather than asking the reader to scroll and subtract.
        #
        # Gated additionally on both percentages being computable AND actually printing
        # differently: when they round to the same integer there is no visible discrepancy to
        # explain, and a caveat about one would send the reader looking for a difference that is
        # not on the screen.
        if (resolution_loss_msg is not None
                and metrics.self_sufficiency_baseline is not None):
            measured_ss = _self_sufficiency(rec)
            simulated_ss = max(0.0, metrics.self_sufficiency_baseline)
            if round(100 * measured_ss) != round(100 * simulated_ss):
                caveats.append(_msg(
                    "For the same reason, the self-sufficiency of %(measured)s shown for your "
                    "household above differs from the %(simulated)s the Energy savings tile uses "
                    "as its no-battery baseline. The first is measured from your meter; the "
                    "second is what the simulation reproduces without a battery, and it is the "
                    "one the battery is compared against so that both sides of that comparison "
                    "rest on the same information.",
                    measured=_fmt_pct(measured_ss),
                    simulated=_fmt_pct(simulated_ss),
                ))
    price_lost = normalize.price_granularity_lost(dataset.frames, rec.grid_s)
    if price_lost["lost"]:
        native = _res_msg(price_lost["native_resolution_s"])
        caveats.append(_msg(
            "Spot prices are recorded every %(native)s but the run is %(res)s, so the battery "
            "acted on an averaged price and could not chase within-interval swings.",
            native=native,
            res=res_msg,
        ))
    # §6.16's pricing-uncertainty width (D5′, D9). Placed HERE, right after the price-granularity
    # caveat, because the two are the same fact read on two sides: that one says the DISPATCH acted
    # on an averaged price, this one says the BILL is uncertain by a stated amount for the same
    # reason. Emitted before the run-specific notes so the pair stays adjacent, and it does not wait
    # for the euro block below because it belongs beside its sibling rather than beside the tariff
    # notes. `price_bracket` is already None whenever this must not appear at all — cost simulation
    # off, hourly settlement (D10), or no intra-interval spread anywhere — so this `is not None` is
    # the whole gate; see `_price_bracket`.
    if price_bracket is not None:
        # `num(_, "eur")` prints WHOLE euros (`_NUM_KINDS`, deliberately: appendix A's 2027 tariffs
        # do not support a figure to the cent). So a width under half a euro would print "€ 0" —
        # a sentence claiming a worst case of nothing, which is exactly what D5′'s None-not-zero
        # rule exists to avoid saying. Suppressed on the same rounding the pattern applies, the way
        # `WATERFALL_DISPLAY_EPS_EUR` drops a row that would print "€ 0"; `<=` because a width of
        # exactly 0.5 rounds half-to-even to "€ 0" as well.
        if price_bracket.width_eur > WATERFALL_DISPLAY_EPS_EUR:
            # WORDING, and every clause of it is load-bearing:
            #
            #  * "worst case" (D9). The number is the extreme over where inside each hour the
            #    energy sat, not a typical error. A typical error would be far narrower, because
            #    errors across thousands of hours partially cancel — but the independence that
            #    claim needs is not supportable (household load has strong intra-hour structure and
            #    battery charging is deliberately timed), so the narrower figure is not offered.
            #    "give or take" or "±  typically" would assert exactly what was not established.
            #  * It bounds HOW FAR OFF THE SAVING COULD BE, and says SAVING rather than "the euro
            #    figures on this page". The scope matters and the narrower claim is the true one:
            #    `width_eur` is `(saved_high − saved_low)/2`, and all three evaluations are
            #    DIFFERENCES of two bills. Each individual bill — also on this page, in the KPI
            #    sentence and in the waterfall rows — moves by MORE than that, because the two
            #    bills' errors partly cancel in the difference (measured on the `_bracket_dataset`
            #    fixture: width €2.46, against a half-range of €2.72 on the battery bill alone).
            #    A sentence sold as a worst case must not be an understatement of what it names, so
            #    it names only the quantity the number actually bounds.
            #  * It is deliberately NOT written as "your saving is X ± Y". The width can exceed the
            #    saving itself (measured: three of seven synthetic scenarios, and the one-day test
            #    fixture gives €2.46 against a saving of €0.45), which a ± phrasing renders as
            #    absurd, and which a reader would reasonably take as "so I might lose money" — a
            #    much stronger claim than a worst-case bound on the PRICING supports. Naming the
            #    saving as the thing that SHIFTS keeps that separation: it states a displacement,
            #    not an interval around the figure.
            #  * The reason is given in the user's terms — their data is hourly, the market moves
            #    every 15 minutes — rather than as "spot_max − spot_min".
            width = num(price_bracket.width_eur, "eur")
            # The fraction counts INTERVALS with a spread, not energy and not euros, so the copy
            # says "hours", never "of the saving" or "of your electricity". Two wordings rather
            # than a substituted phrase, for the reason the SoC-drift pair above gives.
            #
            # BOTH wordings say PRICED hours. The denominator of `bracketed_fraction` is priced
            # intervals, so a window that is half unpriced and half spread-carrying has a fraction
            # of exactly 1.0 and takes the whole-window branch — where "every hour" would claim
            # something about hours that carry no price at all. "every priced hour" is the same
            # length and reads no worse, so the common branch carries the qualifier too.
            #
            # The 0.95 threshold: below it the window genuinely straddles a resolution change
            # (§6.16's D2 case — EPEX moved to quarter-hourly settlement on 2025-10-01, so a window
            # crossing that date is part hourly and part not), and saying "your window" would
            # overstate the reach. At or above it the handful of exceptions are single held or
            # gap-filled hours, which are not worth a qualifying clause the reader then has to
            # place. The percentage is only shown in the partial branch, where it is informative.
            if price_bracket.bracketed_fraction < 0.95:
                caveats.append(_msg(
                    "Your energy data is hourly, but the electricity market prices every 15 "
                    "minutes, so for %(share)s of the priced hours here the simulation cannot see "
                    "when inside the hour your electricity actually moved. In the worst case — "
                    "every one of those hours landing on its least favourable quarter — that "
                    "shifts the saving shown on this page by %(width)s. Treat it as a bound on "
                    "how far the pricing could be off, not as a typical error: a real hour will "
                    "sit somewhere inside its quarters, and this run cannot tell you where.",
                    share=_share_pct(price_bracket.bracketed_fraction),
                    width=width,
                ))
            else:
                caveats.append(_msg(
                    "Your energy data is hourly, but the electricity market prices every 15 "
                    "minutes, so the simulation cannot see when inside each priced hour your "
                    "electricity actually moved. In the worst case — every priced hour landing on "
                    "its least favourable quarter — that shifts the saving shown on this page by "
                    "%(width)s. Treat it as a bound on how far the pricing could be off, not as a "
                    "typical error: a real hour will sit somewhere inside its quarters, and this "
                    "run cannot tell you where.",
                    width=width,
                ))
    if negative_saving and metrics is not None:
        # §7.2 items 9 and 10. Without PV the battery's value is in the price SPREAD — a euro
        # quantity — so an energy-only run measures the cost of moving the energy and none of the
        # benefit. Say that plainly rather than presenting a negative kWh figure as a verdict.
        #
        # TWO msgids, branching on whether euros were actually computed. The energy-only wording
        # ends "a euro quantity this energy-only run does not compute", which with cost simulation
        # ON is simply false — the COST SAVINGS section directly below states that very quantity,
        # and a caveat contradicting the section beneath it is worse than no caveat. So the
        # cost-on variant keeps the explanation of WHY the kWh figure is negative and points at the
        # euro figure instead of disclaiming it.
        #
        # This does not breach fixture 18: the invariant is over the ENERGY FIGURES, and §2.4
        # itself says the caveats box gains euro-qualifying text when euros are modelled. The
        # cost-OFF wording is untouched, which is what a reader comparing the two modes checks.
        if cost is None:
            caveats.append(_msg(
                "This battery imported %(extra)s MORE from the grid than "
                "the same household without one. That is a real result, not an error: round-trip "
                "losses and standby cost energy, and the value of charging cheaply and "
                "discharging when prices are high is a price spread — a euro quantity this "
                "energy-only run does not compute. An energy-only run cannot tell you whether the "
                "battery is worth buying.",
                extra=_fmt_kwh(abs(metrics.saved_kwh)),
            ))
        else:
            caveats.append(_msg(
                "This battery imported %(extra)s MORE from the grid than the same household "
                "without one. That is a real result, not an error: round-trip losses and standby "
                "cost energy. The battery's value is in the price spread — charging cheaply and "
                "discharging when prices are high — which is a euro quantity, so read the cost "
                "savings below rather than this figure to judge whether it is worth buying.",
                extra=_fmt_kwh(abs(metrics.saved_kwh)),
            ))
    if metrics is not None and metrics.soc_drift_significant:
        # §6.11's SoC drift correction. Without a cost model there is no median import price, so
        # the euro valuation (`soc_delta_value_eur`) is null and is not shown — only the kWh.
        #
        # TWO msgids rather than one with a `%(direction)s` hole. "more"/"less" was previously
        # substituted as a bare word, which is unextractable and, worse, untranslatable in place:
        # a language that inflects the adjective or puts it elsewhere in the clause cannot express
        # either sentence by filling a one-word slot in the other's word order.
        drift = _fmt_kwh(abs(metrics.soc_delta_kwh))
        if metrics.soc_delta_kwh > 0:
            caveats.append(_msg(
                "The battery ended the period %(drift)s more "
                "charged than it started. That residual energy is not part of the saving above and "
                "is large relative to it, so the headline figure would move if the period ended at "
                "a different state of charge.",
                drift=drift,
            ))
        else:
            caveats.append(_msg(
                "The battery ended the period %(drift)s less "
                "charged than it started. That residual energy is not part of the saving above and "
                "is large relative to it, so the headline figure would move if the period ended at "
                "a different state of charge.",
                drift=drift,
            ))
    if clamp_fired:
        # §2.3a's display clamp, on EITHER half of the tile. Only the presentation is clamped; the
        # metric itself is negative. Worded to cover both sides rather than naming the battery one:
        # the baseline half is now run A's simulated figure and can clamp too (the same round-trip
        # and drift mechanics apply to a household with an EXISTING battery in the reconstruction).
        caveats.append(_msg(
            "Self-sufficiency came out below zero and is shown as zero. Grid "
            "import exceeded the reconstructed household load over this period — the battery ended more "
            "charged than it started, or round-trip losses consumed imported energy. It evens out "
            "over full charge/discharge cycles; select a longer period to see it."
        ))
    # §2.5(b) / §7.3 check 18: the SOFT block. A user who selected an unsupported phase topology
    # and continued is running the 3-phase model, and `topology.approximated` records that choice.
    # The spec requires the caveat to be PINNED to the results panel, not merely shown once in the
    # dialog they clicked through — so it is emitted here, on every result computed under it.
    #
    # What the approximation costs: the run is numerically identical to the 3-phase case (fixture
    # 12), because v1 has no per-phase model at all. What it cannot capture is the per-phase power
    # limit — a 1-phase battery cannot exceed one phase's fuse rating however the load is spread.
    if cfg.topology.approximated:
        caveats.append(_msg(
            "Your battery is wired across the phases in a way version 1 does not model, so this "
            "run uses the 3-phase approximation you accepted. Because a smart meter nets across "
            "phases the energy result should be close; what is not modelled is the per-phase "
            "power limit, which a 1-phase battery cannot exceed however the load is distributed."
        ))

    # ── The EURO caveats (§2.4: "the caveats that qualify a euro figure … appear only with cost
    # simulation on, because there is no euro figure to qualify"). Placed before the standing
    # parameter-set note so that note stays last, as it was.
    if cost is not None:
        # What the bill IS, and what it is not. §6.10 excludes vastrecht, netbeheerkosten and the
        # vermindering energiebelasting because none of them responds to consumption, so they
        # cancel exactly out of a before-and-after comparison — but the two figures beside the
        # tile are labelled "without a battery" and "with one", which a reader may take for two
        # invoice totals. They are not, and the difference is large (the fixed part of a Dutch
        # bill is on the order of several hundred euros a year), so it is stated rather than left
        # to be discovered.
        caveats.append(_msg(
            "The euro figures count only the part of your bill that responds to what you do with "
            "your electricity. Standing charges — vastrecht, netbeheerkosten and the "
            "vermindering energiebelasting — are left out, because they do not change when a "
            "battery is installed and would cancel out of the comparison anyway. So these are "
            "not two invoice totals; they are the two halves of your bill a battery can move."
        ))
        # Appendix A is explicit that the 2027 tariffs are unpublished and that the
        # terugleverkosten rate shipped is a PLACEHOLDER. §2.4's own framing of the two-section
        # split is that a euro figure is "that data plus a contract model assembled from
        # unpublished 2027 tariffs", and the panel should say so where the euros are.
        caveats.append(_msg(
            "This is priced under the post-2027 regime, in which net metering no longer exists. "
            "Several of those tariffs are not yet published — the terugleverkosten rate in "
            "particular is a placeholder — so the euro figures move with the contract you "
            "entered in the parameters panel and should be read as a scenario rather than as a "
            "quotation."
        ))
        # §6.5's feed-in compensation is NOT clamped per interval, which is the point of the
        # model, but it is the single assumption most likely to surprise: exporting can COST
        # money. Stated only when it actually bit, so the box does not carry a general warning
        # about a case this run did not reach.
        if any(line["label"] == "lost_feedin_compensation" and line["eur"] > 0
               for line in cost["waterfall"]):
            caveats.append(_msg(
                "Some of the export this battery avoided would have earned a NEGATIVE net "
                "amount — the terugleverkosten on it exceeded the compensation — so not "
                "exporting is counted as a gain rather than as a loss. That is how the 2027 "
                "regime works and not an error in the arithmetic."
            ))
        # The per-interval / period-aggregate split behind `monthly[].saved_eur`, stated only in
        # the window where it actually matters. `costs.py` cannot allocate the top-up across
        # intervals without inventing a convention, so the monthly bars omit it and their sum
        # falls short of the headline by exactly that amount.
        if abs(cost_c.topup_eur - cost_a.topup_eur) > WATERFALL_DISPLAY_EPS_EUR:
            caveats.append(_msg(
                "The statutory feed-in floor paid out over this period. It is assessed over a "
                "whole billing period rather than hour by hour, so it appears as its own line in "
                "the money breakdown and is left out of the monthly savings chart, whose bars "
                "therefore add up to slightly less than the headline figure."
            ))

    # State the parameter set the figures were computed under. Stated rather than hidden — a
    # figure computed from an unstated parameter set is the kind of number that propagates
    # unchallenged.
    #
    # The caveats carry no literal "%" sign — the round-trip efficiency reads "0.90 round-trip"
    # rather than "90% round-trip". That began as a workaround for the old `newstyle=True`
    # %-formatting, which read "% r" as a conversion specifier and rendered "90{}ound-trip"; it is
    # no longer needed (`app/i18n.install_for` now uses `newstyle=False`, so a literal "%" is
    # inert). The wording is kept because changing it would change the English text, which this
    # restructuring must not do.
    caveats.append(_msg(
        "Computed for the battery configured in the parameters panel — "
        "%(capacity)s kWh usable, "
        "%(charge_kw)s/%(discharge_kw)s kW, "
        "%(efficiency)s round-trip efficiency, "
        "charge %(charge_policy)s / "
        "discharge %(discharge_policy)s.",
        capacity=_g(cfg.battery.usable_capacity_kwh),
        charge_kw=_g(cfg.battery.max_charge_kw),
        discharge_kw=_g(cfg.battery.max_discharge_kw),
        efficiency=_g(cfg.battery.roundtrip_efficiency),
        charge_policy=_policy_key(cfg.policy.charge_policy),
        discharge_policy=_policy_key(cfg.policy.discharge_policy),
    ))

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
        # An explicit range is stated, not inferred: `_period_selected_for` maps a SPAN back to the
        # nearest preset and so can only ever answer with a preset. See PERIOD_SELECTED_CUSTOM.
        "period_selected": (
            PERIOD_SELECTED_CUSTOM if custom_range else _period_selected_for(dataset, eff)
        ),
        # The window's two ends as `<input type=date>` values (YYYY-MM-DD), so the selector can put
        # the applied range back into the fields it hides by default. The EFFECTIVE window, after
        # clamping to coverage — the fields then show what was actually simulated rather than what
        # was typed, which is the honest answer when a requested end lies past the data.
        "period_start_date": eff[0].date().isoformat(),
        "period_end_date": eff[1].date().isoformat(),
        "data_summary": data_summary,
        "kpis": kpis,
        "energy_breakdown": energy_breakdown,
        "secondary": secondary,
        "chart": _monthly_import(rec),
        "caveats": caveats,
        # The window request the lazy benchmark fetch should re-send, as a JSON string the template
        # drops straight into a data-* attribute. It is the EFFECTIVE window (what was actually
        # reconciled and simulated), stated as an explicit start/end rather than as the preset the
        # caller may have used — so the box is computed over exactly the window the rows beside it
        # describe, even where reconciliation narrowed the requested one. `resolve_window` clamps
        # both ends to coverage, so re-sending an already-clamped window is a no-op.
        "benchmark_request": json.dumps(
            {"start": eff[0].isoformat(), "end": eff[1].isoformat()}
        ),
        # §4.5's `cost`, NULL WHOLESALE when `simulate_cost` is off — not an object of null
        # fields, and in particular not a waterfall of eight null entries. The template renders
        # the whole COST SAVINGS section under one `{% if results.cost %}`, which is the
        # granularity §4.5 says the UI actually branches at.
        "cost": cost,
        # §4.5's `monthly[].saved_eur`, null under the same toggle and never 0.0 (fixture 19).
        # Carried beside the kWh series the chart already had, in the same bucket order, so the
        # two chart OPTIONS §2.4 asks for are two views of one bucketing rather than two series
        # that could disagree about which month a bar belongs to.
        "monthly_saved_eur": monthly_saved_eur,
        # §4.5's `simulate_cost`, so a consumer reading this view-model can tell "cost is null
        # because the user turned it off" from "cost is null because there was nothing to price".
        "simulate_cost": bool(cfg.simulate_cost),
        # §6.16's pricing-uncertainty width — a `PriceBracket` or None. Deliberately a TOP-LEVEL
        # key and NOT a `price_bracket` entry inside `cost`: D5′ dropped the §4.5 result block
        # (with its low/central/high public fields and its null-when-off contract) in favour of
        # reporting only the width, as a caveat beside the saving. §4.5's `cost` object stays
        # exactly the shape the spec fixes, so nothing here can perturb the figures already on
        # screen. None means "no width to state", never "the width is zero" — see
        # `_price_bracket`. The template does not read this key: it is consumed HERE, by the
        # caveat built beside the price-granularity one, and carried on the view-model so a test
        # (and a future consumer) can assert the number rather than parse it back out of a
        # sentence.
        "price_bracket": price_bracket,
    }

    # §2.4's benchmark box. Absent — not zeroed — when there was no simulation to bound; the
    # template guards on `results.benchmark`, so an absent key simply omits the card rather than
    # rendering a box of invented numbers.
    if bench is not None:
        result["benchmark"] = _benchmark_block(bench, cfg.eta_d)
    # §2.4's money benchmark box, on the same absent-not-zeroed convention and gated by BOTH
    # `with_benchmark` and `simulate_cost` (see the run-E call site). §4.5's `benchmarks.cost` is
    # null wholesale without cost simulation; here that is an absent key, exactly as
    # `benchmarks.energy` is absent when the DP did not run.
    if cost_bench is not None:
        result["cost_benchmark"] = _cost_benchmark_block(cost_bench, cfg)

    # Short-window guard (§7.4): below min_annualisation_days annualisation is disabled. We annualise
    # nothing here; the flag + message let the template show the §2.4 info box. Uses the EFFECTIVE
    # span (what the run actually covers), not the requested one.
    span_days = (eff[1] - eff[0]).days
    if span_days < min_annualisation_days:
        result["annualisation_disabled"] = True
        # A COUNTED message: `min_annualisation_days` drives the "days" plural. It is 90 today, so
        # only the plural form is ever selected — but the count is what gettext needs to pick a
        # form, and hard-coding the plural would break the moment the constant changes or a
        # language with a different plural rule is added.
        result["annualisation_message"] = _msg_n(
            "Annualised projection is disabled for ranges under %(n)s day. "
            "Battery savings are strongly seasonal; scaling a short window to a year can overstate "
            "annual savings by a factor of roughly 2–3. Select 6 months or 1 year to see an annual "
            "figure.",
            "Annualised projection is disabled for ranges under %(n)s days. "
            "Battery savings are strongly seasonal; scaling a short window to a year can overstate "
            "annual savings by a factor of roughly 2–3. Select 6 months or 1 year to see an annual "
            "figure.",
            min_annualisation_days,
            n=num(min_annualisation_days, "count"),
        )

    return result
