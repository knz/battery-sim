# Results screen layout revamp

## Task Specification

Revamp the layout of the **results screen**, with **no change in functionality**.

Current state at the start: a battery pane at the top, followed by "panel ③" holding the results.

Requested changes (initial):

1. Remove the "③" marker from the title of the results panel.
2. Inside the **top panel**, create two cards side by side: battery settings left, the time
   interval selector (presets, the two custom date pickers, Apply) right.
3. The results panel therefore no longer carries the interval/date selector.

Explicit constraint: **layout only** — same routes, same form semantics, same submitted
parameter names, same simulation behaviour.

### Requirements added mid-conversation

4. The preset ribbon overflowed the narrower card → make it wrap.
5. The new card's title "Period" needs a Dutch translation.
6. Hide the start/end date pickers by default; add a **"custom"** entry to the ribbon; show the
   pickers only when "custom" is picked. Dutch: "aangepast".
7. Date pickers display MM/DD/YYYY — wanted DD/MM/YYYY.
8. The date-format hint must only show when the start/end pickers are showing.

Standing instruction added mid-task: **keep test runs focused** — the full suite is slow because
it contains benchmarks.

## Working context

- Worktree `.claude/worktrees/uiux`, branch `wt/uiux`, forked from
  `feat/pending-affordance-backend` at `73e0c7f`. Own `.venv` and `node_modules`.
- `npm install` in a worktree rewrites `package-lock.json`'s `"name"` to the directory name.
  Incidental; discard rather than commit.

## High-Level Decisions

**The period card is a THIRD swappable fragment, not markup nested in the battery box.**
The screen already swapped two fragments with *different* server context: `POST /params`
re-renders `_panel_params.html` with no `results` key, `POST /results` re-renders
`_panel_results.html`. Nesting the period controls in the battery box would have blanked them on
every Calculate. So `_panel_interval.html` gets its own root, `#panel-interval`, outside both.
(Chosen by the user from three options; the alternatives were client-side DOM updates and
server-rendering both panels.)

**`POST /results` returns two fragments joined by a marker comment** (`PANEL_SPLIT`), which the
client splits and swaps into `#panel-interval` and `#panel-results` separately. A single wrapper
element was not available: the card sits in the two-column row and the panel spans full width
below it, so no container encloses just those two. One request rather than two, so the halves
cannot describe different windows.

**"custom" is a mode, not a preset.** It carries no `data-period`, so the delegated handler that
POSTs `{"period": token}` skips it; its own handler only reveals the date row. Nothing recomputes
until Apply, because there is no range to run until the user gives one.

**Whether a window is "custom" is stated by the caller, never inferred.** `_period_selected_for`
maps a window's *span* back to the nearest preset — all it can do with two datetimes — so an
applied 7-day range came back highlighted as "1 week" with the picker hidden again. The route now
reads the fact off the request body and passes `results_from(custom_range=True)`.

**The date-format hint is computed in the browser.** A native `<input type=date>` renders in the
*browser's* locale; the page cannot override it via `lang`, an attribute, or CSS (verified: en-US,
en-GB and nl-NL contexts all rendered MM/DD/YYYY in headless Chromium, and `html lang` changed
nothing). Forcing DD/MM/YYYY would mean replacing the native control with text inputs and losing
the calendar popup, mobile keyboard and built-in validation. The user chose native + a hint;
`Intl.DateTimeFormat().formatToParts()` resolves against the same locale the control uses, so the
hint states the browser's actual order rather than a generic note. The three phrasings are gettext
strings rendered as `data-` attributes; the script only picks between them.

**Topology SVGs use container queries.** Halving the battery box's width squeezed the Installation
tab's illustrations to ~154px, which the smoke suite caught. §2′.6 gave that selector its own tab
precisely because it "needs width". `sm:` keys off the viewport, so at 1280px it still forced 2–3
columns into a half-width card; `@container` + `@md:`/`@lg:` puts the decision where the constraint
actually is. Tailwind v4 has this built in — no plugin.

**The preset ribbon is a wrapping flex, no longer a daisyUI `join`.** A `join` cannot wrap:
`join-item` rounds only the first and last child, so a wrapped join shows flat-edged buttons
mid-row.

## Requirements Changes

Items 4–7 above arrived during implementation and were folded in. Item 7 could not be delivered as
literally stated (browser-controlled); the trade-off was put to the user, who chose the hint.

## Files Modified

**Created**
- `app/templates/_panel_interval.html` — the period card: presets + "custom", the collapsible date
  row, the window line, the cost toggle. Every id/name preserved from its former home.

**Modified**
- `app/templates/_panel_results.html` — moved block and `period_buttons` removed; `③` badge
  dropped; header docstring rewritten. Re-resolves `cost_blocked` locally (see Obstacles).
- `app/templates/workspace_results.html` — two-column grid for the control cards; `recompute()`
  splits and swaps both fragments; `currentResultsBody()` reads the active preset from
  `#panel-interval`; custom-button handler; `applyDateFormatHint()`; docstring rewritten.
- `app/templates/_panel_params.html` — Installation tab marked `@container`; its three topology
  grids switched from `sm:` to `@md:`/`@lg:`.
- `app/main.py` — `PANEL_SPLIT` constant; `results()` renders both fragments and passes
  `custom_range`; module, `index()` and `results()` docstrings updated.
- `app/results_view.py` — `custom_range` keyword; `PERIOD_SELECTED_CUSTOM`; new
  `period_start_date` / `period_end_date` view-model keys (effective window, for pre-filling).
- `app/locales/{nl,en}/LC_MESSAGES/messages.{po,mo}`, `messages.pot` — five new msgids:
  "Period"/"Periode", "custom"/"aangepast", and the three date-order hints.
- `app/static/app.css` — rebuilt (`npm run build:css`) for the container-query classes.
- `tests/conftest.py` — `split_panels()` and `ids_inside()` helpers.
- `tests/test_results_route.py` — four new tests (the custom-mode contract, and the hint's nesting
  inside the collapsible picker); one assertion scoped to the results half of the response.
- `tests/test_workspace_results.py` — the cost-toggle placement test rewritten for the new layout.

## Rationales and Alternatives

- **Marker comment vs. two requests vs. a wrapper div:** a wrapper is impossible given the layout;
  two requests could disagree about the window. The marker keeps one round-trip.
- **`custom_range` keyword defaulting to False** rather than a new required argument, so every
  existing `results_from` caller stays correct without edits.
- **Date fields pre-filled with the EFFECTIVE window** (after clamping to coverage), so a request
  reaching past the data shows what was actually simulated rather than what was typed.
- **Date row `hidden` rather than absent**, so the inputs keep their ids in the DOM for the
  delegated Apply handler.

## Obstacles and Solutions

- **`cost_blocked` silently broke.** It was a `{% set %}` local inside the moved block; the
  invitation box in `_panel_results.html` still read it, and Jinja's undefined is falsy — so the
  box offered "Enable cost simulation" (a link to a *disabled* radio) exactly where §2′.7 forbids
  it. Caught by two existing tests. Fixed by re-resolving it in that file.
- **Topology SVGs squeezed to 154px** by the half-width card → container queries (above).
- **Ribbon overflowed the card** → wrapping flex instead of `join` (above).
- **An applied custom range snapped to the nearest preset** → `custom_range` flag (above).
- **DD/MM/YYYY not settable** on a native date input → hint computed via `Intl` (above).
- **The format hint stayed visible under a collapsed picker.** It was a SIBLING of the collapsible
  row, and a `hidden` class governs one element, not the markup that follows it — so the card
  explained the format of two fields the reader could not see. `#results-range` now wraps the
  fields *and* the hint, so one class governs the whole picker; the id the JS toggles and
  `aria-controls` points at is unchanged, so no handler needed touching.
- `tests/screenshot.py` hardcodes `/`; a scratchpad script was used to reach the results screen.

## Verification

- `tests/test_results_route.py`, `test_workspace_results.py`, `test_results_view.py`,
  `test_i18n.py`: **270 passed**.
- The hint-nesting test was checked against the OLD markup and fails there, so it catches the
  regression rather than passing vacuously.
- `tests/test_smoke.py` (Playwright): **41 passed** — including the SVG-width test that caught the
  squeeze, and the period-click and cost-toggle tests that pass unchanged, which is the evidence
  the moved controls still behave identically.
- The full suite passed (1337) at the mid-point, before items 6–7; since then only focused runs,
  per the user's instruction.
- Browser-driven checks of the new behaviour: date row hidden on load; "custom" reveals it,
  pre-filled and focused; Apply keeps custom active with no preset highlighted and the fields
  holding the applied range; picking a preset re-hides the row. Format hint verified under en-US,
  en-GB and nl-NL. Screenshots taken in both languages.

## Current Status

Complete and verified; **not committed** — the working tree holds the changes for review.

Open / deferred:

- The two control cards have unequal heights (`items-start`, so the shorter one does not stretch).
  Deliberate, but a taste call worth confirming.
- The screen's spec text (`specs/20-workspaces-ux.md` §2′.6/§2′.7) still describes the period
  controls and the cost toggle as living inside the results block. The code now differs; the spec
  has not been updated, and whether to amend it is the user's call.
- `tests/screenshot.py` still hardcodes `/`, so it cannot capture the results screen. Could take a
  path argument.
- The hint's *content* (which order `Intl` reports) is not covered by a test — only its nesting is.
  It was verified manually under en-US, en-GB and nl-NL. The reveal/hide interaction is likewise
  browser-verified rather than tested. The route-level custom-mode contract IS covered.
