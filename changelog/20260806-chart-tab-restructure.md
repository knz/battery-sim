# Chart tab strip: reorder, drop monthly grid import, split the view-pair

## Task specification

The user's original request, verbatim:

> in the result screen, there's a tab selection for the graph display.
> - move "energy flows" to first position, make it default
> - remove "monthly grid import" graph since it's superseded by "energy flows"

### Clarification raised

"Monthly grid import" and "Monthly savings (€)" are not two tabs. They are two
VIEWS of one container (`#monthly-chart`), selected by a second attribute
`data-chart-view` (`kwh` | `eur`) that rides alongside `data-chart-tab`.
Removing the kWh view therefore does not simply delete a tab: it leaves the €
view as the sole occupant of a container whose whole reason for having a view
attribute was that it held two series.

Options put to the user: keep € as a standalone tab; remove the whole monthly
container (rejected in the asking — Energy flows is kWh-only, so this would
lose the euro series from the panel entirely, and it does NOT supersede it);
or reorder only.

The user's answer, verbatim:

> would it be an idea to make the two charts actual separate charts? instead of
> data-chart-view?

So the scope is larger than "delete a button" and smaller than "delete a
chart": the €-savings series becomes its own tab with its own container, and
the `data-chart-view` mechanism goes away with the kWh series it was
distinguishing.

## High-level decisions

### 1. `data-chart-view` is removed, not merely reduced

The strip carried two attributes doing two jobs: `data-chart-tab` (which
container is visible) and `data-chart-view` (which series `#monthly-chart`
draws). The second existed only because ONE container held two series; it
predates `data-chart-tab` and is the sole thing in the strip that is not a
plain tab.

With the kWh series gone there is nothing left to distinguish, so the attribute
goes with it. Afterwards the strip is one concept: a button names a container,
`CHART_TABS` says how to draw it. This removes the view logic from four places
(`selectChartTab`, `rememberChartTab`, `restoreChartTab`, and the remembered
`{tab, view}` pair, which collapses to a plain tab key).

### 2. The server keeps `_monthly_import()` and `results["chart"]`

Checked before assuming it was dead. It is not:

- `app/sample_data.py:458` builds the key for the static sample.
- `tests/test_results_view.py:2204` uses `len(r["chart"]["values"])` as the
  reference length the euro series must match.
- `_monthly_import`'s calendar-month bucketing is documented as the reference
  that `_energy_flows` and `_monthly_saved_eur` deliberately mirror
  (`results_view.py:1078`, `:2414`).

So only the UI stops plotting it. The payload becomes unplotted-but-emitted,
which is a real (small) cost — recorded as a followup rather than removed
silently, since removing it is a server-side change the user did not ask for
and would touch the bucketing reference three view-models point at.

### 3. Every tab is now conditional — two consequences handled explicitly

The old strip always had `Monthly grid import`, unconditional and hardcoded
`btn-active`. All three surviving tabs are conditional, so:

- **The default cannot be a hardcoded `btn-active` on the first button.** It is
  chosen server-side as the first tab that actually renders, with the
  containers' `hidden` state following the same choice, so there is no
  client-side flash and no state where the strip highlights a tab whose
  container is hidden.
- **The strip can now be empty**, which was previously impossible. That renders
  as a stated absence rather than an empty bordered card.

### 4. Order and default

`Energy flows` first and default (as requested), then `Battery rhythm`, then
`Monthly savings (€)`. The euro tab goes last: it is the one whose absence is
most likely (cost simulation off), so a strip that loses it keeps the same
leading order rather than reshuffling.

### 5. "Superseded by Energy flows" is true of the QUESTION, not of the number

The request gives supersession as the reason for removal. Checked rather than
repeated: the two are not the same quantity.

- `_monthly_import()` is MEASURED total grid import over the window — the
  meter, including whatever would have charged a battery the household did not
  have.
- *Energy flows*' `imp_home` bars are grid import serving HOUSEHOLD LOAD under
  the simulated run, one segment of a stack that also carries `dis_home` and
  `pv_to_home`.

So a reader cannot read the old bar's value off the new chart. What is
genuinely superseded is the question — where the household's energy came from,
month by month — which *Energy flows* answers by source rather than as one
undifferentiated total, on the same monthly axis.

The removal stands: it is the user's call and it is defensible on its own
terms. G1 in `docs/specs/followups.md` records that this very chart, under its
earlier "Monthly savings" label, was read as ~11× the actual saving — a chart
whose honest label had to say it was NOT the thing beside it was already
carrying its own hazard. But the spec states the supersession accurately rather
than asserting an equivalence that does not hold.

## Files modified

- `changelog/20260806-chart-tab-restructure.md` — this file.
- `app/templates/_panel_results.html` — `Monthly grid import` button and the
  `#monthly-chart` container deleted; strip reordered to Energy flows /
  Battery rhythm / Monthly savings (€), all three conditional; a
  `{% set default_chart_tab %}` chain picks the first tab that renders, and
  every `btn-active` and every container `hidden`/`flex` class derives from
  that one value; new `#saved-eur-chart` container; `#monthly-data` →
  `#saved-eur-data`, now conditional and carrying only the euro series; new
  absent-state line for the empty strip; header and in-body comments rewritten.
- `app/templates/workspace_results.html` — `drawMonthlyChart` →
  `drawSavedEurChart`, no view branching; `CHART_TABS` reordered with a
  `saved_eur` entry; `data-chart-view` removed from `selectChartTab`, and
  `selectedChartTab` collapsed from `{tab, view}` to a plain key;
  `initPanelResults()` reads the server's `btn-active` back and draws THAT tab
  instead of a hardcoded one; header and inline comments updated.
- `app/locales/` — one msgid added (the absent-state line), one retired
  (`Monthly grid import`); `.po`, `.pot` and both `.mo` regenerated.
- `docs/specs/02-ux-wireframes.md` — §2.4 wireframe strip reordered; the
  view-pair bullet replaced by one on per-container charts and one on
  conditional tabs and the default.
- `docs/specs/followups.md` — C1 narrowed; C1a opened.
- `tests/test_results_route.py` — the old view-pair test rewritten as
  `test_the_euro_savings_chart_is_a_tab_of_its_own_gated_on_cost`; new
  `test_the_chart_strip_default_is_the_first_tab_that_actually_renders`.
- `tests/test_smoke.py` — `test_chart_rendered` became
  `test_the_charts_box_states_its_absence_when_no_tab_renders`; the
  survives-a-recompute test retargeted to *Monthly savings (€)* (with Energy
  flows now the default, asserting the default survives a swap that re-renders
  the default is a tautology); new
  `test_the_default_chart_tab_is_drawn_on_first_load`.

## Obstacles and solutions

**The first-load draw path had no test at all.** Not a regression — it was
never covered, because every browser test either clicks a tab (which draws it)
or asserts after a swap (where the fetch handler redraws everything). It
mattered here specifically because this change made the default a SERVER
decision, so `initPanelResults()` had to start reading it back rather than
calling one hardcoded draw — new logic on an uncovered path. Found by
sabotage, not by review. Test added; verified independently by re-sabotaging
(`if (false && ...)`) and confirming it is the only test that fails.

**The `flex`-flag agreement between template and `CHART_TABS` cannot be
tested.** Flipping `saved_eur`'s flag broke nothing: a `flex` container with
one full-width child lays out exactly as a block one, so there is no symptom to
assert on. No test was invented for it — one reading the class attribute back
would check the template against itself rather than against a behaviour. Left
as a review-enforced invariant, with the comment saying so explicitly, and
recording that sabotage is what established it is unenforceable, rather than
implying a check exists.

**The empty-strip test rests on an implicit precondition.** It works because
this smoke module's shared workspace is never given data. If a future test
seeds that workspace, the test would quietly stop testing the empty strip
rather than fail. Made explicit with an assertion that panel ③ rendered at all,
so that failure mode is a failing test rather than a green one that has changed
meaning.

**The absence line asserted something that can be false.** As first written it
read "No charts for this window: there is no simulated data to draw, and cost
simulation is off", on the reasoning that both are always true together in the
empty state. They are not. All three tabs sit behind
`frame is not None and frame.intervals > 0` in `results_from()`, and
`monthly_saved_eur` behind the cost guard INSIDE that — so an empty strip means
there is no FRAME and implies nothing at all about `simulate_cost`. A user with
cost simulation ON and no data would have been told their cost simulation was
off: a statement about their own configuration, and wrong.

Corrected to name only what the state implies ("…there is no simulated data to
draw"), with the template comment recording why the cost setting must not be
named here. Catalogs re-extracted, re-filled and recompiled; the earlier msgid
is retired to `#~` in both.

This is the same class of defect as the "tile above"/"tile below" footnote the
user caught in `20260806-battery-money-heatmap.md`, and it is worth naming as a
pattern: **sabotage testing establishes that code does what the code says, and
cannot see prose that describes the world wrongly.** Both escapes were English
sentences asserting a fact about state or layout that no test reads. Found here
by tracing the guard conditions in `results_from()` back from the template
rather than by running anything.

## Verification

Independently re-run by the orchestrator, not taken from the implementing
agent's report:

- 418 focused tests pass (`test_smoke`, `test_results_route`,
  `test_workspace_results`, `test_no_english_leakage`, `test_results_view`).
- `tests/test_benchmark.py` was never invoked, per the standing constraint.
- 9 sabotages run by the implementing agent, 7 caught. The two that were not
  are the `flex` flag (no symptom — documented above) and the first-load draw
  (test added). The first-load sabotage was independently repeated here.
- Catalogs verified by reading the compiled `.mo` files rather than trusting
  the report — followup G2 records a changelog claiming a recompile that had
  not happened. Both locales are 100% translated (nl 496/496, en 409/409), the
  new msgid is translated in both, and `Monthly grid import` is absent from the
  compiled catalogs.
- Confirmed no `data-chart-view`, `drawMonthlyChart`, `#monthly-chart` or
  `#monthly-data` identifier survives in `app/` or `tests/` outside historical
  references in explanatory comments.

## Current status

Complete, not committed. `app/results_view.py` and `app/sample_data.py` were
deliberately not touched.

Carried, not done:

- **C1a** — `results["chart"]` is still computed and serialised on every render
  with nothing plotting it.
- **C1** — the per-month kWh saving series remains unbuilt; only its euro
  counterpart ships.
- The `flex`-flag invariant is enforced by review only.
