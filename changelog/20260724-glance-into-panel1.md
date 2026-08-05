# Move "Your data at a glance" inside panel ①

## Task Specification

**User's original prompt (verbatim):**

> request for UI change: we have an box of results "your data at a glance" repeated in two places
> (once immediately after data input, then one with clamped dates in the result pane)
>
> we'd like to change our initial vision for the first display, and instead have this data
> presented inside panel 1, below data quality and above the "next: parameters" button

Change the placement of the first (full-coverage) copy of the data-glance band: instead of an
unnumbered interstitial band between panels ① and ②, render it **inside panel ①'s expanded body**,
after the "Data quality" card and before the "Next: parameters →" CTA. The second copy (panel ③,
clamped to the selected range) is unaffected.

## Current State (pre-change)

- `app/templates/_data_glance.html` — shared `data_glance(data_summary, title=None)` macro.
- `app/templates/_panel_summary.html` — thin wrapper: imports the macro, renders it with the
  full-coverage `data_summary` context var. Documents the band's §2.3a "not a stepper panel"
  semantics.
- `app/templates/index.html:54` — `{% if data_summary %}{% include "_panel_summary.html" %}{% endif %}`
  between `_panel_data.html` and `_panel_params.html`.
- `app/templates/_panel_data.html` — panel ①: collapse section; body = intro, slot roster,
  drawer/dialog markup, "Data quality" card (l.191–244), then the CTA row (l.246–248).
- `app/main.py:98–123` — sets `ctx["data_summary"]` from `summary_view.data_summary_from(loaded)`,
  pops it in the empty state so the band is absent before the first fetch.
- Specs: §2.1 layout diagram, §2.3a (the band's own section), §3.4 state machine paragraph,
  §12 cross-references.
- Tests: `tests/test_smoke.py:137` asserts the band is absent in the empty state.

## Requirements Changes

A second requirement arrived mid-conversation, after the panel-① plan was approved.

**User's second prompt (verbatim):**

> likewise, inside panel 3, we'd like the results of this box to be styled like the energy savings
> below (with "your energy use..." styled like "energy savings" with a ruler on the right, and
> without a frame).

So this task covers BOTH copies: the first moves, the second restyles.

**User's third prompt (verbatim), on the divider label casing:**

> divider label casing: maybe use normal casing in the translation strings, and use css uppercase
> styling
>
> plan ok otherwise

**User's fourth prompt (verbatim)** — a follow-up after reviewing the result, plus a bug report:

> okay let's drop the repeated coverage/day-count line under the divider, but add the day count to
> the range picker above.
>
> also, I'm noticing a bug: if I collapse panel 1, then click on one of the info buttons in the
> "your energy usage" results, the explanatory popup does not appear but the page becomes
> unresponsive. please investigate

## High-Level Decisions

Settled with the user via clarifying questions (2026-07-24):

1. **Placement — inside panel ①'s body**, after the Data-quality card, before the "Next:
   parameters →" CTA. It is no longer an unnumbered interstitial band with its own §3.4 semantics;
   it is a section of panel ①, and therefore follows panel ①'s collapse/focus behaviour.
2. **Hiding on collapse is accepted.** When panel ① collapses to its one-line summary the glance
   figures go with it. The user can reopen ① at any time, and panel ③ carries the range-clamped
   copy. Rejected alternative: promoting a headline figure or two into panel ①'s collapsed summary
   line — extra surface for little gain, and the collapsed line is already carrying day-count and
   source summary.
3. **Panel ① framing — a peer of the Data-quality card** (`bg-base-200 border border-base-300`,
   `h3` heading), so the two read as sections of one panel body rather than a band floating inside
   a panel.
4. **Panel ③ framing — no card, a `divider divider-start` heading** matching the adjacent
   `ENERGY SAVINGS` divider. The group boxes stack directly below it.
5. **Three framing variants collapse to two.** The macro gains a `frame` argument: `"section"`
   (panel ①) and `"divider"` (panel ③). The original `"band"` look (`bg-base-100` card) loses its
   only caller when `_panel_summary.html` goes, so it is dropped rather than kept as dead markup.
6. **Divider label casing via CSS, not msgids.** The user's call: keep translation strings in
   normal sentence case and apply `uppercase` in the template. This matches what the macro's own
   group headings (`Grid`, `Household`, …) already do. Consequence: the existing shouted msgid
   `ENERGY SAVINGS` is the outlier and is converted too — msgid becomes `Energy savings`, the
   Dutch `ENERGIEBESPARING` carries over as `Energiebesparing`. Without this the two adjacent
   dividers would disagree on casing convention.
7. **Coverage/day-count line kept in the divider variant.** There is no card header to hang it on,
   so it renders as a muted line under the divider. Mildly redundant with panel ③'s range picker,
   but the band's other figures (solar's own span, the notes) are read against it, and dropping it
   would be a content change rather than the requested styling change.
8. **`_panel_summary.html` removed**, not left unreferenced, and §2.3a rewritten rather than
   deleted — its content rules (omit-don't-zero, the existing-battery framing, the unreliable-
   reconstruction suppression) still hold; only the placement/semantics paragraphs change.

## Obstacles and Solutions

1. **Translation extraction silently drops ~50 msgids.** Running the workflow documented in
   `babel.cfg` (`pybabel extract -F babel.cfg …`) rebuilt the catalogs 52 msgids smaller — the
   `.mo` files shrank ~6 KB — because `app/sample_data.py` marks its strings with the project-local
   alias `_N(...)`, which Babel's default keyword list does not know. Fixed by extracting with
   `-k _N --sort-output`; the documented workflow in `babel.cfg` was corrected and now says why the
   flag is required. Caught by comparing msgid sets against `HEAD`, not by any test.
2. **Panel-③ divider test anchored on the wrong occurrence.** The section title appears twice (the
   `aria-label`, then the divider text); the first is before the divider. Anchored on the second.
3. **The data-glance macro never translated (pre-existing bug, found while verifying Dutch).**
   `{% from "_data_glance.html" import data_glance %}` without `with context` does not pass the
   importing template's context, which is where Jinja's i18n extension installs the per-request
   gettext functions. The macro's strings therefore froze at whichever locale rendered FIRST in the
   process and never changed: an English-first server showed an English band (title, group
   headings, ⓘ aria-labels) to Dutch users forever, and a Dutch-first server did the reverse.
   Both copies were affected; it predates this task (panel ③'s copy had it too) and was invisible
   in tests because each test process happened to render Dutch first. Fixed with `with context` on
   both imports, documented inline, and covered by a regression test that requests English before
   Dutch — the ordering that reproduces it. A Dutch-first test passes with the bug present.

## Follow-up round (same session)

9. **The panel-③ coverage line is dropped; the day count moves to the range picker.** The line
   under the divider heading repeated what the picker above already said. The picker's coverage
   line now reads `<dates> · N days · simulated <res> · N intervals`. Because "day"/"days" needs
   `ngettext` while the rest of that line is bare literals, `results_view` exposes the parts
   (`period_dates`, `period_days`, `period_run`) and the template joins them; `period` is kept
   whole for any consumer of the old shape, and the template falls back to it.

10. **Bug: the ⓘ popup froze the page when panel ① was collapsed** (reported by the user; fixed).
    The shared `#slot-info-dialog` lived inside panel ①'s `.collapse-content`. daisyUI sets
    `content-visibility: hidden` on a collapsed `.collapse-content`, and a `<dialog>` inside such a
    subtree still enters the **top layer** on `showModal()` — so it blocks every click on the page
    — but the browser never paints it. The user therefore got no popup and a dead page. Confirmed
    in the browser: `d.open === true`, `d.matches(':modal') === true`, and the console logging
    *"Rendering was performed in a subtree hidden by content-visibility"*.

    Pre-existing (panel ①'s own roster ⓘ had it too, after collapsing), but only reachable in
    practice once the glance moved into panel ①, because panel ③'s copy stays visible while panel
    ① is closed. Fixed by moving the dialog to **page level** in `index.html`, beside the already
    page-level `#pending-dialog`; the delegated click handler needed no change.

    Note on the test: Playwright's `is_visible()` returns True for a `content-visibility: hidden`
    subtree, so it does NOT catch this on its own. The smoke test asserts structurally that the
    dialog has no `.collapse-content` ancestor, which was verified to fail against the old markup.

## Files Modified

- `app/templates/_data_glance.html` — macro split into a frame dispatcher + shared `_glance_body`;
  new `frame` argument (`section` / `divider`); old `band` look dropped; the divider frame carries
  no coverage line.
- `app/templates/_panel_data.html` — renders the glance between the data-quality card and the CTA;
  `#slot-info-dialog` moved out to page level (see obstacle 10).
- `app/templates/_panel_results.html` — panel-③ copy switched to `frame='divider'`; the
  `ENERGY SAVINGS` divider now uses a sentence-case msgid + `uppercase`; the range picker's
  coverage line gained the day count.
- `app/templates/index.html` — `_panel_summary.html` include removed; `#slot-info-dialog` mounted
  here at page level, with a note on why it cannot live inside a collapse.
- `app/templates/_panel_summary.html` — **deleted**.
- `app/results_view.py` — adds `period_dates` / `period_days` / `period_run` to the view-model.
- `app/sample_data.py` — the same three keys on the sample panel-③ view-model.
- `app/main.py`, `app/summary_view.py` — comment/docstring wording only ("band" →
  "summary"/"section"); no behaviour change.
- `app/locales/{messages.pot,en,nl}` + `.mo` — `ENERGY SAVINGS` → `Energy savings`.
- `app/static/app.css` — Tailwind rebuild.
- `babel.cfg` — corrected extraction workflow (`-k _N --sort-output`) and why.
- `specs/02-ux-wireframes.md` — §2.1 diagram, §2.2 panel-① layout + closing prose, §2.3a rewritten
  for the new placement, §2.4 diagram + a note on the repeated copy.
- `specs/04-state-machine.md` §3.4, `specs/12-metrics-and-benchmarks.md` — placement + anchors.
- `tests/test_results_route.py` — 5 new tests (panel-① placement, panel-③ divider framing,
  translation regression, the picker's day count, page-level dialog placement).
- `tests/test_smoke.py` — new Playwright test that the ⓘ dialog works with panel ① collapsed;
  wording. `tests/test_data_summary.py` — wording.

## Current Status

Complete. **133 passed, 2 skipped** (the live-HA tests, which need `HA_URL`/`HA_TOKEN_FILE`).

Verified in a browser against a seeded dataset:
- panel ① renders the glance as a peer of the data-quality card;
- panel ③ renders it with a divider heading matching "Energy savings", no frame, no coverage line;
- the picker line reads `<dates> · N days · simulated hourly · N intervals` and the day count
  tracks the selected range (7 / 90 / 365) and pluralises in Dutch ("7 dagen");
- with panel ① collapsed, an ⓘ in panel ③'s glance opens a painted dialog, closes on Escape, and
  the page stays responsive;
- locale switching works in both directions.
