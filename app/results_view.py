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

What is NOT emitted this increment (later phases):
  * the §6.12 COST benchmark (run E) and any euro figure — `simulate_cost` is false.
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
    results_from(dataset, window) -> dict | None   the panel-③ energy-savings view-model, or None.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np

from app.dataset import LoadedDataset
from app.domain import normalize
from app.domain.benchmark import EnergyBenchmark, _capture_ratio, energy_benchmark
from app.domain.metrics import SOC_DRIFT_WARN_FRAC, EnergyMetrics, energy_metrics
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
from app.data_view import _fmt_res, _res_msg
from app.i18n import msg as _msg, msg_n as _msg_n, num
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

# The label the selector highlights, keyed off the preset the window was resolved from. Kept as the
# wireframe default ("1 year") for the full-coverage / explicit-range case.
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


def results_from(
    dataset: LoadedDataset,
    window: tuple[datetime, datetime],
    *,
    cfg: SimulationConfig | None = None,
    with_benchmark: bool = False,
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
    if frame is not None and frame.intervals > 0:
        # `rec` and `frame` come from the same reconcile_grid over the same window, so `pv_mask`
        # (built against `rec`) indexes `frame`'s arrays too — same length, same interval starts.
        runs = run_all(frame, cfg)
        metrics = energy_metrics(runs, frame, cfg, pv_mask=pv_mask)
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
            {"title": "SELF-SUFFICIENCY",
             "value": _arrow(ss_base_str, ss_batt_str),
             "delta": ss_delta},
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
    # Order: reconstruction reliability, price granularity, then the run-specific notes (negative
    # saving, SoC drift, self-sufficiency clamp), then the standing note stating the parameter set.
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
        # Raised only when the gap rounds to at least 1 kWh: below that the two figures print
        # identically and a caveat explaining a difference the reader cannot see would be noise.
        resolution_loss = rec.imp_total - metrics.baseline_import_kwh
        if round(resolution_loss) >= 1:
            caveats.append(_msg(
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
    if negative_saving and metrics is not None:
        # §7.2 items 9 and 10. Without PV the battery's value is in the price SPREAD — a euro
        # quantity — so an energy-only run measures the cost of moving the energy and none of the
        # benefit. Say that plainly rather than presenting a negative kWh figure as a verdict.
        caveats.append(_msg(
            "This battery imported %(extra)s MORE from the grid than "
            "the same household without one. That is a real result, not an error: round-trip "
            "losses and standby cost energy, and the value of charging cheaply and discharging "
            "when prices are high is a price spread — a euro quantity this energy-only run does "
            "not compute. An energy-only run cannot tell you whether the battery is worth buying.",
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
        "period_selected": _period_selected_for(dataset, eff),
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
    }

    # §2.4's benchmark box. Absent — not zeroed — when there was no simulation to bound; the
    # template guards on `results.benchmark`, so an absent key simply omits the card rather than
    # rendering a box of invented numbers.
    if bench is not None:
        result["benchmark"] = _benchmark_block(bench, cfg.eta_d)

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
