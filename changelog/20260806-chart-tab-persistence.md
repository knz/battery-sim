# Persist the selected chart tab across a recompute

Small follow-up to `20260806-average-day-diverging.md`. Nothing about the charts themselves
changes; this is about which one is on screen after a fragment swap.

## Task specification

> when I change parameters / recompute, which graph tab is currently selected is lost (resets to
> the first tab). i'd prefer if it would persist (browser-side)

Asked where the selection should live. The user chose **in-page only** — a variable on the
never-swapped page — over `sessionStorage` or `localStorage` keyed by workspace.

## The behaviour being changed, and why it was that way

The reset is not an oversight. `workspace_results.html` says so in two places, in comments written
when the euro view was added:

> The selected view is held on the chart container rather than in a variable, so a fragment swap
> (which replaces the container) resets to the default — which is what should happen: a swap means
> a new window, and the euro series may not exist for it.

That reasoning is sound about the €-series HAZARD and wrong about the CONCLUSION. The risk is
real: `Monthly savings (€)` is rendered only `{% if results.monthly_saved_eur %}`, and `Energy
flows` only `{% if results.energy_flows %}`, so a swap genuinely can return markup in which the
previously-selected tab does not exist. But resetting unconditionally solves that by discarding
every selection, including the ones that are still perfectly valid — which is the behaviour the
user is objecting to.

So the fix restores the selection *conditionally*: remember it, and after the swap re-apply it
only if a button carrying it came back in the fresh markup. If it did not, fall through to the
default. The hazard the old comment identified is still handled; it is just handled by checking
rather than by forgetting.

## Design

**One variable, not one per attribute.** The strip carries two attributes doing two jobs
(`data-chart-tab` = which container, `data-chart-view` = which monthly series), and a single
button can carry both. Rather than track them separately and risk an incoherent pair, the saved
state is the pair as the user last selected it, and re-application looks for a button matching
that pair.

**Re-apply by REPLAYING the click handler, not by duplicating it.** The handler already does four
things (highlight one button, toggle two containers, set the view attribute, draw). Re-applying
state after a swap needs exactly those four things, so the handler body moved into a named
`selectChartTab(btn)` and both paths call it. A second copy would have been a second place to
forget the `hidden`/`flex` pairing.

**The default stays in the markup.** `btn-active` on the first button and `hidden` on
`#flows-charts` are how the server renders the panel, and that is still what an unrestorable
selection falls back to — the restore path does nothing at all in that case rather than actively
resetting anything.

## Scope

Deliberately excluded: the *pending* `SoC + price` tab. It carries no `data-chart-tab` (per the
existing rule that a pending tab must not look like a working one), it never becomes the selection,
and it opens a dialog instead. Nothing here touches it.

Also excluded: the `<details>`/tab state of the params pane, which already has its own
`readPaneState`/`applyPaneState` pair for the same class of problem. This change follows that
established shape rather than generalising the two into one mechanism — they carry different
state across different swaps.

## Files modified

- `app/templates/workspace_results.html` — extracted `selectChartTab()` from the click handler;
  added the saved-selection variable, `rememberChartTab()` and `restoreChartTab()`; called the
  restore from the results-swap success path. Two comments rewritten where they asserted the reset
  was desirable.
- `app/templates/_panel_results.html` — header comment notes that the two data- attributes are also
  the restore's selector, and that this template still renders the default.
- `tests/test_smoke.py` — two browser tests (below).

No Python changed: this is entirely browser-side, as asked.

## Verification

Both tests are in `test_smoke.py` rather than `test_workspace_results.py`, and that placement is
the point. The MARKUP is identical before and after this change — the panel renders the default
either way, correctly — so no assertion on the server's HTML can see the defect. What changed is
what the browser does with that markup after a swap. The suites in `test_workspace_results.py`
(349 tests) were green with the defect present and are green now.

- `test_the_selected_chart_tab_survives_a_recompute` — selects *Energy flows*, changes the battery
  capacity, presses Calculate, and asserts the container is still visible, the strip still
  highlights that tab, the monthly container is not also showing, and the chart was actually
  REDRAWN (`#flows-avgday svg`) rather than merely un-hidden. Then repeats over a period change,
  which swaps the same panel by a different path. **Confirmed to discriminate** by commenting out
  the `restoreChartTab()` call: it fails with "the recompute dropped the reader back on the first
  tab", which is the user's report.
- `test_a_swap_that_removes_the_selected_tab_falls_back_to_the_default` — the hazard case. Selects
  the €-series tab, clears `simulate_cost` server-side so the next swap renders a strip without
  that button, and asserts exactly ONE tab is active (not zero — a strip claiming nothing — and not
  two), that it is the default, that the chart is drawn, and that no page error was raised.

Full runs: 44 browser smoke tests, and 349 across `test_workspace_results`, `test_results_route`,
`test_results_view` and `test_no_english_leakage`.

## Current status

Complete.

Not covered: whether the selection should also survive a full page RELOAD. It does not, by the
storage choice made above, and that is the intended behaviour rather than a gap.
