# Data summary interstitial panel

## Task Specification

**User's original prompt (verbatim):**

> update for the UX/wireframe specs & app code. After the user validates their data series
> (click fetch button), we'd like an interstitial "summary of your data" panel before they go
> on to enter their battery details.
>
> the summary should display the data results that can be computed without the battery
> information (including, but not limited to, the total energy consumed/produced from the grid,
> self-sufficiency)

Add a "summary of your data" panel that appears after the data fetch (panel ①) and before the
battery-parameter panel (panel ②). It presents figures derivable from the household's data alone
— no battery, no policy, no pricing. Examples named by the user: total grid energy
consumed/produced, self-sufficiency. Scope spans both the specification package (`specs/`) and
the running app (`app/`).

## Current State (pre-change, established by exploration)

- The app is at the **data-import increment**. After a browser Fetch (ha_fetch.js), the page
  reloads and panel ① renders the real persisted dataset via `app/data_view.py` +
  `app/domain/normalize.py` (grid selection + reconciliation metadata). Panels ② and ③ still
  render the *static* sample view-model (`app/sample_data.py`); there is **no simulation domain
  layer yet** (no `simulate_core`, no metrics module).
- The panels are three stacked stepper sections in `templates/index.html`
  (`_setup_band`, `_panel_data`, `_panel_params`, `_panel_results`). Panel ① ends with a
  "Next: parameters →" button.
- Load reconstruction (§6.3: `load = import − export [+ pv]`) and the energy metrics
  (§6.11: `self_sufficiency = 1 − import/load`, `self_consumption`, totals) are **specified but
  not yet implemented**. The frames carry per-interval kWh values already (energy series), so the
  battery-free aggregates ARE computable from the persisted dataset now.
- Spec §2 (`02-ux-wireframes.md`) defines the setup band + three panels; §2.4 documents panel ③.
  §12 (`12-metrics-and-benchmarks.md`) defines the metrics and marks which are battery-free.

## High-Level Decisions

Settled with the user via clarifying questions (2026-07-24):

1. **Placement — unnumbered band below panel ①, above panel ②.** Not a numbered stepper step:
   it is a "here's what we found" interstitial, modelled on the setup band (always-expanded, no
   collapse-to-summary, no `[?]`/pending semantics, no CTA of its own). This avoids renumbering
   Parameters/Results across the specs and templates. It renders **only once a real dataset is
   loaded** — the empty state has nothing to summarise, so before the first fetch the band is
   absent (like the results it foreshadows).
2. **Content — all four figure groups**, all battery-free (§6.11 energy metrics + §6.3 load
   reconstruction):
   - Grid import/export totals (kWh over the window).
   - Self-sufficiency (`1 − import/load`).
   - Solar & consumption: total PV production, reconstructed household load, self-consumption
     ratio (`1 − export/pv`). PV-dependent rows shown only when `has_pv` / when PV data exists.
   - Price/window context: coverage span & days, average / min / max spot price over the window.
   All are figures a real controller/simulator does not need battery inputs to produce; they are
   exactly the §6.11 "Energy" row plus the raw meter/price aggregates behind it.
3. **Implementation — spec + UI shell with a sample view-model.** Matches the scaffold's current
   "shape first" posture (panels ②/③ still render `sample_data.py`). The real battery-free
   computation (a §6.3/§6.11 domain slice over the persisted frames) is deferred to a later
   increment; this task lands the spec text and the panel/template driven by sample numbers, so
   the intended shape is on record and reviewable without pulling the domain layer forward.

## Requirements Changes

**2026-07-24 — pre-existing battery accounted for in the grouping (user follow-up).**

> note that the user may already have a pre-existing battery, such that home load and
> self-consumption are derived from that data too. the grouping should take it into account

The user may already own a battery whose sensors are mapped into the `battery_charge` /
`battery_discharge` slots (§4.1, §5). §6.3 load reconstruction then *strips* that battery
(`load = imp − exp + pv + batt_dis − batt_chg`), so the reconstructed household load and the
self-consumption ratio are **derived from the existing battery's data too** — they are the true
behind-the-meter demand net of that battery, not a no-battery quantity.

Consequences for this task:

- **Framing.** Drop "battery-free" as the organising label. The honest contract is: figures
  computable **from the household's own recorded data — which may include a pre-existing
  battery — before the *simulated* battery is configured.** The distinction that matters is
  *existing/measured* battery (an input) vs. *simulated* battery (what panels ②/③ add), not
  "no battery at all".
- **Grouping.** When `battery_charge` / `battery_discharge` are present, surface the existing
  battery as its own group (observed charge/discharge throughput over the window), and label the
  household-load and self-consumption rows as **net of your existing battery** so the reader
  knows the reconstruction used it. When those slots are absent, that group is omitted and the
  labels carry no such qualifier (the omit-don't-zero rule from §2.4 again).
- Cross-refs: §6.3 (the `batt_chg`/`batt_dis` strip), §4.1 (the optional battery slots),
  §6.15 / open-question §8.6 (existing battery installed mid-window → reconstruction consistency,
  a known limitation to acknowledge but not solve here).

## Confirmations (2026-07-24)

- **(a)** The band is hidden in the empty/pre-fetch state and shown only once a dataset is loaded.
- **(b)** The sample view-model demos the **existing-battery variant**: `battery_charge` /
  `battery_discharge` populated, the "Your existing battery" throughput group rendered, and the
  Household/Solar rows labelled "net of your existing battery". (This diverges from the current
  `sample_data.py`, which leaves those two slots unmapped — the summary sample carries its own
  battery figures rather than re-deriving the mapping sample.)

## Files Modified

Specs:
- `specs/02-ux-wireframes.md` — new **§2.3a "The data summary band — Your data at a glance"**
  (wireframe + prose: band-not-panel, the shown-figures table, the omit-don't-zero rule, and the
  existing-vs-simulated battery distinction with "net of your battery"). §2.1 overall-layout ASCII
  updated to show the band's position between ① and ②.
- `specs/04-state-machine.md` — §3.4 note: the summary band, like the setup band, has no focus
  state; absent until `DATA_READY`, re-renders on `RELOAD_DATA`.
- `specs/12-metrics-and-benchmarks.md` — §6.11 note: the self-sufficiency / self-consumption /
  totals subset of the Energy row needs no simulated battery and is surfaced in the band; `efc`,
  `saved_kwh`, `saved_pct` stay in panel ③. Cross-refs the existing-battery net-of labelling.

App:
- `app/templates/_panel_summary.html` — **new**. The band markup (Grid / Household / Solar /
  existing-battery / price groups), each optional group guarded for omit-don't-zero.
- `app/templates/index.html` — include `_panel_summary.html` between ① and ②, gated on
  `data_summary` being present; header docstring updated.
- `app/sample_data.py` — new `_data_summary()` sample view-model (existing-battery variant);
  exposed in `sample_view()`; module docstring notes main.py drops it in the empty state.
- `app/main.py` — `index()` drops `data_summary` from the context when no dataset is loaded, so
  the band is absent pre-fetch and present once data exists (numbers still sample this increment).
- i18n: `app/locales/messages.pot`, `nl` + `en` `.po`/`.mo` — new band strings extracted and
  translated (Dutch), en filled as identity; catalogs kept fuzzy-free.

Tests:
- `tests/test_data_summary.py` — **new**. Unit tests for the sample view-model shape (always-on
  groups, existing-battery variant, optional-group keys present for the template guards).
- `tests/test_smoke.py` — new assertion that the band is absent in the empty/pre-fetch state.

## Rationales and Alternatives

- **Unnumbered band, not a numbered panel** (user's choice): avoids renumbering
  Parameters/Results across specs + templates, and reads correctly as read-only context rather
  than a stepper step. Modelled on the setup band, differing only in that it is absent until data
  loads.
- **Spec + UI shell with sample numbers** (user's choice): matches the scaffold's posture (panels
  ②/③ still render `sample_data.py`); the real §6.3/§6.11 battery-free computation over the
  persisted frames is a later increment. A code comment in `main.py` flags this so the sample
  numbers over a real dataset are not mistaken for a bug.
- **Existing battery surfaced explicitly** (user's follow-up): §6.3 already strips a mapped
  existing battery when reconstructing load, so household/self-consumption figures are net of it.
  The band gives the existing battery its own throughput group and labels the reconstructed rows,
  keeping "the battery you have" distinct from "the battery we simulate" (panels ②/③).

## Obstacles and Solutions

- **i18n extraction dropped every `_N()` string.** First `pybabel extract` omitted `-k _N` (the
  repo's chrome marker), so `update` obsoleted all `sample_data.py` msgids and fuzzy-matched new
  short msgids onto existing translations (e.g. `Imported` stole `BESPAARDE NETAFNAME`), breaking
  `test_dutch_renders`. Fix: reverted the catalogs to HEAD, re-extracted with the documented
  `pybabel extract -F babel.cfg -k _N … --no-location`, ran `update … --no-fuzzy-matching` to stop
  the donor problem, then filled only the new empty msgstrs (Dutch for nl, identity for en). All
  original translations preserved; catalogs fuzzy-free.

## Current Status

Increment 1 (spec + UI shell) complete. Specs updated; band implemented as a spec + UI shell
driven by the sample view-model; hidden pre-fetch, shown once data loads; bilingual. Full test
suite passed (83 passed, HA-live test skipped — needs a real instance).

## Increment 2 — the real computation (2026-07-24)

**User's prompt (verbatim):**

> now let's actually implement the corresponding computations

Wire real, computed numbers into `data_summary` from the persisted frames, replacing the sample in
the loaded state. `tests/test_data_summary.py`'s shape assertions become the contract the computed
view-model must also satisfy.

### Decisions (confirmed with the user 2026-07-24)

1. **Reconstruction fidelity — per-interval align + clamp (§6.3).** Reconcile the grid energy
   series (import/export/pv/battery) onto the effective-window common grid per interval, apply the
   §6.3 balance `load = imp − exp + pv + batt_dis − batt_chg` per interval, clamp negatives to 0
   (counting them for a caveat), then sum. `self_sufficiency = 1 − import.sum()/load.sum()` uses the
   clamped load, matching §6.11. This is more faithful than sum-then-combine and the per-interval
   reconstruction is reusable when the full simulation lands.
2. **Partial coverage — sum over each series' own coverage.** Each total is computed over the
   intervals that series actually has within the effective window (matches how panel ① already
   derives the effective window via `normalize.effective_window`). Rationale for the mixed policy:
   the per-interval load reconstruction still needs the grid series on ONE aligned grid, so those
   are reconciled onto the effective window; the price aggregates (avg/min/max) and an optional
   short-coverage series use their own coverage rather than shrinking the whole window (an existing
   battery added mid-window must not truncate the grid totals — open question §8.6).

### Approach

- **New `app/summary_view.py`** — `data_summary_from(dataset) -> dict | None`, producing the exact
  shape `_data_summary()` returns (grid / household / solar / battery / price groups, `net_battery`
  flag, coverage/days), computed from the frames. Returns None when there is no simulatable grid
  (no covering energy series), so `main.py` omits the band as in the empty state.
- **Reconciliation helper** to sum an energy frame onto the effective-window grid (downsample =
  sum deltas per §6.2; a series already at/finer than the grid sums exactly; irregular → skip with
  a caveat). Reuses `normalize.effective_window` / `choose_grid`.
- **Formatting** kept in the view layer: thousands-separated kWh, integer-percent, €/kWh to 3 dp,
  matching the sample's presentation so the template is unchanged.
- **`main.py`** — in the loaded branch, replace the sample `data_summary` with
  `summary_view.data_summary_from(loaded)`; keep the empty-state drop.
- **Tests** — extend `tests/test_data_summary.py` with computed-view cases over synthetic frames
  (known totals, the existing-battery net-of variant, no-PV/no-battery/no-price omission, the
  negative-load clamp). The existing sample-shape tests stay as the shared contract.

### Files (planned)

- `app/summary_view.py` — new.
- `app/main.py` — call `summary_view.data_summary_from` in the loaded branch.
- `tests/test_data_summary.py` — add computed-view tests over synthetic datasets.
- `app/sample_data.py` — `_data_summary()` retained as the empty-state-free demo shape and the
  test contract; docstring notes the computed path now supplies real numbers when a dataset exists.

### Negative self-sufficiency — surfaced during implementation (2026-07-24)

Wiring real numbers exposed an edge the sample never hit: `self_sufficiency = 1 − import/load`
(§6.11) goes **negative** when grid import exceeds the reconstructed load over the window. With an
existing battery this is normal — a battery that ends the window more charged than it started (net
SoC drift), plus round-trip losses, means some imported energy went into the battery and was never
discharged to the load within the window.

Discussion with the user (verbatim prompts):

> let's take a step backward here. what does "self sufficiency" really mean? if there's a battery
> and it charges from the grid, that does not count as "self sufficiency"

> i'm tempted by option 3 -- it seems to me that even though the load may appear negative during
> one interval, the battery will later discharge and contribute to self sufficiency, such that over
> multiple charge/discharge cycles it balances out.

**Decision — option 3: keep the spec metric, clamp the display.** The user's balancing argument is
correct for a *cycle-balanced* window: charge returns as discharge, and `1 − import/load` lands in
a sane range. The residuals that keep it from fully cancelling — net SoC drift (§6.11 already flags
this) and round-trip losses — are genuine grid dependence and *should* count against
self-sufficiency, so the metric stays `1 − import/load`, unchanged. Only the **displayed** value is
clamped to `max(0, ·)`; when it clamps, the band shows a caveat explaining the battery ended more
charged than it started and that it evens out over full cycles. The negative I first saw came from
a 24-hour test window with a pure net-charging battery — a test artifact, rare in a real
multi-month dataset. Considered and rejected: redefining self-sufficiency to subtract
`battery_charge` from the numerator (over-counts an owned battery as "self", and needs a
flow decomposition the pre-simulation band does not have).

**Also fixed (pre-existing template gap the short window exposed):** the coverage line rendered
"1 days" / "1 dagen". Switched to `ngettext('day', 'days', days)` with a `day`/`days` plural pair
in both catalogs (nl: `dag`/`dagen`).

### Files modified (increment 2, actual)

- `app/summary_view.py` — **new**. `data_summary_from(dataset) -> dict | None`: the §6.3
  per-interval load reconstruction (grid series reconciled onto the effective-window grid, clamp
  negatives) + §6.11 battery-free metrics, with own-coverage price aggregates. Formats to the
  sample's presentation. Returns None when no covering energy series → band omitted.
- `app/main.py` — loaded branch now sets `data_summary = summary_view.data_summary_from(loaded)`;
  `has_dataset` gates on it being non-None; empty-state drop kept. Import + docstring updated.
- `app/sample_data.py` — `_data_summary()` gains `self_sufficiency_clamped: False`; docstrings note
  the computed path supplies real numbers once a dataset loads.
- `app/templates/_panel_summary.html` — `ngettext` for day/days; the self-sufficiency-clamped
  caveat (ⓘ line, shown only when `self_sufficiency_clamped`); shape comment updated.
- `specs/02-ux-wireframes.md` §2.3a — documented the display clamp + caveat and why it is specific
  to the existing-battery variant.
- `specs/12-metrics-and-benchmarks.md` §6.11 — note that the band display-clamps `self_sufficiency`
  to ≥ 0 % (metric unchanged, presentation only).
- `app/locales/messages.pot`, `nl` + `en` `.po`/`.mo` — the `day`/`days` plural pair and the
  clamp-caveat sentence; Dutch translated, en identity; catalogs fuzzy-free (re-extracted with
  `-k _N`, updated `--no-fuzzy-matching`).
- `tests/test_data_summary.py` — computed-view tests over synthetic frames: base totals,
  self-sufficiency with PV, tariff-register fold, existing-battery net-of variant, negative-load
  clamp, negative-self-sufficiency display clamp (+ not-clamped case), price stats, no-grid → None,
  and a computed-view shape-contract check. Sample-shape tests retained as the shared contract.

**Status:** increment 2 complete. Full suite passes (93 passed, 2 skipped — the HA-live tests need
a real instance). Band renders real computed numbers in both languages; negative-self-sufficiency
clamp + caveat and singular "1 day"/"1 dag" verified end-to-end through the real route.

## Increment 3 — anomalies found on real imported data (2026-07-24)

The user imported a real 2-year dataset (grid meters + spot price, solar mapped part-way) and
reported three anomalies in the band. Investigating the persisted frames (`data/local/series`)
found two real bugs in `summary_view.py` and one data problem the band was hiding.

**User's report (verbatim):**

> okay so I have imported some data ... I'm seeing two anomalies:
> - grid import seems very low. ... FWIW the meter was reset at some point ... was this taken into account?
> - solar produced is computed to be zero, which doesn't match reality ...
> - self consumption has an abnormal value of "-1001532%"

Root causes (from the persisted frames):

1. **"Grid import very low" — effective-window clipping bug (mine).** The solar series covered only
   ~140 days (panels mapped recently) while the meters covered 2 years. `data_summary_from` built
   the window via `normalize.effective_window(ALL frames)`, whose intersection collapsed to solar's
   140 days, clipping grid import from ~8,765 kWh to ~637 kWh. This contradicted the agreed
   "sum over each series' own coverage" policy. **The meter reset was NOT the cause** — HA
   reset-corrects the `sum` register upstream, the deltas were all non-negative, 0 RESET_CORRECTED
   flags, ~8,765 kWh over 2 years is trustworthy.
2. **"−1001532% self-consumption" — near-zero PV divide (mine).** The solar sensor summed to 0.2 kWh
   (a broken import), which passed the tiny `DIV_GUARD_EPS = 1e-6` guard, so
   `self_consumption = 1 − export/pv` divided by ~0.2 against a large export.
3. **"Solar zero" — data problem, surfaced honestly.** The solar frame genuinely held near-zero
   values; the band should say so, not show 0.

A THIRD bug surfaced while fixing: with the broken solar, the §6.3 negative-load clamp discarded
~2,036 kWh (23% of load) of unexplained export, silently **inflating consumption** back to ~import
and forcing self-sufficiency to 0%.

### Decisions (confirmed with the user 2026-07-24)

- **Grid-driven window; each short series keeps its own span.** The window is the grid meters'
  coverage; solar/battery/price sum over their own coverage within it. Solar reports its own span
  ("since <date> · N days", `partial` flag). Context from the user: panels were installed ~6 months
  ago, so the 140-day solar span is real, not an error.
- **Near-zero PV → omit + note.** A PV series below `PV_PRESENT_FLOOR_KWH` (1 kWh) is treated as
  empty: the Solar group is omitted and a `solar_empty` data-quality note shown. Fixes the divide.
- **Compromised reconstruction → warn + suppress.** When the clamp discards more than
  `CLAMP_UNRELIABLE_FRAC` (5%) of the reconstructed energy, consumption and self-sufficiency are
  UNRELIABLE: both suppressed (rendered "—") and a prominent `load_unreliable` warning naming the
  unexplained export is shown. Grid import/export and price (measured, not reconstructed) stay.
  The user chose this over showing the (inflated) numbers with a caveat.

### Files modified (increment 3)

- `app/summary_view.py` — window/grid from `_WINDOW_SLOTS` (grid meters) only, not all frames;
  `_add_solar` helper computes produced + self-consumption over the PV's OWN coverage window
  (export restricted to it), applies the empty-PV floor, and reports the PV span + `partial`;
  reliability gate (`CLAMP_UNRELIABLE_FRAC`) suppresses consumption/self-sufficiency and emits a
  `load_unreliable` note; `notes` list added. Clamp fraction denominator is `load + clamped` so a
  total clamp reads as maximally unreliable rather than a swallowed divide-by-zero.
- `app/templates/_panel_summary.html` — render "—" for suppressed household figures; the
  `since <date> · N days` partial-solar label; a `notes` loop rendering the `load_unreliable`
  warning (alert) and `solar_empty` note; gettext printf interpolation `_(msgid, export=...)`
  (NOT `|format`, which double-interpolates the already-`%`-bearing string); shape comment updated.
- `app/sample_data.py` — solar sample gains `coverage`/`days`/`partial`; `notes: []` added.
- `app/locales/*` — three new strings (the `load_unreliable` warning with `%(export)s`, the
  `solar_empty` note, and `since`); Dutch translated, en identity; catalogs fuzzy-free.
- `tests/test_data_summary.py` — new/updated computed-view tests: short-solar-doesn't-clip-grid
  totals, near-zero-PV omit+note, self-consumption over the PV window, heavy-clamp → unreliable +
  suppression + note, small-clamp stays reliable. Old "negative-load → 0 kWh" test replaced by the
  unreliable-gate test.
- Specs: §2.3a and §6.11 to follow (grid-driven window, near-zero-PV omission, reliability gate).

**Status:** increment 3 code complete. Full suite passes (97 passed, 2 skipped). All three reported
anomalies resolved; verified end-to-end on the live dataset (import 8,765 kWh, solar "since
2026-02-12", no false warnings) and on a synthetic broken-solar dataset (warning + suppression +
solar_empty note, both languages).

## Increment 4 — ⓘ info buttons on the derived metrics (2026-07-24)

**User's prompt (verbatim):**

> in the "at a glance" panel, please also introduce an info button next to the derived metrics
> that explains how they are computed in a popup

### Decisions (confirmed with the user 2026-07-24)

- **Which metrics:** the three *derived* ones — Consumption (§6.3 reconstruction), Self-sufficiency
  (1 − import/load), Self-consumption (1 − export/pv). Grid import/export and price avg/min/max are
  raw measured sums, so no button (matches "derived metrics").
- **Placement:** one ⓘ per metric row, each opening a popup specific to that metric.

### Approach

Reused the existing shared-dialog pattern: a `.slot-info-btn` with `data-info-title` /
`data-info-body` (both translated server-side) opens `#slot-info-dialog` (defined in
_panel_data.html), wired by the delegated document-level click handler already in ha_fetch.js — so
**no JS change** was needed, and the dialog is always in the DOM when the band is (both are
data-gated, _panel_data before _panel_summary). The Consumption blurb varies with the
existing-battery case (§6.3 then strips that battery), chosen in-template on `net_battery`.

### Files modified (increment 4)

- `app/templates/_panel_summary.html` — ⓘ buttons on Consumption, Self-sufficiency,
  Self-consumption with per-metric explanation blurbs; header docstring updated.
- `app/locales/*` — four new blurbs (two Consumption variants + the two ratios); Dutch translated,
  en identity. Literal percents use U+FF05 (％), not ASCII %, so the gettext printf-checker does not
  treat "0% means"/"100% means" as a format placeholder (the ASCII form raised ValueError:
  unsupported format character at render — same rule as the README i18n note). Obsolete `#~`
  entries pruned; catalogs fuzzy-free; nl/en/pot all 210 msgids.
- `tests/test_ingest_ws.py` — `test_reload_renders_from_persisted_dataset` now asserts the
  Consumption + Self-sufficiency ⓘ buttons render (no-battery consumption variant, since that
  ingest has no battery series).

**Status:** increment 4 complete. Full suite passes (97 passed, 2 skipped). All three ⓘ buttons
render with translated title + body in both languages and open the shared explanation dialog;
verified end-to-end.
