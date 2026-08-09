# Results screen: vertical stack → fixed side panel + scrolling results

## Task Specification

Restructure the results screen (`GET /w/{id}/results`) from its current vertical stack into a
two-region layout:

1. **A side panel holding the parameters, which does not scroll.**
2. **A results region that scrolls independently.**

## The user's prompts, verbatim

Recorded in full per `docs/specs/AGENTS.md` ("when updating files in the specs directory, also
record the human user's original prompts in the changelog"), since this task modified
`docs/specs/20-workspaces-ux.md`, `docs/specs/04-state-machine.md` and
`docs/specs/02-ux-wireframes.md`.

1. > create a new worktree, we're going to work on ui layout

2. > i'd like to restructure the results screen from a vertical stack to 1) a side panel with
   > the parameters, which doesn't scroll 2) a result part that can scroll

3. Answers to the three clarifying questions (selected options): **"Battery + Period both"** in
   the side panel; **"Panel scrolls internally"** when its content is taller than the viewport;
   **"Fall back to today's stack"** on narrow viewports.

4. > yes

   — approving the implementation plan.

5. > let the labels for charge/discharge strategy wrap around

## Current state (before changes)

`app/templates/workspace_results.html` renders, inside a single `<main class="mx-auto flex
max-w-5xl flex-col gap-4 p-4 lg:p-8">`:

- a two-column grid (`lg:grid-cols-2`) holding `_panel_params.html` (the Battery box,
  `#panel-params`) beside `_panel_interval.html` (the Period card, `#panel-interval`);
- `_panel_results.html` (`#panel-results`) full width below them.

The whole page scrolls as one document. The site footer (`_footer.html`) follows `<main>`.

Three swappable fragment roots exist and are contracts with the JS in `workspace_results.html`:

- `#panel-params` — replaced by `POST /w/{id}/params` (outerHTML swap)
- `#panel-interval` + `#panel-results` — replaced together by `POST /w/{id}/results`, which
  returns both joined by a `<!--panel-split-->` marker

All behaviour is bound via listeners delegated from `document`, so a layout change that keeps
the three ids and their nesting-independence does not require touching the handlers.

## Open question raised before implementation

The spec says the current mechanism is load-bearing. `docs/specs/20-workspaces-ux.md` §2′.6
("What is unchanged") states:

> §3.4 calls "the parameters and the results must be visible at the same time" the single most
> important interaction detail in the app. Here that is met structurally: **the battery box and
> the results are on one screen and scroll together**, so a capacity change and its effect are
> visible at once.

A fixed side panel satisfies the *requirement* (parameters always visible) more strongly than
scrolling-together does — under the current layout the parameters leave the viewport as soon as
the reader scrolls into the figures. But it contradicts the *mechanism* the spec text names.
Assessment: this is a spec-text update, not a spec violation. Recorded here so the change to
§2′.6 and §3.4 is deliberate rather than incidental.

## Requirements Changes

Three questions were put to the user before implementation; all three were answered and the
plan was approved on that basis:

1. **What goes in the side panel** — *both* control cards (battery box and period card), not
   the battery box alone. The split is inputs on the left, answers on the right.
2. **Panel taller than the viewport** — it scrolls internally (`overflow-y: auto`), rather than
   the sticky behaviour releasing and the page scrolling. A control the user cannot reach is
   worse than a second scrollbar.
3. **Narrow viewports** — fall back to today's vertical stack below `lg`, rather than building
   a second condensed rendering of the battery box as a sticky top bar.

## High-Level Decisions

**The layout is a flex column on `<body>`, not `position: sticky`.** `lg:h-screen` +
`lg:overflow-hidden` pin the document to one viewport and remove the page's own scrollbar,
which is the precondition for the two columns to own theirs. Sticky was not used because it
keeps the page scrollbar and only pins the panel within its container's height — the panel
would still scroll away once its container ended.

**`lg:min-h-0` on `<main>` and on both columns is load-bearing.** A flex child's default
`min-height: auto` refuses to shrink below its content, so without it both columns grow to full
content height, `overflow-y-auto` never has anything to clip, and the scrollbar silently
reverts to the page. This is the single easiest thing to break here and is commented as such in
the template.

**The footer moved inside the results column.** The body is `lg:overflow-hidden`, so a footer
left as a sibling of `<main>` would sit below the one-viewport region and be unreachable at any
scroll position.

**The results column keeps an inner `max-w-4xl`.** The column takes the full remaining width,
but prose and caveats are not run out to 2000px on a wide monitor. This is what the old
`max-w-5xl` on `<main>` was doing.

**Column width is `lg:w-[26rem]`, `xl:w-[30rem]`.** Started at `lg:w-96` (384px); at that width
the advanced pane's tab strip wrapped to two lines and "Charge & discharge" took its own row.
The wider `xl` step fits the strip on one line and keeps `[ Calculate → ]` above the fold on a
700px-tall viewport.

**No `items-start` on the aside — this was a bug found and fixed during implementation.** On a
flex column that cross-axis rule shrink-wraps each card to its own content; the battery box's
content is wider than the column, so instead of fitting it *overflowed* to 441px inside a 384px
aside and its `[ Calculate → ]` button was clipped against the border. Measured, not eyeballed.
Stretched (the default), the cards take the column's width and their contents wrap.

**No JavaScript changed.** All behaviour is bound via listeners delegated from `document`, and
the three fragment root ids kept their names, so the swaps work unmodified even though
`#panel-interval` and `#panel-results` now live in *different* containers.

## Obstacles and Solutions

- `#panel-params` overflowing the aside → removed `items-start` (see above).
- The repo's `tests/screenshot.py` targets `/` and uses `full_page=True`, neither of which suits
  a nested-scroll layout on a specific screen → wrote throwaway probes in the scratchpad instead
  of modifying the committed helper.
- A fresh data dir has no `local` workspace, so `/w/local/results` 404s → the probes call
  `demo.materialize()` against a temp `BATTERY_SIM_DATA_DIR` to get a workspace with real data.

## Verification

Measured in headless Chromium against the demo workspace, not eyeballed:

- **1440×900** — page does not scroll (`body` overflow hidden); aside 480px fixed, does not
  scroll; results column scrolls (3540px content in 836px); footer inside the results column;
  visible Plotly charts 812px wide.
- **800×900** — fallback confirmed: page scrolls, `body` overflow visible, aside full-width with
  `overflow-y: visible`, columns stacked. Today's layout.
- **1440×700 with the advanced pane open** — internal scroll engages as designed: 1071px of
  content in a 636px column, `scrolls: true`, page still does not scroll, nothing clipped.
- **Interaction test across all three swap paths** — period preset (`POST /results`, the split
  swap that now spans two containers), chart-tab switch, and capacity edit (`POST /params` plus
  its triggered recompute). After each: all three panel ids present and in the correct column,
  page still not scrolling, results column still scrolling, visible plots still 812px, chart-tab
  selection preserved. No console errors.
- **`uv run pytest tests/`** — 1868 passed, 23 skipped (the live-HA suite), no failures.

## Follow-up: the policy labels wrap (prompt 5)

The narrower control column exposed a clipping bug on the advanced pane's *Charge & discharge*
tab. daisyUI's `.label` sets `white-space: nowrap`, so the policy names ran past the card's
right edge and were cut off mid-word — "D1 Serve house load when consumption exc|" at 1024px.
Measured before the fix: D1's text span was 385px inside a 360px card.

**Three classes are needed together, and removing any one brings the clipping back in some
form:**

- `whitespace-normal` on the label — releases daisyUI's `nowrap`;
- `items-start` on the label plus `mt-0.5` on the control — puts the radio/checkbox on the
  *first* line instead of centring it against a now two-line block;
- `min-w-0` on the text span — a flex child otherwise refuses to shrink below its content
  width, so the wrap never happens.

`shrink-0` was also added to the controls and to the "PV only" badge and ⓘ button, so the fixed
elements are not squeezed as the text reflows.

Applied to all four label rows on that tab (three charge policies, three discharge policies,
the export checkbox, the economic guard) and — for consistency, since it is the identical
pattern and string length one tab over — to the Battery tab's "Continue with a 3-phase
approximation" checkbox, which sits inside a narrower alert box still.

Verified: every row reports `overflows: false` at both 1440 and 1024, with the long ones now
two lines (span height 42px, was 21px) and the short ones unchanged at one. Clicking a label's
*wrapped* text still selects its radio and toggles the checkbox, and the choice survives the
`POST /params` round-trip — worth checking explicitly, since changing a label's box model can
break the implicit hit target. Full suite re-run after the change.

## Files Modified

- `app/templates/workspace_results.html` — `<body>` becomes a flex column pinned to the
  viewport above `lg`; `<main>` becomes the two-column region; new `<aside>` wraps the two
  control includes; new scrolling `<div>` wraps the results include and the footer. Header
  comment block rewritten: the old ASCII wireframe and the "scroll together" rationale replaced
  with the two-column diagram and the reasoning below.
- `app/templates/_panel_params.html` — the five label rows that clipped now wrap (see the
  follow-up section above). No change to any field name, value or validation.
- `app/static/app.css` — regenerated (`npm run build:css`) for the new utility classes. This is
  a committed build artifact (`package.json`: the app needs no Node at runtime), so it was
  checked rather than assumed: deleting the output and rebuilding from scratch reproduces the
  committed bytes exactly (sha256 `c7c7913…`), and a selector-set comparison against `HEAD`
  shows 21 selectors added and **0 lost** — the change is purely additive. The minified file is
  one line, so `git diff` reports "1 insertion, 1 deletion" and shows nothing useful; the
  comparison script is in the scratchpad rather than committed.
- `docs/specs/20-workspaces-ux.md` — §2′.6's wireframe redrawn; new subsection "The controls are
  a fixed column, not the top of a long page"; "What is unchanged" no longer claims the two
  scroll together; §2′.9's cross-reference updated; third decisions round (17–20) added.
- `docs/specs/04-state-machine.md` — §3.4's statement of the mechanism updated, with a paragraph
  on why the requirement is unchanged and the mechanism replaced.
- `docs/specs/02-ux-wireframes.md` — the screen-inventory table row for Results.

## Current Status

Complete and verified. No follow-ups outstanding.

### One trade-off, measured rather than assumed

The `lg` breakpoint (1024px) is where the two-column layout engages, and at exactly that width
the results column is 608px. The KPI tiles then wrap their labels ("EQUIVALENT FULL CYCLES"
wraps and clips slightly at its tile edge), where the old full-width layout fitted them on one
line. Checked against the pre-change layout at the same width to confirm this is a genuine
consequence of the narrower column and not a pre-existing defect: it is new.

Nothing is unreachable and no figure is lost — the tiles reflow rather than truncate — so this
is a density cost, not a correctness one, and it is confined to roughly 1024–1200px. Three ways
to address it if it proves annoying in practice, none of them taken here because the choice is
a judgement about real use rather than something the probes can settle:

- raise the two-column threshold to `xl` (1280px), so this range keeps the stacked layout;
- let the KPI tile row drop to two columns below some width;
- narrow the control column further in the `lg`–`xl` range.

Left as-is and flagged rather than pre-emptively fixed.
