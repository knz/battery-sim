# Results screen: the footer becomes a fixed bottom band

## Task Specification

On the results screen (`GET /w/{id}/results`), the footer — privacy statement, attribution,
licence, NO WARRANTY — currently sits inside the scrolling results column, so it is out of view
whenever the reader is anywhere but the very bottom of the figures. Make it always visible.

## The user's prompts, verbatim

Recorded per `docs/specs/AGENTS.md`, since this task modifies `docs/specs/20-workspaces-ux.md`.

1. > the footer with disclaimer licensing etc: on the results page, it belongs to the result side
   > so is scrolled out of view when the result screen is opened. can we make it a fixed footer
   > that's always visible

2. Answers to the two clarifying questions: **"Same two lines, pinned"** (no condensed variant of
   the footer for this screen) and **"Results column only"** (the band spans the results column,
   not the full window width).

3. > go ahead

   — approving the implementation plan.

## Current state (before changes)

`changelog/20260809-results-side-panel-layout.md` made this screen two columns above `lg`: a
fixed `<aside>` of controls and a scrolling results column. It put the footer **inside** that
scrolling column, and recorded why:

> The body is `lg:overflow-hidden`, so a footer left as a sibling of `<main>` would sit below the
> one-viewport region and be unreachable at any scroll position.

That reasoning is correct as far as it goes — the footer had to move somewhere inside the
one-viewport region — but "inside the scrolling column" was one of two options and the weaker
one. It trades unreachable-at-every-scroll-position for unreachable-at-every-scroll-position-
but-the-last, behind ~3500px of figures.

## High-Level Decisions

**The results column stops being the scroller and becomes a flex column of two children.** The
scroll moves down one level to a new inner `<div>`; the footer is the second child, `flex-none`.
The alternative — `position: sticky; bottom: 0` on the footer inside the existing scroller —
would have kept the DOM flatter, but a sticky element still participates in the scrolled content,
so the last figure would slide *under* it and the footer would need an opaque background plus a
matching bottom padding on the content to compensate. The split is the same idea stated
structurally, and the scroll container's own bottom edge is then the correct one.

**`lg:min-h-0` on the new scrolling child.** Same reason it is already on `<main>` and both
columns, one nesting level further down: a flex child's default `min-height: auto` refuses to
shrink below its content, so without it the child grows to full content height, `overflow-y-auto`
has nothing to clip, and the scrollbar reverts to the nearest ancestor that can take it.

**Full-width band, `max-w-4xl` content.** The footer wrapper spans the results column so its
border rules across the whole column; the footer's own `mx-auto max-w-4xl` (unchanged, from
`_footer.html`) keeps the text aligned with the figures above it rather than centred in a wider
band.

**`_footer.html` is not touched.** It is included by all four screens. Every change here is in
the results screen's own wrapper markup, so the other three keep rendering it exactly as before.

**The footer's own bottom padding is trimmed on this screen only.** `_footer.html` carries
`pb-8 pt-4` — padding sized for the end of a scrolling page, where trailing space below the last
line is what keeps the text off the window edge. In a permanent band it reads as lopsided, and
measurably so: the band came out 85px tall with visibly more space below the text than above.
`lg:[&>footer]:pb-4` on the wrapper matches the two, taking the band to 69px and giving 16px back
to the figures at every viewport at or above `lg`. Done as an arbitrary variant on the wrapper
rather than by editing the partial, because the other three screens still end in a scrolling page
and want the original spacing.

## Obstacles and Solutions

- The first CSS comparison script parsed selectors by splitting on `,` at brace depth 0, which is
  wrong for a minified Tailwind build — utilities sit inside `@media`/`@layer` wrappers, so nearly
  every real selector is at depth ≥1 and both sets came out empty-and-equal ("0 added, 0 lost").
  Caught by checking whether a class I had just introduced was really present in the committed
  file; it was not. Replaced with a script that extracts escaped class tokens and ignores nesting.
- `tests/screenshot.py` targets `/` with `full_page=True`, neither of which suits a nested-scroll
  layout on a specific screen → throwaway probes in the scratchpad rather than changes to the
  committed helper.
- A fresh data dir has no `local` workspace → the probes call `demo.materialize()` against a temp
  `BATTERY_SIM_DATA_DIR` and use the id it returns (it generates one rather than taking `demo`).

## Verification

Measured in headless Chromium against the demo workspace.

**Layout, at five viewports.** In each case the footer's viewport-relative top is identical
before and after scrolling the figures to the bottom, which is the property the change is about:

| viewport | page scrolls | figures scroll | footer top before → after | band bottom / window |
|---|---|---|---|---|
| 1440×900 | no | yes (3417px in 767px) | 832 → 832 | 900 / 900 |
| 1440×700 | no | yes (3417px in 567px) | 632 → 632 | 700 / 700 |
| 1280×800 | no | yes (3461px in 667px) | 732 → 732 | 800 / 800 |
| 1024×768 | no | yes (3723px in 619px) | 684 → 684 | 768 / 768 |
| 800×900 | **yes** | n/a (stacked) | 4072 → 4072 | 4156 / 900 |

The last row is the sub-`lg` fallback and is unchanged: the page scrolls, `body` overflow is
`visible`, and the footer sits in normal flow far below the fold. Band height 69px above `lg`
(85px at 1024, where the attribution line wraps to two); 84px in the stacked layout, confirming
the padding variant is correctly gated on `lg`.

**Interaction, across all three swap paths plus the footer's own control.** `#panel-results` now
lives one nesting level deeper than before, so each path was checked for where the swapped-in
markup lands: period preset (`POST /results`, the split swap spanning two containers), chart-tab
switch, and capacity edit (`POST /params` plus its triggered recompute). After each — all three
panel ids present, results still inside the scrolling half, params and interval still in the
aside, footer still at 832/900, exactly **one** `<footer>` in the DOM (the band is never
replaced), chart-tab selection preserved, visible plots still 812px, no console errors. The NO
WARRANTY button inside the pinned band still opens its dialog.

**CSS.** `app.css` is a committed build artifact. Class-set comparison against `HEAD`: 3 added
(`lg:bg-base-100`, `lg:border-t`, `lg:[&>footer]:pb-4`) plus `sticky` from daisyUI's own emission
set, and **0 lost** — purely additive. The minified file is one line, so `git diff` reports
"1 insertion, 1 deletion" and shows nothing useful; the comparison script is in the scratchpad
rather than committed.

**Not re-run: the pytest suite.** `uv run pytest tests/` was started after the change and
interrupted before completing, so this change has not been checked against it — `tests/test_footer.py`
and `tests/test_results_view.py` are the two that touch this markup. No test was modified. Worth
running before this is relied on.

## Files Modified

- `app/templates/workspace_results.html` — the results column becomes a flex column of two
  children: a new scrolling `<div>` wrapping `_panel_results.html`, and a pinned wrapper holding
  `_footer.html`. Header comment block updated: the wireframe redrawn with the footer below the
  scroll region, and the paragraph explaining why the footer sat inside the scroller replaced with
  why it no longer does.
- `app/static/app.css` — regenerated (`npm run build:css`) for the three new utility classes.
- `docs/specs/20-workspaces-ux.md` — §2′.6's wireframe redrawn; new paragraph under "The controls
  are a fixed column" stating the footer is a pinned band and why. (§2′.8's "footer" is the
  wizard's button bar, a different thing, and is untouched.)

## Current Status

Complete, with the pytest suite not re-run (see Verification). No follow-ups outstanding.
