# Results-screen period: smarter default window + data-availability warning

## Task specification (as given)

1. Pick the initial default interval on the results screen as the **intersection of "the last
   year" with the interval for which consumption/production (grid meter) data exists**.
2. If PV data is also available, narrow that default further to its **intersection with the part
   of the period that has PV data**.
3. If the resulting default equals the whole last year, preselect **"last 1 year"** in the period
   ribbon; otherwise preselect **"custom"**.
4. Whenever the user selects a predefined period: if the selected period **contains a boundary of
   any data series** (i.e. some series is unavailable over part of it), show a small-print warning
   that some data is unavailable for the selected period.

## Current state (as read, before changes)

- `app/results_view.py`
  - `PERIOD_DAYS` — five presets, spans in days.
  - `DEFAULT_PERIOD = "last_1_year"`.
  - `resolve_window(dataset, period=, start=, end=)` — presets anchor the window END to the
    **grid-meter** coverage end (`_coverage_window`, `_WINDOW_SLOTS` = the four grid registers),
    reaching back `days`, clamped to coverage start. Explicit ranges are clamped to coverage.
  - `_period_selected_for(dataset, window)` maps a resolved span back to the *nearest* preset
    label — presentation only; `PERIOD_SELECTED_CUSTOM = "custom"` is set by the caller via
    `results_from(..., custom_range=True)`.
  - `_pv_coverage_mask` already knows the solar frame is `solar_production` and uses its own
    coverage; PV coverage today affects self-consumption, not the window.
- `app/main.py:874` — the initial page render calls `resolve_window(loaded)` with no arguments, so
  the default is today purely `last_1_year` anchored to grid coverage end.
- `app/main.py:1012+` (`POST /w/{id}/results`) — preset or explicit range; sets `custom_range`
  from the presence of start/end.
- `app/templates/_panel_interval.html` — the ribbon; `is_custom` drives the "custom" highlight and
  reveals the date fields (pre-filled from `period_start_date`/`period_end_date`). The window line
  under the pickers is `period_dates · N days · period_run`.
- `app/domain/frames.py` — `SeriesFrame.coverage()` returns first/last-interval bounds only;
  there is **no interior-gap API** today.

## Clarifications received

- **Gap definition: coverage BOUNDS only.** A series counts as unavailable over part of the window
  when the window extends past that series' first/last timestamp. No interior-hole scanning — that
  would need a new gap API on `SeriesFrame` (spacing > resolution). Recorded as a deliberate
  limitation, not an oversight: a mid-history sensor outage does NOT raise the warning today.
- **Series scope: ALL mapped series**, energy and price alike, not just the ones the energy figures
  are computed from.
- **Persistence: remember the user's choice per workspace**, rather than recomputing the default on
  every load.
- **Warning renders whenever it applies** — initial default, presets and custom ranges alike — not
  only after a preset click. It is a property of the resolved window.
- **Re-fetch behaviour (user, second round):** a stored PRESET re-resolves against the new coverage
  on every load (so a re-fetch moves the window); a stored CUSTOM range is kept verbatim.
- **Non-intersecting stored custom range (user, third round):** flip to the `last_1_year` PRESET and
  REWRITE the stored block to `{"preset": "last_1_year"}`, so the fallback is sticky rather than
  re-derived on each load. Partial overlap does NOT flip — it stays custom and is clamped by
  `resolve_window`, since it is still a range the user chose.

## Assumptions stated and confirmed by "go ahead"

1. **"Last year" is DATA-anchored** — the trailing year ending at the grid-meter coverage end
   (§7.4), not wall-clock `now()`. This is what makes step 1 equal to the existing
   `resolve_window(period="last_1_year")`. Under a wall-clock reading, step 1 would need its own
   computation and would yield a shorter window whenever the data ends in the past.
2. **"Consumption/production" in step 1 means the FOUR GRID REGISTERS** (`_WINDOW_SLOTS`), with PV
   handled separately in step 2. `solar_production` is deliberately excluded from `_WINDOW_SLOTS`
   (`app/domain/reconcile.py:58-61`) so a short PV series cannot clip the grid totals.

An earlier draft of the plan claimed step 1 was "exactly" what the existing preset computes. That
flattened a real choice into a non-choice: the two coincide only under assumption 1, and only
under assumption 2. Corrected here so the equivalence is not read as structural.

## High-level decisions

- **`retained.results_period` in the simconfig JSON**, not a new `workspace_state` column. The
  `retained` block already holds non-parameter per-workspace UI state (`pricing_configured`), the
  write path is atomic (`save`'s mkstemp + os.replace), and no schema migration is needed.
- **Discriminated by KIND, not by resolved dates:** `{"preset": token}` vs `{"start", "end"}`.
  Storing only the resolved `(start, end)` would be insufficient — a preset must be re-resolved
  against current coverage on every load for the re-fetch rule to work.
- **Nothing is stored until the user touches the ribbon.** The computed grid ∩ PV default is
  DERIVED state, not a choice. Persisting it on first load would freeze it against later
  re-fetches — precisely the problem the preset/custom split exists to avoid.
- **`is_preset` test:** the default preselects `last 1 year` only when step 2 changed nothing AND
  step 1 spanned a full 365 days. "More than a year of PV" alone is insufficient: with 400 days of
  PV but 200 days of grid data, step 1 clamps to 200 days and the result is still custom.
- **PV can move the END, not only the start.** The intersection is a plain interval intersection;
  if PV coverage ends before the grid's (a PV sensor that stopped reporting), the default window
  ends before the data does. Handled as an ordinary intersection rather than special-cased.
- **Empty grid ∩ PV intersection keeps step 1's window** (grid-only) rather than yielding nothing
  to simulate.

## Requirements change (user, fourth round): a "default" preset button

> "let's also add a 'default' preset the user can select which recomputes the default as we
> discussed (so they can reset to the known-good period)"

Added as a SIXTH ribbon button, leading the row. Decisions:

- **`PERIOD_DEFAULT = "default"` is NOT in `PERIOD_DAYS`, and `resolve_window` does not accept it.**
  Every other preset is a SPAN in days; this one is a RULE whose answer moves with the data.
  Keeping it out of that dict is what stops it being treated as a fixed span later. The routes
  branch on it before reaching `resolve_window`.
- **Stored as `{"preset": "default"}`**, so it re-derives on every load rather than freezing the
  dates it resolved to when pressed. Storing the resolved range would defeat the reason the user
  reaches for it.
- **`results_from` gained a `period_selected` override.** The button's resolved window is an
  ordinary pair of datetimes, indistinguishable after the fact from a typed range, so
  `_period_selected_for` would highlight whichever span-preset happened to be nearest. Only the
  route that honoured the request can say it came from this button. `custom_range` is a bool and
  could not carry a third state.
- **`default` + an explicit range is still a 400**, like any other preset — it is not an escape
  hatch from the mutual-exclusivity rule.
- No JavaScript changed: the button carries `data-period`, so the existing delegated click handler
  POSTs it and `currentResultsBody()` reads it back across a parameter save unchanged.

**Knock-on UX change, worth review.** A first visit now highlights "default" rather than "custom",
which is more accurate — the screen IS showing the derived window, and "custom" only ever meant
"none of the spans fit". The consequence is that the date fields no longer auto-open on a first
visit. They stay pre-filled with the window in force, so opening them shows real dates rather than
blanks. The test that pinned the old behaviour was renamed and re-pointed rather than deleted.

## Files modified

- `app/results_view.py` — added `default_window(dataset) -> (start, end, is_preset)` and
  `coverage_gaps(dataset, window) -> [ {series, label, covered_from, covered_to} ]`; `results_from`
  now emits `period_coverage_gaps`. New imports: `ROLE_LABEL` (from `data_view`), `SERIES_SLOTS` /
  `SLOT_BY_NAME` (from `domain.series_vocab`) — checked for import cycles, there are none.
- `app/simconfig_store.py` — `retained.results_period` with `load_results_period` /
  `save_results_period`; `to_dict` carries the slot forward verbatim. Module docstring's "two
  slots" section reworked to three, with the argument for the third made explicitly (the file's own
  rule is that no slot is added without one).
- `app/main.py` — new `_opening_window(workspace_id, loaded)`; `GET /w/{id}` uses it instead of the
  bare `resolve_window(loaded)`; `POST /w/{id}/results` records the choice.
- `app/templates/_panel_interval.html` — the small-print warning block; header comment updated.
- `app/locales/messages.pot`, `nl/…/messages.po`, `en/…/messages.po` + compiled `.mo` — two new
  msgids ("One series does not cover…" with its plural, "no data"), Dutch filled in.
- `tests/test_results_view.py` — 12 tests for `default_window` / `coverage_gaps`.
- `tests/test_simconfig.py` — 8 tests for the persistence slot.
- `tests/test_results_route.py` — 8 route tests for the opening window and the rendered warning.

## Obstacles and solutions

- **`save_results_period` silently dropped the choice when no config document existed.** Found by a
  route test, not by inspection: the `client` fixture seeds a dataset and a workspace row but never
  saves parameters, which is also the ordinary FIRST VISIT — fetch data, click a preset, before
  ever touching the parameter screen. Fixed by creating the document, carrying the `retained` block
  ALONE so that appendix-A defaults are not materialised into a file `load()` would then read back
  as the user's own choices. Pinned by two tests.
- **Two `default_window` tests initially asserted day 400 as the coverage end.** The test helper's
  advertised dataset window stops at day 365 and `effective_window` clips frame coverage to it. The
  code was right; the test's premise was wrong. One of the two ("disjoint PV") was additionally
  mislabelled — the PV frame did overlap — so it was split into a genuine partial-overlap case and a
  genuine disjoint one (PV history predating the meter's).
- **The sticky-fallback route test asserted the wrong observable.** After flipping to
  `last_1_year`, the ribbon highlights `last_30_days`: `_period_selected_for` maps the resolved span
  back to the NEAREST preset, and the year clamps to the 30 days that exist. Pre-existing
  presentation behaviour, unrelated to this change; the test now asserts the stored value (the
  actual contract) and the window, not which label lights up.

## Verification

- Full suite: **1431 passed, 25 skipped** (1397 passed before this work; 34 added).
- The "default" button renders leading the ribbon and active, in English ("default") and Dutch
  ("standaard"), and lands on the PV-narrowed window end to end through the route.
- Manual render against a realistic dataset (13 months of meter data, PV from 2026-04-01):
  the screen opens on 2026-04-01 → 2026-07-05 preselecting custom, with NO warning — every series
  covers that narrowed window, which is step 2 working as intended. Widening to `last 1 year` then
  raises the warning naming "Solar production (2026-04-01 → 2026-07-10)".
- Dutch render checked with two short series: plural form, translated role labels, correct spans.

## Known limitations (deliberate, not defects)

- **Bounds only.** An interior hole — a sensor that dropped out mid-history and came back — does
  NOT raise the warning. `SeriesFrame.coverage()` reports first/last only; detecting holes needs a
  new gap API scanning each index for spacing above its native resolution. A test pins the current
  behaviour so it is not mistaken for a bug.
- **The opening default will read as "custom" for most solar households**, since PV is usually
  mapped later than the meter. That follows from the spec as given; it is a visible change to the
  screen's first impression.
- The remembered period is per workspace and survives a parameter save. The "default" button is
  the reset affordance; there is no way to return to "nothing remembered", but pressing "default"
  is behaviourally identical to it.

## Current status

Complete. Specified behaviour implemented, tested and verified; catalogs updated and compiled.
Not committed — left staged for review.
