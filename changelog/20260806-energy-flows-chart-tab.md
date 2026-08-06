# Energy flows chart tab

## Task specification

Build out the **Energy flows** tab in panel ③'s Charts box, currently a pending affordance
(`chart_energy_flows` in `app/features.py`). The user asked first for an explanation of what
the tab — and the "price" half of the sibling `SoC + price` tab — were intended for, then
chose a concrete design.

Scope agreed: **three charts stacked vertically** in one tab, all kWh:

1. Stacked bar — **load sourcing** (where the household's energy came from)
2. Stacked bar — **PV allocation** (where the solar generation went)
3. **Average day** — hour-of-day mean profile

The `SoC + price` tab is explained but **out of scope** for this change.

## What the two pending tabs were for

Reconstructed from the spec, which is thin here — one wireframe at
`docs/specs/02-ux-wireframes.md:1111` and two passing mentions. Recorded because the
reasoning is not written down anywhere else.

**Energy flows.** The only direct statement is `02-ux-wireframes.md:1206` — "*Energy flows*
is unaffected" — in the note on what enabling cost simulation changes. That fixes it as a
purely physical, kWh-only view, the one chart with no euro dimension in either mode. This is
consistent with the panel's central split: kWh figures must be identical whether or not money
is modelled.

**The "price" half of SoC + price.** `02-ux-wireframes.md:1204` is explicit: SoC on the
primary axis, **bare spot price** (`spot_eur_kwh`) on the secondary, in *both* modes. Spot
rather than the delivered import price precisely because spot is a simulation input that
exists regardless of cost simulation — the same reasoning that keeps `spot_eur_kwh` in the CSV
when the cost columns are dropped. Its purpose is as a dispatch diagnostic: whether charge
ramps sit in price troughs and discharge ramps in peaks. It is the visual counterpart to the
money capture ratio, which says *how much* was left on the table but not *when*.

Two gaps the spec never addresses, noted for whenever that tab is built: whether the chart
covers the whole range or a zoomable window (~8,760 points at hourly resolution for a year),
and whether the SoC series is run C alone or overlaid with the perfect-foresight benchmark.

## High-level decisions

**Three charts in one scrolling tab, not nested sub-tabs.** They share a unit (kWh) and answer
adjacent questions, so scrolling beats clicking and allows cross-chart comparison. Each chart
gets a short heading stating its question — without one, a user scrolling to chart 2 has no
way to know why its totals differ from chart 1 (one sums to load, the other to PV generation).

**Pie charts rejected.** Not on general anti-pie grounds: the specific problem is that energy
flows are not one partition. PV splits three ways and load is sourced three ways, with the
battery a shared node in both. A pie must discard one partition or draw two pies that cannot
show they share a term — losing exactly the network structure that makes the data interesting.

**A Sankey was the main alternative considered** and is the canonical choice for this data
(Home Assistant's energy distribution card, SolarEdge, Enphase all use one). Set aside for the
primary view because the results panel already states these totals numerically in the "Where
the energy comes from" box — a Sankey would largely restate on-screen numbers, whereas the
time-resolved views add the dimension that box lacks. Not a closed question: a Sankey is more
immediately legible to a non-expert, and could be added later without disturbing these three.

### Decisions taken by the user

| Question | Choice | Note |
|---|---|---|
| Average-day grouping | **Single averaged day** over the whole range | Simplest to build and read. Known trade-off, accepted: blends summer and winter into a profile matching neither season. Per-season (4 panels) and per-month (12 panels) were the alternatives. |
| Months with gap data | **Annotate incomplete months** | Bar drawn from available data, visually marked, with a footnote. Consistent with the panel's existing `coverage_gaps` warnings. |
| Y-axis scaling | **Independent per chart** | Load sourcing and PV allocation have genuinely different totals; a shared axis would squash the smaller. |
| Bar bucketing | **Monthly** | Reuses `_monthly_import`'s calendar-month bucketing; bars line up with the sibling tab. |
| "Incomplete" threshold | **>5% of intervals missing** | Any-missing would flag nearly every month on real data, making the marking meaningless. |
| Average-day SoC trace | **Include**, secondary axis | Shows the daily charge/discharge cycle directly. The `SoC + price` tab remains separate, deferred work. |
| Data delivery | **Inline with the panel** | See below — the lazy-endpoint option was raised and measured against the existing precedent. |

### Why the flows data is NOT lazy-loaded, unlike the benchmark box

The user asked whether a separate endpoint with lazy loading would be appropriate, since the
charts need more data out of the simulation. The pattern exists here already —
`POST /results/benchmark` does exactly this — but the measured costs point the other way:

| Work | Cost, year of hourly data |
|---|---|
| A/B/C runs (`run_all`) | ~0.12 s |
| Everything else on the page | ~0.13 s |
| §6.12 DPs (runs D/E) | **~4.6 s** ← why the benchmark box is lazy |

The three charts need only the A/B/C flows — the 0.12 s part, which `results_from` computes on
every request anyway to produce the KPI tiles and breakdown. They do not touch the DP. Lazy
loading would therefore avoid no expensive computation.

The real trade is payload, not latency: inline ships a few KB of JSON on every panel render
even for users who never open the tab. Against that, **nothing is cached in this codebase** (a
deliberate, documented choice), so a separate endpoint would re-run `run_all` on tab open —
0.12 s of recomputation to save a few KB. Inline chosen as the better side of that trade.

If the flows payload later grows (per-interval rather than per-month series, say), this
decision should be revisited; the `/results/benchmark` route is the template to copy.

## Findings from the code

**The data is already there.** `Flows` in `app/domain/simulate.py` retains per-interval numpy
arrays for every quantity the three charts need — `imp`, `exp`, `chg_pv`, `chg_grid`,
`dis_home`, `dis_grid`, `curtailed`, plus `soc` and a `gap` mask. This is bucketing work in
`results_view.py`, not new simulation outputs.

**The spec's CSV column names do not exist in code.** `charge_from_pv_kwh`,
`discharge_to_home_kwh` etc. appear only in `docs/specs/07-internal-representation.md:341`.
The implementation calls them `chg_pv`, `dis_home`, … — same quantities, different names. No
CSV writer exists yet either. Worth a spec-vs-code reconciliation note, but not this change.

**`Flows.conservation_residual` is referenced but does not exist.** The `StepFlows` docstring
(`simulate.py:113`) points at it; `grep` finds no definition anywhere in `app/` or the specs.
A stale docstring reference — noted, not fixed here.

**The energy identity closes by construction.** §6.8 step 5 (`simulate.py:507`) computes grid
flows as the *residual of the household balance*:

```
net_flow = load + chg_pv + chg_grid − pv − dis_ac
imp = max(0, net_flow)      exp = max(0, −net_flow)
```

which rearranges to:

```
load + chg_pv + chg_grid + exp + curtailed  =  pv + dis_home + dis_grid + imp
```

This resolves an earlier concern that direct-PV-to-home might have two disagreeing
derivations. There is one balance, and `curtailed` being tracked explicitly (rather than
folded into a residual) is what makes it close.

The two decompositions follow:

- **Load sourcing:** `load = dis_home + (imp − chg_grid) + pv_to_home`
  where `pv_to_home = pv − chg_pv − exp_from_pv − curtailed`
- **PV allocation:** `pv = chg_pv + pv_to_home + exp_from_pv + curtailed`

**Two terms are mixed and must be separated.** `exp` covers both PV export and battery
arbitrage export, so the PV part is `exp − dis_grid`. `imp` likewise covers both household
draw and grid charging, so the household part is `imp − chg_grid`. Getting either wrong
double-counts the battery.

**Gap intervals are NaN, not zero** (`Flows` docstring, `simulate.py:150`), deliberately — a 0
in `imp` asserts "nothing was imported", which is not what the simulation claims for an
interval with missing inputs. This is why the gap-annotation decision above matters: summing
through with `nansum` would render a half-covered month as a short bar reading "low usage"
rather than "unknown".

## Rendering constraints

Charts are **Plotly, drawn client-side** from a JSON `<script>` data node
(`_panel_results.html:450`), via a named `window.drawMonthlyChart()` defined in
`workspace_results.html` and re-called after HTMX swaps. All three charts are within Plotly's
standard repertoire — stacked bars are native, the average day is a simple line/bar. No new
charting machinery.

The HTMX swap constraint is load-bearing: an inline `<script>` in a swapped-in fragment does
not re-execute, which is why the draw function lives in the parent template and reads a fresh
data node. Any new draw function must follow the same pattern.

## Two further constraints found while planning

**`_monthly_import` cannot be reused directly.** It takes `ReconciledGrid` (measured data);
the flows live on `RunSet` from `run_all`. The new function needs a different input. Its
bucketing *loop* is mirrored exactly — window start + `i × grid_s`, (year, month) key in
first-seen order, month NUMBERS not names — so the bars align with the sibling tab and the
locale-bound `monthname` filter keeps working.

**The tab switcher currently assumes one chart container.** `data-chart-view` is set on a
single `#monthly-chart` and the delegated handler redraws it in place. Energy flows is a
different container holding three plots, so the handler must switch *which container is
visible* and dispatch to the right draw function, rather than only redrawing one node. This is
the main template-side change and affects the existing tabs, so it needs care not to regress
the kWh/€ toggle.

## Implementation plan

### Phase 1 — data (`app/results_view.py`)

New `_energy_flows(runs, rec, frame) -> dict`, called inside `results_from` beside
`_monthly_import`, emitting one dict with three sub-objects.

Per-interval series derived from `runs.c` (the policy run, matching the KPI tiles), with the
two mixed terms separated as established above:

- `pv_to_home  = pv − chg_pv − exp_from_pv − curtailed`
- `exp_from_pv = max(0, exp − dis_grid)`
- `imp_home    = max(0, imp − chg_grid)`

Then:

- **`load_sourcing`** — monthly stacks of `dis_home`, `imp_home`, `pv_to_home` (sums to load)
- **`pv_allocation`** — monthly stacks of `chg_pv`, `pv_to_home`, `exp_from_pv`, `curtailed`
  (sums to PV generation)
- **`average_day`** — 24 hour-of-day means of the same flow terms, plus a mean `soc` trace.
  Means over non-gap intervals only; `np.nanmean` per hour bucket.

Gap handling: per month, `missing_frac = gap.sum() / n_intervals`; a month is flagged
`partial` when `missing_frac > 0.05`. Sums use `np.nansum` throughout (gaps are NaN, never 0).
The flag rides in the payload as a parallel boolean array so the template need not recompute
it.

Rounding to whole kWh as `_monthly_import` does; the average-day series keeps 2 decimals since
its magnitudes are ~1 kWh.

### Phase 2 — template (`app/templates/_panel_results.html`)

- New `#flows-charts` container (hidden by default) holding three divs: `#flows-load`,
  `#flows-pv`, `#flows-avgday`, each with a short heading naming the question it answers.
- New `<script id="flows-data" type="application/json">` node beside the existing
  `#monthly-data`, same pattern.
- The `Energy flows` button loses its pending-affordance attributes and becomes a real
  `data-chart-tab` control.
- Footnote line under the bars, rendered only when any month is `partial`.

### Phase 3 — drawing (`app/templates/workspace_results.html`)

- Generalise the delegated click handler: `data-chart-tab` selects which container is shown;
  the existing `data-chart-view` kWh/€ toggle keeps working *within* the monthly tab.
- New `window.drawEnergyFlows()` reading `#flows-data`, three `Plotly.newPlot` calls with
  `barmode: 'stack'`, independent y-axes, average day with SoC on `yaxis2`.
- Called on initial load and from `recompute()`'s success path, exactly as
  `drawMonthlyChart` and `loadBenchmark` are, so it survives HTMX swaps.
- Partial months rendered with a lighter marker colour / pattern fill.

### Phase 4 — retire the affordance and update specs

- Remove `chart_energy_flows` from `app/features.py` (both the pending set and the label map).
- `docs/specs/implementation-progress.md` — move it out of pending.
- `docs/specs/followups.md` — C2 becomes partially done (`chart_soc_price` still pending).
- Extract new translatable strings (`pybabel extract`/`update`); the headings and footnote are
  user-visible text and must be marked, not hardcoded English.

### Phase 5 — verify

- Existing Playwright smoke tests must still pass (they check the monthly chart draws — the
  tab-switcher generalisation is the regression risk).
- Add a smoke check that opens the Energy flows tab and asserts three plots render.
- Assert the two stack identities close on a fixture: load sourcing sums to load, PV allocation
  sums to PV generation, within a small epsilon.

**Deliberately out of scope:** the `SoC + price` tab, a Sankey view, the CSV writer, and
reconciling the spec's CSV column names against the code's field names.

## Phase 1 as built — one correction to the plan

**The plan's load-sourcing identity was incomplete.** It states `load = dis_home + imp_home +
pv_to_home`, taking `load` to be `frame.load`. It is not: §6.9 hands `battery_step` a REBOUND
`frame.load + standby_kw × dt` (`simulate._View`), so the balance that actually closes is

```
dis_home + imp_home + pv_to_home  =  household_load + standby
```

Measured before the fix: the three segments overshot `frame.load` by 108.0 kWh against
2,801.6 kWh over 3,600 intervals — exactly `3600 × 0.030 kW × 1 h`, the appendix-A default
standby. A 3.9% gap with no visible cause in the chart.

Fixed by publishing `standby` and `household_load` **beside** the three segments rather than as a
fourth stacked bar. Standby is a sink, not a source; stacking it would put the battery's own
consumption on the "where the energy came from" side of the balance. Phase 2 decides whether to
show it as a reference line, a footnote, or to net it out — the data supports all three.

The standby figure is the PARAMETER-derived draw, not `RunSet.standby_kwh`. `energy_metrics`
draws the same distinction (`metrics.py:293-312`): the metered `C.imp − B.imp` difference is
smaller whenever PV or the battery covered standby, and would leave the stack short by that much.

The PV-allocation identity needed no correction and closed on the first run.

**Hour-of-day is UTC.** §4.4 holds the pipeline in UTC and `SimulationFrame.index` is UTC-naive by
construction; the CSV spec's `timestamp_local` has no implementation. The average-day profile is
therefore shifted 1–2 h from Dutch wall-clock time (PV peak near 11:00, not 13:00). Converting in
the computation path would be the only local-time conversion there and would disagree with every
other time figure in the module. `workspace_list_view.DISPLAY_TZ` is the precedent for doing it at
DISPLAY time, which is where it belongs if Phase 2/3 wants it. Left UTC and documented in the
function docstring.

### Payload shape

`results["energy_flows"]` — a dict, or None when there was no frame to simulate:

- `months: list[int]` (1–12, first-seen chronological, `_monthly_import`'s bucketing)
- `partial: list[bool]`, `any_partial: bool`
- `load_sourcing: {dis_home, imp_home, pv_to_home, standby, household_load}` — `list[float]`,
  whole kWh, one entry per month
- `pv_allocation: {chg_pv, pv_to_home, exp_from_pv, curtailed}` — same shape
- `average_day: {hours: list[int]} + {dis_home, imp_home, pv_to_home, chg_pv, chg_grid,
  exp_from_pv, curtailed, standby, household_load, soc}` — 24 floats each, 2 dp

### Verified

- `uv run pytest tests/test_results_view.py` — 112 passed; `test_results_route.py` +
  `test_metrics.py` — 77 passed.
- Both identities close to **0.0 kWh exactly** unrounded. They close by construction, so this is a
  check that the terms were assembled right, not a numerical-tolerance result. Per-month rounded
  residuals ≤1.0 kWh (load) and ≤1.23 kWh (PV) are per-segment whole-kWh rounding.
- Gap handling exercised on a frame with 300 of 3,600 intervals blanked: month 3 flagged
  `partial` at 38.7% missing, month 2 correctly NOT flagged at 1.79% (under the 5% threshold),
  identities still exact. No NaN reaches the payload; it is JSON-serialisable (~2.1 KB / 5 months).
- Not verified: behaviour on a real Home Assistant dataset, and on a sub-hourly grid. The checks
  above used synthetic hourly data.

## Files modified

Phase 1, the data function:

- `app/results_view.py` — added `_energy_flows(runs, rec, frame, cfg)` and
  `FLOWS_PARTIAL_MONTH_FRAC`; called from `results_from` beside `_monthly_import`; new
  `"energy_flows"` key in the returned view-model (None when there is no frame); module docstring
  index updated.

The average-day local-time conversion:

- `app/i18n.py` — new `DISPLAY_TZ` constant (Europe/Amsterdam) with its own docstring stating that
  it is a zone, not an offset, and that range conversions must be per-timestamp; added to the
  module's public-API list.
- `app/workspace_list_view.py` — `DISPLAY_TZ` definition removed and imported from `app.i18n`
  instead, re-exported through a new `__all__`; the local `ZoneInfo` import dropped.
- `app/results_view.py` — `_energy_flows` buckets the average day by Europe/Amsterdam local hour,
  converted per interval; the obsolete "Hour-of-day is UTC" docstring section replaced; module
  index entry and the `average_day.hours` payload comment updated. Monthly bucketing unchanged.

Phase 4, affordance retirement (template markup excluded — Phase 2 owns it):

- `app/features.py` — `chart_energy_flows` moved from `FEATURE_KEYS` to `RETIRED_KEYS`; its
  `FEATURE_TITLES` entry kept and moved to the retired block, per the module's own retirement
  rule (issues already filed under the key must stay readable). `chart_soc_price` untouched.
- `tests/test_smoke.py` — the pending-affordance assertion split: `chart_soc_price` still
  asserted present, `chart_energy_flows` now asserted absent.
- `docs/specs/implementation-progress.md` — row moved from *Currently pending* to *Retired*.
- `docs/specs/followups.md` — C2 rewritten as **HALF DONE**, describing only `chart_soc_price`
  as pending and carrying forward the "what was this tab for" notes from this changelog.

Deferred to the phases that own them: the template button (Phase 2), `_energy_flows` (Phase 1),
the draw functions (Phase 3), and the `pybabel` string extraction (Phase 4's second half, which
depends on the template strings existing).

Anticipated:
- `app/results_view.py` — `_energy_flows` and its call site
- `app/templates/_panel_results.html` — tab content, data node, footnote
- `app/templates/workspace_results.html` — tab switching, `drawEnergyFlows`
- `app/features.py` — retire the `chart_energy_flows` pending affordance
- `app/locales/**` — new translatable strings
- `docs/specs/implementation-progress.md`, `docs/specs/followups.md` — C2 status
- tests — smoke coverage for the new tab

## Current status

Design decisions taken; code facts verified against `simulate.py`, `results_view.py` and both
templates. Plan written. **Awaiting plan approval before any code changes**, per AGENTS.md.

## Corrections found during implementation

Two things in the plan above were wrong. Both were found by building it, not by reading.

**1. `app/features.py` is retire-don't-delete.** The plan said to remove `chart_energy_flows`
from "both the pending set and the label map". The module documents the opposite rule
(`features.py:22-24`): a shipped key moves to `RETIRED_KEYS` and **keeps its title**, because
GitHub issues already filed under that key must still render a readable feature name. Deleting
the title would also have broken `import app.features` outright — `_check_titles_cover_keys()`
asserts at import over `FEATURE_KEYS | RETIRED_KEYS`. Done the module's way instead.

**2. The load-sourcing identity as planned does not close.** The plan asserted
`load = dis_home + imp_home + pv_to_home` with `load` meaning `frame.load`. It is not: §6.9
hands `battery_step` a REBOUND `frame.load + standby_kw × dt` (`simulate._View`,
`simulate.py:582`, which rebinds rather than mutating so the band and tiles still see the
household's own load). The identity that actually holds is

    dis_home + imp_home + pv_to_home  =  household_load + standby

Measured before the fix: a **+108.0 kWh** residual against 2,801.6 kWh of load over 3,600
intervals — exactly `3600 × 0.030 kW × 1 h`, the appendix-A default standby, i.e. a 3.9%
overshoot with no visible cause on the chart. Had this shipped unnoticed, every load-sourcing
bar would have been silently ~4% tall.

`_energy_flows` therefore publishes `standby` and `household_load` BESIDE the three segments.
The standby figure is the PARAMETER-derived draw, not `RunSet.standby_kwh`: the latter is the
exact `C.imp − B.imp` run difference (standby *as the meter saw it*, smaller whenever PV covered
it), which would leave the stack short by whatever PV absorbed. `metrics.py:293-312` draws the
same distinction for the same reason.

## Two further decisions

| Question | Choice | Note |
|---|---|---|
| Average-day time basis | **Convert to Europe/Amsterdam** | The computation layer is UTC throughout (§4.4) and `SimulationFrame.index` is UTC-naive, so bucketing by UTC hour put the PV peak at ~11:00 instead of ~13:00 — a profile that would read as simply wrong to a user comparing it against their own inverter or HA dashboard. `workspace_list_view.DISPLAY_TZ` is the project's precedent: compute in UTC, convert at display. **The conversion must be per-interval, before aggregating** — Amsterdam is UTC+1/+2 across DST, so rotating the finished 24-point array would be wrong for half the year. |
| Standby in the load stack | **Reference line** | A line marks household load; the gap between it and the stack top is the standby draw. Preferred over a footnote (less visible) and over netting it out (the segments would stop matching the simulation's actual flows). Standby is a sink, so it is never a stack segment — that would put the battery's own consumption on the "where it came from" side. |

## Phase 1 verification (reported and independently spot-checked)

- Both identities close to **exactly 0.0 kWh** unrounded — by construction from step 5's
  residual, so this confirms the terms were assembled correctly rather than being a tolerance
  result. Per-month rounded residuals ≤1.0 kWh (load) and ≤1.23 kWh (PV), from per-segment
  whole-kWh rounding.
- Gap path exercised by blanking 300/3,600 intervals: a month at 38.7% missing flagged
  `partial`, one at 1.79% correctly not flagged. No NaN reaches the payload. ~2.1 KB JSON for
  five months.
- `tests/test_results_view.py` 112 passed; `test_results_route.py` + `test_metrics.py` 77 passed.
- Independently re-verified here: `simulate.py:582` does rebind load with standby; the retired/
  pending key split is as reported; no test pins `FEATURE_KEYS` contents.

**Unverified:** behaviour on a real Home Assistant dataset and on a sub-hourly grid. All Phase 1
checks used synthetic hourly data.

## Average-day local-time conversion (as built)

The "Convert to Europe/Amsterdam" decision above is now implemented in `_energy_flows`.

**`DISPLAY_TZ` moved to `app/i18n.py` rather than being redefined or imported across views.**
Importing it from `workspace_list_view` would not have cycled, but it would have made
`results_view` — a view-model over simulation output — depend on the workspace-list view, which
pulls in `app.workspaces` → `db`/`config`/`dataset`. `app/i18n.py` is the leaf module both views
already import and it is where the app's other display conventions live (number formats, month
names); a display timezone is the same kind of rule. `workspace_list_view` re-exports the name via
`__all__` so the reference it has been known by still resolves.

**The conversion is per-interval, in a Python loop.** `zoneinfo` has no numpy-vectorised
equivalent, so each interval's local hour comes from `(_as_utc(window[0]) + i × grid_s)
.astimezone(DISPLAY_TZ).hour`. The monthly bucketing is untouched and stays UTC, mirroring
`_monthly_import` as decided.

### Measured

- Synthetic PV bell centred on **13:00 Amsterdam local**, `exp_from_pv` peak bucket:
  | Window | UTC bucketing (before) | Local bucketing (after) |
  |---|---|---|
  | January only (UTC+1) | 12:00 | **13:00** |
  | July only (UTC+2) | 11:00 | **13:00** |
  | Full year 2025 (spans both transitions) | 11:00, peak flattened to 2.45 | **13:00, 2.60** |

  The full-year row is the point: the UTC profile's peak is both displaced *and* lower, because the
  two half-years land in different UTC buckets and smear the hump. A constant shift cannot repair
  that, only re-centre the smear.

- **DST offsets observed per interval**, from the function's own bucketing:
  spring-forward `2025-03-30` — UTC 00:00 → local 01:00 (+1), UTC 01:00 → local **03:00** (+2),
  local 02:00 never occurring; fall-back `2025-10-26` — UTC 00:00 → local 02:00 (+2) and UTC 01:00
  → local **02:00** (+1), the repeated hour.
- **Bucket-occupancy check** over a 20-day window spanning `2025-03-30`: a marker series nonzero
  only on local hour 13 lands in bucket 13 and nowhere else. Counter-proof on the same window: a
  marker on fixed **UTC** hour 11 splits **0.5 / 0.5 across local buckets 12 and 13** — an outcome
  no constant rotation of a finished array can produce, so this distinguishes the implemented
  approach from the rejected one rather than merely being consistent with it.
- `tests/test_results_view.py` + `test_results_route.py`: 168 passed. `test_workspace_list.py` +
  `test_i18n.py` (the `DISPLAY_TZ` move): 128 passed.

- **Loop cost measured:** 0.038 s for 35,040 intervals (a year of 15-minute data), against the
  ~0.12 s `run_all` the page already runs. Not a reason to vectorise.

**Not verified:** behaviour on a real Home Assistant dataset, and on a sub-hourly grid end-to-end
(the timing above is the conversion loop alone, not a full sub-hourly `_energy_flows` run).

**Incidental finding, not investigated:** `reconcile_grid` fills short dataset-level meter holes
rather than leaving NaN, so gap-flagged months will be rarer in practice than the plan assumed.
Whether that interpolation is intended is a separate question from this change.

## Local-time conversion (Phase 1b)

The average-day bucketing now converts to Europe/Amsterdam per interval, before aggregating.

**`DISPLAY_TZ` moved to `app/i18n.py`.** It previously lived in `workspace_list_view`. Importing
it from there would not have cycled, but it would have made `results_view` — a view-model over
simulation output — depend on the workspace-list view and, transitively, on `app.workspaces` →
`db`/`config`/`dataset`. `i18n.py` is the leaf both already import and where the app's other
display conventions live (number formats, month names); a display timezone is the same class of
rule. `workspace_list_view` re-exports it so the old reference path still resolves.

**Peak hour, measured** on a synthetic PV bell centred on 13:00 local:

| Window | UTC (before) | Local (after) |
|---|---|---|
| January only (UTC+1) | 12:00 | **13:00** |
| July only (UTC+2) | 11:00 | **13:00** |
| Full year 2025 | 11:00, peak 2.45 | **13:00, peak 2.60** |

The full-year row is the substantive one: under UTC the peak was both displaced *and lower*,
because the two half-years land in different UTC buckets and smear the hump. A constant shift
could only have re-centred that smear, not removed it — which is the argument for per-interval
conversion rather than rotating the finished 24-point array.

**DST evidence** (independently reproduced in the orchestrating session, not only reported):

- Spring-forward 2025-03-30: UTC 00:00 → local 01:00 (+1); UTC 01:00 → local **03:00** (+2).
  Local 02:00 never occurs.
- Fall-back 2025-10-26: UTC 00:00 → local 02:00 (+2); UTC 01:00 → local **02:00** (+1). Two
  distinct UTC intervals map to the same local hour.

The discriminating check: over a window spanning 2025-03-30, a marker series nonzero only on
*local* hour 13 lands in bucket [13] and nowhere else; the counter-proof, a marker on fixed *UTC*
hour 11, **splits 0.5/0.5 across local buckets 12 and 13**. No constant rotation of a finished
array can produce a split, so this distinguishes the implemented approach from the rejected one
rather than merely being consistent with both.

**Known artifact, accepted:** the two DST days weight local hour 02:00 unevenly by construction —
sub-percent over any real window, and correcting it would distort more than it fixes.

**Monthly bucketing deliberately left on the UTC basis.** A monthly total is a sum over a
contiguous block, so the choice only moves a handful of boundary intervals between adjacent
months (≤2 h at each month edge). Diverging from `_monthly_import` would cost more in
inconsistency than it buys.

Cost: 0.038 s for 35,040 intervals (a year at 15-minute resolution), against the ~0.12 s
`run_all` the page already performs. Not worth vectorising.

**A first probe read as a failure and was not** — worth recording. Reading the peak from
`pv_to_home` gave 10:00 in every case, because the load clamp flattens that series into a
five-way tie and `argmax` returns the first tied bucket. `exp_from_pv` is unclamped and made the
check decisive.

## Phases 2 and 3 as built — the template and the three draw functions

### Phase 2, `app/templates/_panel_results.html`

The *Energy flows* button lost **both** `data-pending-name` and `data-feature-key`, plus its
`opacity-60` and its trailing `[?]`. Both attributes had to go, not one: the dialog handler in
`_pending_dialog.html` matches on `data-pending-name`, so leaving it would have fired "Not built
yet" over a working tab, while leaving `data-feature-key` alone would have failed
`test_new_pending_controls_marked`, which asserts a count of 0 for `chart_energy_flows`.

The button and the whole flows subtree are gated on `results.energy_flows`, which is None when
there is no frame to simulate — the same condition that drops the `#flows-data` node. An empty
workspace therefore shows exactly the tab strip it showed before.

`#flows-charts` is `hidden flex-col gap-4`, holding three headed plot divs plus the footnote.
The headings state the QUESTION each chart answers, which is what makes charts 1 and 2 legible
side by side: they have different totals and share a term (`pv_to_home`).

The footnote is written **"5 percent", not "5%"**, deliberately. A bare `%` in a msgid makes
`pybabel extract` mark the entry `#, python-format`; the string takes no arguments at all, so
that flag can only ever turn a translator's stray `%` into a runtime format error. Found by
extracting the first draft and reading the `.po`.

`#flows-data` sits beside `#monthly-data`, inside `#panel-results` so a swap replaces it, and
carries every user-visible string the charts need — series names, axis titles, the month labels
made here by the locale-bound `monthname` filter. Nothing in the JS writes English.

### Phase 3, `app/templates/workspace_results.html`

**The tab switcher was split into two attributes rather than generalised in place.**

    data-chart-tab   which container is visible (`monthly` | `flows`)
    data-chart-view  which series #monthly-chart draws (`kwh` | `eur`)

The two monthly buttons carry BOTH. That is the part that mattered: with `data-chart-tab` alone
on them, clicking € from the flows tab would have switched container without selecting the euro
series; with `data-chart-view` alone, it would have selected the series without leaving the flows
tab. Carrying both makes one click do both, and it is what keeps the pre-existing kWh/€ toggle
behaving exactly as it did. The handler still delegates from `document` and the selected view is
still held on the container, so a swap resets it — container visibility now resets the same way,
back to monthly.

The handler dispatches on the tab and returns early for `flows`, so `drawMonthlyChart()` is never
called with a euro view that a flows button did not set.

`drawEnergyFlows()` draws three plots:

- `#flows-load` — stacked `dis_home + imp_home + pv_to_home`, with `household_load` as a
  scatter reference LINE over the bars. The gap between line and stack top is the standby draw.
- `#flows-pv` — stacked `chg_pv + pv_to_home + exp_from_pv + curtailed`.
- `#flows-avgday` — the same source segments plus `chg_pv` over hours 0–23, with `soc` on
  `yaxis2` (overlaying, right, `rangemode: 'tozero'`) because stored kWh is not the same quantity
  as kWh moved per hour.

Independent y-axes throughout, as decided. Styling follows the monthly chart's conventions
(transparent bgcolors, `font: {size: 11}`, `displayModeBar: false`, `responsive: true`).

One colour map is shared by all three charts, so a term keeps its colour wherever it appears —
`pv_to_home` is a segment of both stacks and the two charts are only comparable if it looks the
same in each. `#570df8`, the monthly chart's existing series colour, is kept for the battery.

Partial months are marked with a Plotly `marker.pattern` hatch, per point rather than by
splitting the series, so a short bar reads as "unknown" rather than "a quiet month".

**Plotly cannot size a plot inside a `hidden` container** — it measures 0. So the tab handler
draws AFTER flipping the class, and `initPanelResults()` / `recompute()` draw eagerly as well so
the tab is populated the instant it is picked. Both call sites were updated, matching how
`drawMonthlyChart` and `loadBenchmark` already re-fire after a swap.

### Catalogs

17 new msgids, extracted with the documented flags and translated into `nl` (and filled in `en`,
matching the existing entries there). `"Energy flows chart"` became obsolete — the msgid existed
only because of the pending button's `data-pending-name`; `app/features.py` keeps the retired
key's title as a plain dict value, which is not extracted.

### Verified in a real browser

Playwright against the running server, on a seeded dataset (the empty smoke workspace has no
`energy_flows` at all, so the default `page` fixture cannot exercise this):

- All three plot divs render, each 876 px wide, `#flows-charts` visible and `#monthly-chart`
  hidden. Legend of chart 1 reads Household load / Directly from solar / From the grid / From the
  battery — server-translated, as intended.
- No `pageerror` at any point in the walk.
- The pending dialog does NOT open on the tab click (`#pending-dialog[open]` count 0).
- kWh → € → kWh on the monthly tab moves the y-axis title between `kWh` and `€` and sets
  `data-chart-view` accordingly; € clicked from INSIDE the flows tab switches container and series
  in one click and leaves exactly one tab button active.
- After a period-preset recompute (a full panel swap), reopening the tab still renders all three.

Test results: `test_workspace_results.py` + `test_results_route.py` +
`test_no_english_leakage.py` — 231 passed. `test_smoke.py` — 42 passed, including
`test_new_pending_controls_marked` and `test_chart_rendered`.

**Not verified:** the flows tab in Dutch in a browser (the catalogs are filled and the leakage
test passes on the Dutch render, but no screenshot was taken), and behaviour on a dataset large
enough for the partial-month hatching to actually appear — `any_partial` was false on the seeded
fixture, so the footnote and the hatch pattern are unexercised in the browser.

## Partial-month hatching: exercised in a browser (the gap the phases above left)

The phases above shipped the hatching and the footnote without either ever having been rendered —
`any_partial` was false on every fixture available, so both were inferred correct from the payload
shape. Both have now been observed.

### The mechanism is not reachable from a dataset

Probed before trying to render anything. `_energy_flows` derives `partial` from `Flows.gap`, which
§6.9 sets from `isnan(frame.load) | isnan(frame.pv)`. Nothing in the pipeline can put a NaN there:

- `reconcile._resample_sum` does `np.nan_to_num(values, nan=0.0)`, so NaN readings become 0.0;
- intervals a series does not cover contribute 0 by the own-coverage policy;
- `rec.load = np.maximum(raw_load, 0.0)`, and `simulation_frame` zero-fills an absent `pv`.

**Measured, not read:** a 90-day hourly dataset with a 30-day CONTIGUOUS hole (Feb 10 – Mar 12) —
tried both as NaN values and with the rows dropped entirely — gives `isnan(frame.load).sum() == 0`
in both cases, and through `results_from`: `partial == [False, False, False]`, `any_partial ==
False`, with `household_load == [1116, 324, 720]` kWh. February is a bar a third the height of
January's with nothing to say why. That is precisely the "reads as a quiet month" failure the
hatching exists to prevent, and on real data it is exactly the case that does NOT get marked.

This confirms the "incidental finding" recorded earlier in this changelog and sharpens it: the
zero-filling does not merely make flagged months *rarer*, it makes them **unreachable**. The
hatching and footnote are correct code on a path no dataset currently takes. Whether the
zero-filling is right is a separate question from this change and is NOT touched here — but the
gap-annotation decision is contingent on it, so it is recorded here rather than left implicit.

### Observed in Chromium, with the frame patched

`simulation_frame` patched in the server process to NaN intervals 1000–1300 (inside February) of a
Jan–Mar hourly window — 300 of February's 672 intervals, 44.6% missing, against 0% for January and
March. Server + Playwright, English pinned, tab opened by clicking `[data-chart-tab='flows']`:

| | forced gap | no gap |
|---|---|---|
| `partial` in `#flows-data` | `[false, true, false]` | `[false, false, false]` |
| footnote element count | 1 | **0** |
| footnote visible / box | true / 876×16 px at y=968 | — |
| `marker.pattern.shape`, all 3 traces of `#flows-load` | `["", "/", ""]` | `["", "", ""]` |
| `marker.pattern.shape`, all 4 traces of `#flows-pv` | `["", "/", ""]` | `["", "", ""]` |
| `<pattern>` defs in `#flows-load` svg | 3 | 0 |
| `<pattern>` defs in `#flows-pv` svg | 4 | 0 |
| `<pattern>` defs in `#flows-avgday` svg | 0 | 0 |
| `pageerror` / console errors | none | none |
| three plot divs, each 876×256 px | yes | yes |

The `<pattern>` def counts are the load-bearing ones: they are Plotly's own output, so they show
the per-point shape array reached the SVG rather than only sitting on the trace object. One def per
BAR trace, and zero on the average day — which takes no pattern, correctly, since it has no
per-month bar to mark.

**The flag discriminates.** `["", "/", ""]` is the whole point: a rule that marked every month
would produce `["/", "/", "/"]` and pass any assertion phrased as "something is hatched".

A screenshot of `#flows-charts` confirms it reads as intended: February's bar is visibly diagonally
hatched, January's and March's are solid, the household-load reference line dips to meet the short
bar, and the footnote sits between the two bar charts and the average day.

### Permanent test added

ONE test, `test_the_partial_month_footnote_appears_only_when_a_month_is_flagged` in
`tests/test_workspace_results.py` — that file's conventions (TestClient render, assertions scoped
to real hooks), not a browser test.

It pins the SERVER side both ways: footnote absent on the clean render, present on the patched one,
and `#flows-data`'s `partial` array exactly `[false, true, false]`. Scoped there rather than in
`test_smoke.py` because a Playwright version would need the same `simulation_frame` patch inside a
subprocess — machinery disproportionate to what it would add over the trace inspection recorded
above. The JS half (`partialPattern` → `marker.pattern` → `<pattern>` defs) is observed in this
changelog and left unpinned; it is a five-line pure function and the fragile part is the payload
contract, which is what the test holds.

The test also documents the unreachability in its docstring, so the next reader does not repeat the
probe, and it keeps working unchanged if a future coverage rule ever makes gaps reachable.

### Not verified

- The Dutch render of the footnote in a browser (the msgid is translated and the leakage test
  passes; no screenshot taken).
- Behaviour at a sub-hourly grid, and on a real Home Assistant dataset — unchanged from above.
- Whether the hatch remains legible on a bar only a few pixels tall; February's bar here was ~90 px.

## The partial-month flag cannot currently fire (finding, not fixed)

The gap-annotation the user chose is built, correct, and **unreachable from any dataset**. This
was found by trying to exercise it, not by reading.

`_energy_flows` derives `partial` from `Flows.gap`, and §6.9 sets that mask from
`isnan(frame.load) | isnan(frame.pv)` (`simulate.py:708`). Nothing upstream can put a NaN there:

- `reconcile._resample_sum` does `np.nan_to_num(values, nan=0.0)` (`reconcile.py:93`)
- intervals a series does not cover contribute 0 under the own-coverage policy
- `rec.load = np.maximum(raw_load, 0.0)` (`reconcile.py:216`)
- `simulation_frame` zero-fills an absent `pv`

**Measured**, on a 90-day hourly dataset with a 30-day contiguous hole, tried both as NaN values
and with the rows dropped outright:

- `isnan(frame.load).sum() == 0` either way
- through `results_from`: `partial == [False, False, False]`, `any_partial == False`
- `household_load == [1116, 324, 720]` kWh

So February renders as a bar a third of January's height **with nothing saying why** — which is
exactly the "reads as a quiet month rather than an unknown one" failure the hatching exists to
prevent, and it is the case that goes unmarked. An earlier note in this file called flagged
months "rarer in practice"; that was too weak. They are currently impossible.

Not fixed here. Whether zero-filling a hole is the right reconcile behaviour is a separate
question from this tab, and changing it would move numbers on every panel, not just this chart.
Carried to `docs/specs/followups.md`.

**Verified in Chromium by patching `simulation_frame` in the server process** (300 of February's
672 intervals NaN'd — 44.6%, against 0% for January and March), which is the only way to reach
the path at all:

| | forced gap | no gap |
|---|---|---|
| `partial` in `#flows-data` | `[false, true, false]` | `[false, false, false]` |
| footnote element count | 1 | **0** (no empty `<p>`) |
| `marker.pattern.shape`, `#flows-load` | `["", "/", ""]` | `["", "", ""]` |
| `<pattern>` defs in load / pv / avgday SVG | 3 / 4 / 0 | 0 / 0 / 0 |
| pageerror + console errors | none | none |

The `<pattern>` def counts are the load-bearing evidence: they are Plotly's own SVG output, so
the per-point array actually reached the DOM rather than only sitting on the trace object. Zero
on the average day is right — it has no per-month bar. The flag DISCRIMINATES: `["", "/", ""]`,
not `["/", "/", "/"]`.

One focused regression test added to `tests/test_workspace_results.py`
(`test_the_partial_month_footnote_appears_only_when_a_month_is_flagged`), pinning the server side
both ways. Placed there rather than in `test_smoke.py` because a Playwright version would need
the same patch inside a subprocess — machinery disproportionate to what it adds over the trace
inspection above. Its docstring records the unreachability so the next reader does not repeat the
probe, and it keeps working unchanged if a future coverage rule makes gaps reachable.

## Final verification

- `tests/test_smoke.py` — **42 passed** (the only suite exercising a fresh install).
- `test_results_view` + `test_workspace_results` + `test_results_route` +
  `test_no_english_leakage` + `test_i18n` + `test_workspace_list` + `test_metrics` +
  `test_simulate` — **518 passed**.
- The full suite was NOT run: it contains long benchmarks, and `tests/test_benchmark.py` was
  never invoked.

**Still unverified, stated plainly:** real Home Assistant data; sub-hourly grids; the Dutch
footnote rendered in a browser (msgid is translated and the leakage test passes, but no
screenshot); whether the hatch stays legible on a bar only a few pixels tall (the observed one
was ~90 px).

**Two Dutch terms want a native check:** `Curtailed` → "Afgeregeld", `Battery standby draw` →
"Standby-verbruik batterij". Both defensible, neither has in-repo precedent.

## Review findings and fixes

A review pass over the complete diff (no single agent had seen all of it) found two real defects
in the average-day chart plus some dead strings. The monthly charts, the kWh/€ toggle, the
payload/guard consistency and the project-rule compliance all came back clean.

### 1. The average day was wrong by `3600/grid_s` on any sub-hourly grid — FIXED

`_hourly` took `np.nanmean` over the *intervals* in each local-hour bucket. At hourly resolution
that bucket holds one interval per day, so the mean is kWh-per-hour and the axis is right. At
15-minute resolution it holds four, so the value is kWh-per-15-minutes — the same physical day
drawn 4× too short. Measured on identical synthetic data over 60 days:

| grid | avg-day segments summed over 24 buckets | true daily total |
|---|---|---|
| 3600 s | 10.32 kWh | 9.62 kWh ✓ |
| 900 s | **2.58 kWh** | 9.62 kWh ✗ |

15-minute data is the standard Dutch P1 smart-meter export and a common Home Assistant
statistics resolution, so this was not an edge case. Such a user would have seen an average day
at roughly a quarter of what the monthly bars and every KPI tile on the same screen reported.

Compounding it: `soc` is a **stock**, so its per-interval hourly mean is already
resolution-invariant. The flow bars would shrink 4× while the SoC trace on the secondary axis did
not, so the visual relation between the two axes changed silently with the input resolution.

The correct aggregation is a mean **per day** — sum within each local-hour bucket, divide by the
number of distinct days contributing — applied to the flows only, never to `soc`. The flow/stock
distinction is now explicit in the code, because it is precisely the kind of thing a later reader
would "simplify" back into a bug.

This defect was invisible to the entire existing suite. Every check to that point had used
hourly data, where the bug is exactly a no-op.

### 2. The average day stacked a sink onto three sources — FIXED

The draw code stacked four series including `chg_pv` (PV going *into* the battery, a sink) while
its own comment said three. The bar total was therefore a load-side quantity plus a storage-side
one, which corresponds to no physical quantity. Around midday it overstated household consumption
by the charging rate — so the visible peak of "an average day" was the wrong part.

This is the same category error the change deliberately avoids in chart 1, where `standby` is
kept off the stack and drawn as a reference line. The average day now matches chart 1 exactly:
three stacked sources, a `household_load` reference line, SoC on the secondary axis.

### 3. A label faced the wrong way — FIXED (user-reported)

One shared label map served both bar charts, so `pv_to_home` was "Directly from solar" in both.
Chart 2 asks *where the solar went* and every sibling label names a destination, making that one
label the odd one out. Now per-chart: chart 1 keeps **"Directly from solar"**, chart 2 reads
**"Consumed directly"**.

Worth recording as a pattern: one series legitimately needs two labels because two charts ask
opposite questions about it. A later "cleanup" that re-merges the maps reintroduces the defect.

### 4. Dead translated strings — FIXED

`partial_suffix`, `labels.chg_grid` and `labels.standby` were emitted and translated into two
languages with no render path.

### Not defects

- **Cross-slice payload/guard consistency** — every emitted key on the monthly side is read;
  `any_partial` is correctly template-only; the three `{% if results.energy_flows %}` guards are
  identical and cannot disagree.
- **The kWh/€ toggle** — traced through every reachable click sequence. The pending `SoC + price`
  button carries neither attribute, so `closest('[data-chart-tab]')` returns null and the handler
  returns before touching `btn-active`; the pending dialog fires independently. Exactly one
  `btn-active` throughout.
- **Monthly arithmetic** — both identities close at hourly, 15-minute, single-interval and
  year-boundary windows.
- **Empty window / no PV / no battery** — not reachable or not broken.

### Carried, not fixed

- **Multi-year windows merge months across years** (`[1,…,12,1,2,3]` → duplicate "Jan" categories).
  Pre-existing and documented in `_monthly_import`; `_energy_flows` mirrors it deliberately. Worth
  noting that a stacked bar with a reference line degrades worse under category merging than a
  single bar series does.
- **`_energy_flows` uses `cfg.battery.standby_w / 1000.0` rather than the `cfg.standby_kw`
  property**, bypassing the `None`-coercion `_num()` provides. Traced all three `results_from`
  call sites; every one passes `simconfig_store.load()`, which coerces the field back to its
  default, so it is unreachable end-to-end. Strictly safer to use the property; not a live bug.

## Three template-only follow-up fixes (review findings)

A review of the shipped tab found three problems. All three are TEMPLATE-side; `_energy_flows`
in `app/results_view.py` was untouched here (a concurrent change was reworking its aggregation
maths, and the payload KEYS are unchanged either way).

### Fix 1 — `pv_to_home` needs two labels, one per chart

`pv_to_home` is a segment of BOTH bar charts, but the two charts ask opposite questions. Chart 1
asks where the household's energy CAME FROM, so "Directly from solar" names a source and is
right. Chart 2 asks where the solar generation WENT, so every sibling label names a destination
(into the battery / exported / curtailed) and "Directly from solar" is the odd one out — it names
the source in a list of sinks.

**Decided by the user:** chart 2 labels it **"Consumed directly"**; chart 1 keeps "Directly from
solar".

**Structure chosen: one shared `labels` map plus a small `labels_pv_allocation` OVERRIDE map**,
merged by `stackedMonths()` at draw time (`d.labels[k]` becomes `(overrides || {})[k] ||
d.labels[k]`). The alternatives were two full per-chart maps — which would duplicate the six keys
that genuinely are shared and let them drift apart — or renaming the payload key, which would
have touched `results_view.py`. The override map is the smallest thing that expresses "these two
labels are deliberately different", and both templates carry a comment saying WHY, because a
later reader tidying up would otherwise re-merge them and silently undo the fix.

Both strings go through `_()`; "Consumed directly" is a new msgid.

### Fix 2 — the average day stacked a sink onto three sources (confirmed defect)

`workspace_results.html` stacked `['dis_home', 'imp_home', 'pv_to_home', 'chg_pv']` under
`barmode: 'stack'`, beneath a comment claiming "same three sources". `chg_pv` is PV going INTO
the battery — a SINK. Stacking it with three load-side sources makes the bar total a load-side
quantity plus a storage-side one, which is not a physical quantity at all; around midday it
overstates household consumption by the charging rate, so the visible peak of the "average day"
sits in the wrong place. This is the same category error chart 1 deliberately avoids by keeping
`standby` off its stack.

**Fixed to match chart 1 exactly:** three stacked sources (`dis_home + imp_home + pv_to_home`),
`chg_pv` dropped from the stack, plus the `household_load` reference line drawn the same way
chart 1 draws it, plus the existing `soc` trace on `yaxis2` unchanged. The comment now says three
and means three.

`average_day.household_load` was already in the payload and previously unread; it is now the line.

### Fix 3 — three emitted-but-unread label keys

Each resolved individually rather than as a batch:

| key | disposition | reason |
|---|---|---|
| `partial_suffix` (`(incomplete month)`) | **removed** | Nothing reads it and nothing wants to: the partial-month convention is a hatch pattern plus a footnote, both already rendered. A per-point name suffix has no place to go on a Plotly bar trace, whose `name` is per-TRACE. |
| `standby` (`Battery standby draw`) | **removed** | It was emitted for a stack segment that the recorded decision explicitly rules out (standby is a sink). Fix 2's reference line uses `household_load`, not `standby`, so after Fix 2 there is no render path and no plausible near-term one. The payload's `standby` SERIES stays — `results_view.py` is untouched — only the label is dropped. |
| `chg_grid` (`Battery charged from the grid`) | **removed** | `chg_grid` appears in no chart: it is netted out of `imp_home` in chart 1 and is not a PV allocation, so neither bar chart has a slot for it, and the average day now stacks three sources only. |

Removing all three drops three msgids. Catalogues re-extracted with the documented cycle from
`babel.cfg` (`extract -k _N -k _msg -k _msg_n:1,2 --sort-output --no-location` →
`update --no-fuzzy-matching` for both locales → `compile`).

### Files modified

- `app/templates/_panel_results.html` — `#flows-data` labels map: three dead keys removed, new
  `labels_pv_allocation` override map added with the rationale comment.
- `app/templates/workspace_results.html` — `stackedMonths()` takes an override map; chart 2 passes
  it; the average day stacks three sources and gains the household-load line; comments corrected.
- `app/locales/messages.pot`, `app/locales/{en,nl}/LC_MESSAGES/messages.{po,mo}` — one msgid added
  ("Consumed directly"), three removed.

## Defect: the average day was per-INTERVAL, not per-hour, and collapsed on sub-hourly data

Found in review, confirmed by measurement. The earlier "not verified on a sub-hourly grid" caveat
in this file was where it was hiding.

`_hourly` took `np.nanmean` over the intervals falling in each local-hour bucket. At an hourly grid
a bucket holds one interval per day and that mean is kWh-per-hour, so the axis was right. At a
15-minute grid a bucket holds four, and the mean is kWh-per-15-minutes — the same physical day drawn
a quarter as tall, on a page whose monthly bars and KPI tiles did not move. **15-minute is the
standard Dutch P1 smart-meter export and a common Home Assistant statistics resolution**, so this
was the common case rather than an edge one.

**Measured before the fix**, one physical 60-day load/PV profile fed in twice — once as hourly
frames, once as 15-minute frames with each hour's kWh split evenly across its four quarters, so the
two datasets describe one household:

| | source segments Σ over the 24 buckets | monthly stack ÷ days |
|---|---|---|
| grid 3600 s | 14.08 kWh | 14.10 kWh/day |
| grid 900 s | **3.50 kWh** | 14.10 kWh/day |

The monthly column is the control: it is identical across the two, which is what makes the
average-day column an aggregation artifact rather than a difference in the simulation.

### The fix: divide by DAYS, and only for the flows

`_hourly` is now two functions, deliberately not one:

- **`_hourly_flow`** — Σ over the bucket ÷ the number of **distinct local days contributing a
  non-gap interval to it**. Resolution-invariant by construction: four quarter-hours sum to the hour
  they make up, so the numerator does not depend on the grid and the denominator counts days.
- **`_hourly_stock`** — the old per-interval `nanmean`, for `soc` alone.

**`soc` is a STOCK and had to be exempted.** It is kWh stored at an instant, not kWh moved during an
interval; its per-interval mean is already the average charge held during that hour and is already
resolution-invariant, and summing stored charge across a day answers no question. Applying the flow
rule to it would have multiplied the trace by four. The two functions carry that distinction in
their names, their docstrings and a comment on each call site, because collapsing them back into one
is exactly the "simplification" a later reader would reach for.

**Why distinct DAYS and not intervals-÷-per-day.** A fixed divisor would be wrong wherever the
window is not a whole number of complete days: a partial first or last day would dilute the hours it
does not reach, a fully-gapped hour would dilute its bucket in proportion to the gap (the failure the
NaN-not-zero convention exists to prevent), and both DST days would be mis-weighted. Counting the
days that actually contributed handles all four with one rule.

### Verified

Throwaway probes, in the scratchpad, not the repo. Same fixture construction as the new test.

**(a) Resolution invariance.** After the fix, every flow series is bit-identical between 3600 s and
900 s — `max|Δ| = 0.0000` per bucket for `dis_home`, `imp_home`, `pv_to_home`, `chg_pv`,
`household_load` — and the Σ-over-24 goes 3.50 → **14.08 kWh** at 900 s, matching the hourly run's
14.08. Cross-checked outside the view: the simulation's own window totals (`imp`, `exp`, `dis_home`,
`chg_pv`) agree between the two grids to within 1e-15, so the two inputs really are one physical
household.

**(b) Consistency with the monthly stack.** Average-day segments 14.08 kWh against the monthly
`household_load + standby` of 846.0 kWh ÷ 60 days = 14.10 kWh/day, at BOTH resolutions. The 0.02
kWh residual is the monthly stack's whole-kWh rounding.

**(c) SoC.** Unchanged at hourly resolution — same code path, byte for byte. Between resolutions its
per-bucket values differ by up to 0.74 kWh on a ~9 kWh battery, and that difference is REAL, not an
artifact: the 15-minute run samples the same trajectory four times per hour, and comparing the raw
per-interval `soc` arrays outside the view (hourly against the 15-minute array block-averaged in
fours) gives the same 0.73 kWh spread. The window means agree: 4.0967 against 4.0963.

**(d) DST.** Ten-day windows straddling each transition, both grids, no divide-by-zero and no spike:

| window | local 02:00 `household_load` | neighbours 01:00 / 03:00 |
|---|---|---|
| spans spring-forward 2026-03-29 | 0.40 | 0.44 / 0.40 |
| spans fall-back 2026-10-25 | 0.44 | 0.43 / 0.40 |

Both behave as the rule predicts. The spring-forward day contributes no interval to local 02:00 and
so is absent from that bucket's day count, leaving it level with its neighbours. The autumn day
contributes two hours' worth of intervals but counts as one day, so the bucket reads ~10% high —
one double-length day out of ten. Over a real window that share shrinks accordingly.

**Gap days.** Not reachable from a dataset (see the section above), so probed by patching
`Flows.gap` directly: blanking 5 of 20 days entirely leaves the average day IDENTICAL (13.35 kWh
Σ24 either way), which is the correct behaviour — an average day over the surviving 15 days is the
same profile. An all-gap window yields 0.0 in every bucket, no division by zero.

**Cost.** `_energy_flows` on a full year: 0.038 s at 8,760 hourly intervals, 0.095 s at 35,040
15-minute intervals, against the ~0.12 s `run_all` the page already performs. The day-id interning
adds a dict lookup to the tz loop that was already there.

### One permanent regression test added

`test_the_average_day_is_the_same_profile_at_hourly_and_15_minute_resolution` in
`tests/test_results_view.py`. Warranted because **the entire existing suite was blind to this** —
every fixture in it is hourly, at which resolution the wrong aggregation and the right one give the
same answer, so no amount of assertion strength on the existing fixtures could have caught it. The
missing coverage was a second resolution, which is a fixture property rather than an assertion.

It asserts the flows bucket-for-bucket across the two grids, then that the level is right (segments
against the monthly stack ÷ days, at both grids — an hourly-only version of that check would pass
under the defect), and finally the SoC window mean, with the flow/stock distinction stated in the
docstring so the next reader does not "fix" the SoC line to match the others. Confirmed to
discriminate: restoring `nanmean` in `_hourly_flow` fails it with `dis_home moved with grid
resolution`, 0.50 against 0.12 in bucket 0.

One test, not a suite. The property is resolution invariance and it holds for all nine flow series
at once; separate tests per series would restate it.

### Files modified

- `app/results_view.py` — `_hourly` split into `_hourly_flow` (Σ ÷ distinct contributing days) and
  `_hourly_stock` (per-interval mean, `soc` only); the tz loop now also interns each interval's
  local DATE for the denominator; `_energy_flows` docstring gains a section on the denominator and
  the flow/stock split, with the DST and gap paragraphs corrected to the new rule; the module index
  entry updated; per-call-site comments added to the `average_day` payload.
- `tests/test_results_view.py` — `_flows_dataset(days, grid_s)` helper and the one regression test.

### Not verified

- Real Home Assistant data at 15-minute resolution end to end. The fixture is synthetic and
  constructed to be exactly divisible, which is the cleanest case; a real 15-minute export with
  irregular timestamps goes through `reconcile_grid` before reaching this code and was not exercised.
- The rendered chart at 15-minute resolution in a browser. The payload is verified; no template
  change was needed (`app/templates/*` deliberately untouched — another change owned them), and the
  draw functions read the same keys with the same shapes, so this is inferred rather than observed.
- Whether any real window contains a bucket with zero contributing days. The 0.0 fallback is
  exercised only by the all-gap probe.

## Verification of the sub-hourly fix

`_hourly` was replaced by two functions rather than one with a flag:

- `_hourly_flow` — Σ over the local-hour bucket ÷ **distinct local days contributing a non-gap
  interval to that bucket**. All nine flow series.
- `_hourly_stock` — the per-interval `nanmean`, for `soc` alone.

**Why distinct days rather than intervals ÷ intervals-per-day.** A fixed divisor is wrong whenever
the window is not a whole number of complete days. Counting contributing days handles four cases
with one rule: a partial first/last day counts only for the hours it reaches; a day whose 03:00 is
entirely gapped drops out of that denominator instead of diluting it (the failure the NaN-not-zero
convention exists to prevent); the spring-forward day is absent from the 02:00 bucket; the
fall-back day contributes two hours' intervals but counts as one day.

**Resolution invariance**, one physical 60-day profile fed in as hourly and as 15-minute frames:

| grid | before | after |
|---|---|---|
| 3600 s | 14.08 kWh | 14.08 kWh |
| 900 s | **3.50 kWh** | **14.08 kWh** |

After the fix every flow series is bit-identical between grids (`max|Δ| = 0.0000` per bucket).
Cross-checked outside the view: the simulation's own window totals agree between grids to ~1e-15,
so the two inputs are genuinely one household rather than two similar ones.

**Against the monthly stack:** 14.08 kWh vs `household_load + standby` = 846.0 ÷ 60 =
**14.10 kWh/day**, at both resolutions. The 0.02 residual is the monthly stack's whole-kWh
rounding.

**SoC** differs between grids by up to 0.74 kWh per bucket on a ~9 kWh battery, and that
difference is **real, not an artifact** — comparing the raw per-interval `soc` arrays outside the
view gives the same 0.73 kWh spread, because the finer grid samples the same trajectory four times
per hour. Window means agree: 4.0967 vs 4.0963.

**DST**, 10-day windows straddling each transition, both grids: no divide-by-zero, no spike.
Spring-forward's 02:00 sits level with its neighbours (that day is absent from the day count);
fall-back's runs ~10% high (two hours' intervals, one day), shrinking proportionally on longer
windows.

Cost: 0.038 s at 8,760 hourly intervals, 0.095 s at 35,040 15-minute intervals, against the
~0.12 s `run_all` the page already performs.

### The regression test discriminates — verified by sabotage

`test_the_average_day_is_the_same_profile_at_hourly_and_15_minute_resolution` was added to
`tests/test_results_view.py`. The missing coverage was a **fixture property, not a weak
assertion**: every existing fixture is hourly, and at hourly resolution the wrong and right
aggregations agree exactly, so no strengthening of existing assertions could have caught this.

Confirmed in the orchestrating session rather than taken on report: temporarily restoring the old
`nanmean` makes the test fail with `At index 0 diff: 0.5 != 0.12` — the 4× ratio — and the file
was then verified byte-identical to its pre-sabotage state.

### Final test run, whole change present

- `tests/test_smoke.py` — **42 passed** (the only suite exercising a fresh install)
- `test_results_view` + `test_workspace_results` + `test_results_route` +
  `test_no_english_leakage` + `test_i18n` + `test_workspace_list` + `test_metrics` +
  `test_simulate` — **519 passed**
- Full suite not run; `tests/test_benchmark.py` never invoked.

### Also fixed: the committed `.pot` was stale

`app/locales/messages.pot` at HEAD predated the flows work — it still carried
`"Energy flows chart"` and lacked all 15 new msgids (verified against `git show HEAD:`). The
`.po`/`.mo` catalogues were correct, so nothing was user-visibly broken; the template had simply
not been regenerated. Now regenerated, which is why its diff is larger than the one added string.

### Remaining unverified, stated plainly

- Real Home Assistant data, at any resolution.
- A rendered 15-minute chart in a browser. The payload is verified and no template change was
  needed (the draw functions read the same keys with the same shapes), but that is inferred.
- Whether any real window contains an hour bucket with zero contributing days; the 0.0 fallback is
  exercised only by an all-gap probe.
- The Dutch footnote rendered in a browser, and whether the hatch stays legible on a very short
  bar.
- Two Dutch terms want a native check: `Curtailed` → "Afgeregeld", `Battery standby draw` →
  "Standby-verbruik batterij".

## Two explanatory notes under the flows charts, and a total-solar reference line

Two user requests, done in one pass because they touch the same three files. The user's own words,
recorded per `docs/specs/AGENTS.md` (this change does not itself modify `docs/specs/*`, but the
prompts belong with the feature they shaped):

> "in chart 1, lets add a note in small latters under the graph to explain that the bar height is
> always a bit higher than load because of battery standby. I assume the same applies for the
> average day chart? if so, also include the same note under that graph"

> "in the average day chart, I believe the stacked bars currently shown are those contributing to
> house load. am I right to understand there's some PV production not included there?"

The second question was correct: the average day stacks the LOAD-SOURCING decomposition, in which
PV appears only as `pv_to_home`. `chg_pv`, `exp_from_pv` and `curtailed` were on none of the bars,
and around midday those are routinely the larger part of production — so the chart understated what
the panels did at exactly the hours they did the most.

### The standby notes, and why they are gated

The gap between the stack top and the `household_load` line on charts 1 and 3 is the battery's own
draw (§6.9 hands the simulation `frame.load + standby_kw × dt`). Nothing on screen said so.

**Gated on a new `any_standby`, computed server-side from the CONFIGURED draw.** Three options were
available and the choice matters:

| Gate | Rejected because |
|---|---|
| No gate | `standby_w = 0` is a legitimate setting — `simconfig.py:1340` rejects only NEGATIVE values — and at 0 the stack sits exactly on the line. The note would explain a gap that is not on the screen: the same defect the partial-month footnote avoids via `any_partial`. |
| Template flag over the published series | `load_sourcing` is rounded to WHOLE kWh. A small draw over a short window can round to 0.0 in every month while the drawn gap, computed from unrounded figures, is still visible — the note would vanish from a chart that still shows the thing it explains. |
| **Server-side flag from `cfg.standby_kw`** | **Chosen.** Follows the `any_partial` precedent (computed where the data is, not recomputed in the template) and keys on the quantity that actually determines whether the gap exists. |

One msgid for both notes, not two: chart 3 draws the same three segments under the same reference
line, so the same sentence reads correctly under each and it is one translation rather than two.

Incidental fix while in the file: `_energy_flows` now uses the `cfg.standby_kw` PROPERTY rather than
`cfg.battery.standby_w / 1000.0`, closing the "carried, not fixed" item recorded earlier in this
changelog. Unreachable in practice (every call site passes a coerced config), but the property is
where the `None`-coercion lives.

### The total-solar line

`average_day.pv_total` added — the same `pv` array `pv_to_home` is derived from, masked the way
`household_load` is (`np.where(gap, np.nan, pv)`), through `_hourly_flow` because PV generation is a
FLOW. **Measured:** `pv_total − (pv_to_home + chg_pv + exp_from_pv + curtailed)` has a max absolute
per-bucket residual of **0.000000 kWh** at both 3600 s and 900 s, i.e. exact to the payload's 2 dp
rounding. The existing resolution-invariance test still passes, confirmed rather than assumed.

**Not added to `pv_allocation`.** That stack sums to PV generation by construction, so a total there
would draw a line along the top of its own bars.

**Drawn as a dashed line on the PRIMARY axis** (it is kWh moved per hour, like the bars) in
`#b45309` — a deeper amber than `pv_to_home`'s `#f5a524`. Same family, since both are solar and the
line bounds that segment from above, but separable from it and from the near-black load line.

**Suppressed entirely when the window generated no PV.** `simulation_frame` zero-fills an absent PV
series, so a household without panels is a reachable, non-error case that would otherwise get a flat
line on the axis plus a legend entry answering nothing. A new `any_pv` gates the line AND its note
together — a note without its line, or a flat line without its note, is each half an explanation.
Unlike `any_standby` this flag also travels in `#flows-data`, because the line is drawn client-side;
it is derived from the summed SERIES rather than a config field because PV presence is a property of
the DATA, not a setting.

### Wording

Both notes were written long first and cut hard on the user's instruction ("far too long"). The
partial-month footnote is the upper bound; a comment in the template says so, because the natural
edit for a later reader is to re-expand them. No bare `%` in any msgid, per the existing convention.

### Two failures worth recording — both self-inflicted, both caught

**1. A Jinja comment inside a `{{ … }}` expression is a syntax error that fails SILENTLY.** Two
rationale comments were placed inside the `#flows-data` expression. `pybabel extract` then returned
**zero** strings for the whole file — no error, exit status 0 — and the next `pybabel update`
marked every msgid in it obsolete. Recovering meant `git checkout` of the catalogues, which also
discarded the 15 uncommitted Dutch translations from earlier flows work; those were re-translated.
A note in the template now records the failure mode.

**2. Writing the comment delimiters in prose CLOSES the comment.** The note explaining failure 1
contained a literal `#}`, which ended the comment early and dumped the remaining prose into the
rendered page. Caught by `test_no_english_leakage.py` — 14 failures, exactly what that test exists
for. The comment now says why the delimiters cannot be written out.

### Files modified

- `app/results_view.py` — `any_standby` and `any_pv` added to the payload; `average_day.pv_total`
  added via `_hourly_flow`; `cfg.standby_kw` property used instead of the raw field; docstring
  gains sections on the two reference lines and both gates; module index entry updated.
- `app/templates/_panel_results.html` — two `any_standby`-gated standby notes (one shared msgid),
  one `any_pv`-gated solar note, `pv_total` label, `any_pv` in the data node.
- `app/templates/workspace_results.html` — `pv_total` colour in `FLOW_COLORS`; the dashed
  total-solar trace on the average day, conditional on `d.any_pv`.
- `tests/test_workspace_results.py` — two tests, both confirmed to discriminate by sabotage.
- `app/locales/**` — three new msgids, Dutch complete.

### Verified

Test numbers, whole change present:

- `test_results_view` + `test_workspace_results` + `test_results_route` + `test_no_english_leakage`
  — **347 passed**
- `tests/test_smoke.py` — **42 passed**
- `nl` catalogue: **0 untranslated, 0 fuzzy**, no `python-format` flag on any new entry. `en` sits
  at its pre-existing 76 empty entries (unchanged baseline, confirmed against HEAD).
- Full suite NOT run; `tests/test_benchmark.py` never invoked.

Two permanent tests added, each verified to FAIL when its gate is forced true:

- `test_the_standby_note_appears_only_when_the_battery_actually_draws_standby` — asserts by COUNT
  (2 occurrences), since a guard applied to only one of the two charts would pass a substring check.
  Unlike the partial-month flag, this path is reachable from a plain saved configuration, so it
  patches nothing.
- `test_the_total_solar_line_and_its_note_appear_only_when_the_window_generated_pv` — both halves
  (markup and payload flag), plus `pv_total >= pv_to_home` in every bucket, which a series wired to
  the wrong array would fail.

**Observed in Chromium** (real uvicorn, seeded 30-day hourly dataset), three configurations:

| | PV + 30 W | no PV + 30 W | PV + 0 W |
|---|---|---|---|
| `any_pv` in payload | true | **false** | true |
| standby note occurrences | 2 | 2 | **0** |
| solar note occurrences | 1 | **0** | 1 |
| `Total solar production` trace on `#flows-avgday` | present, `y`, `#b45309` | **absent (5 traces, not 6)** | present |
| peak `pv_total` | 2.50 kWh at hour 14, vs `pv_to_home` 0.44 | — | 2.50 at 14, vs 0.41 |
| three plot divs 876×256 | yes | yes | yes |
| pageerrors | none | none | none |

The no-PV column is the load-bearing one: the trace is absent from Plotly's own trace list rather
than merely drawn at zero, and both gates move independently of each other.

**The Dutch render was also observed in a browser** — a gap every previous section of this changelog
left open. Both notes appear in Dutch, and the average day's legend reads Uit de batterij / Van het
net / Rechtstreeks van zon / Huishoudelijk verbruik / Totale zonopbrengst / Laadtoestand, with the
same gating in all three configurations.

### Not verified

- Real Home Assistant data, at any resolution — unchanged from every earlier section.
- The rendered chart at 15-minute resolution. `pv_total` goes through `_hourly_flow` and the
  invariance test covers the payload, but no 15-minute chart was rendered in a browser.
- Whether `#b45309` stays distinguishable from `#f5a524` for a red-green colour-blind reader. The
  two are deliberately close in hue, which is the risk; not tested.
- Whether "Totale zonopbrengst" and "standby-verbruik" read naturally to a native speaker. Both are
  defensible; this joins the two terms already flagged for a native check above.

## The standby note was rewritten for terseness (user instruction)

The first version of the note ran to two sentences. The user's instruction, verbatim:

> the small text to explain standby is currently way too long (too many words). make it very terse
> - "The bars can be higher than house load because of battery standby power."

The supplied sentence was used exactly as given, replacing:

> The stacked bars sit a little above the household load line because the battery draws a small
> amount of power continuously for its own electronics. That draw is included in what the battery
> had to serve.

Both charts share one msgid, so the single replacement covered chart 1 and the average day. The
`any_standby` gating was not touched. The old msgid is obsoleted (`#~`) in both catalogues.

This sets the register for the tab's small print generally: one short sentence, no second sentence
explaining the mechanism. The solar-line note was written to the same standard rather than to the
longer style the standby note started with.

## Accessibility: the two solar colours are below the WCAG floor

`pv_total` (`#b45309`) and `pv_to_home` (`#f5a524`) are deliberately the same amber family — both
are solar, and the line bounds that segment from above. Measured contrast between them is
**2.46:1**, under the 3:1 WCAG floor for non-text graphical objects, and they are adjacent on the
chart by construction.

The colour choice was kept (the semantic kinship is right) and the non-colour cue strengthened
instead: the line is now `width: 3` on top of its existing `dash: 'dash'`, so shape carries the
distinction where contrast is weakest — exactly where the line crosses the segment it bounds.
Not re-tested with a colour-blindness simulator; the measurement is the evidence, and the fix
addresses it by not relying on colour.

## A silent failure mode in the translation cycle, now documented

Worth recording because it cost real work and gives no error. A Jinja comment placed inside a
`{{ … }}` expression is a syntax error that fails **silently** under `pybabel extract`: it returned
zero strings for the whole file with **exit status 0**, and the next `update` then marked every
msgid in that file obsolete. Recovery required `git checkout` of the catalogues, which discarded 15
uncommitted Dutch translations from the earlier flows work; they were re-translated.

A follow-on error had the same shape: a comment explaining the first failure contained a literal
`#}`, which closed the comment early and dumped prose into the rendered page.
`tests/test_no_english_leakage.py` caught that one with 14 failures.

Both failure modes are now documented in the template itself. The general lesson: in this repo a
green `pybabel extract` is not evidence that extraction worked — check the string count.

## Incidental fix

`_energy_flows` now uses the `cfg.standby_kw` property rather than the raw `cfg.battery.standby_w`
field, closing the item carried above as "not a live bug". Unreachable in practice (every
`results_from` call site passes a coerced config), but the `None`-coercion belongs there.
