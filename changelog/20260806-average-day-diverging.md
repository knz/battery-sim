# Average-day chart: diverging bars and a net-grid line

Follows `20260806-energy-flows-chart-tab.md`, which built the tab. This rebuilds chart 3 as a
diverging chart and adds a fourth chart under it; charts 1 and 2 are untouched.

## Task specification

The user's prompts, verbatim and in order:

> let's improve the average day graph:
>
> - remove "total solar"
> - add two "negative" stacked bars (extended below the x axis): one for PV energy dumped
>   into the grid, one for battery energy dumped into the grid

Asked what should happen to `chg_pv` and `curtailed`, which the removed `pv_total` line was
carrying and which the two proposed bars do not cover. The user did not take any offered
option and instead specified:

> overlay add a line graph with net grid (imported - exported)

Asked what "curtailed" meant, was answered, then specified:

> ok so the four negative bars:
> - solar export
> - battery export
> - charge battery
> - curtailed
>
> then overlay net grid as a line

Asked which terms the net-grid line should carry, since `chg_grid` was on no bar. The user
declined the question and resolved it structurally instead:

> add battery charge via the grid as another positive stacked bar

Then, after reviewing the drawn chart, a second round:

> - state of charge axis: I'd like to use the same start/end values and lines as the left axis
>   (kW and kWh are commensurable)
> - state of charge: make the line thinner
> - review the labels for the bars holistically, given the labels don't answer the question
>   "where is house energy coming from?" anymore.

Then, after the shared-axis version was built and inspected:

> split "state of charge" to a fourth graph underneath instead of a secondary y-axis

## Final design

Chart 3, diverging:
  Above the axis: `dis_home`, `imp_home`, `pv_to_home`, `chg_grid`.
  Below the axis: `exp_from_pv`, `dis_grid`, `chg_pv`, `curtailed`.
  Lines: `household_load` and a new net-grid line.
Chart 4, new: `soc` alone, its own frame beneath chart 3, same hours on the x-axis.
Removed: the `pv_total` reference line, and chart 3's secondary axis.

## High-level decisions

**The framing changed, and the code comments have to change with it.** The positive stack was
"where household load came from" — three sources under a `household_load` line, with `chg_pv`
and `standby` deliberately excluded because stacking a sink among sources gives a bar total
that is no physical quantity. Adding `chg_grid` above the axis breaks that invariant on
purpose: the axis now separates *entering the house* from *leaving it or being stored*, not
sources from sinks. The existing comments arguing the old invariant were rewritten rather than
left in place; leaving them would have made the file assert something the chart no longer does.

**`household_load` no longer bounds the positive stack.** It previously sat just above the
stack top, the gap being standby. It now sits below it by standby *plus* grid charging. The
note under the chart was rewritten accordingly — the old wording attributed the whole gap to
standby, which would now be wrong whenever the battery arbitrages.

**The net-grid ambiguity dissolved rather than being decided.** With both grid imports drawn
(`imp_home` above, `chg_grid` above) and both exports drawn (`exp_from_pv`, `dis_grid` below),
the meter reading and the algebraic sum of the grid-coloured bars are the same number. The
question of which one the line meant no longer has two answers.

**Sign convention: positive = net import.** Matches the KPI tiles and the monthly charts, where
import is the quantity reported. The line therefore crosses zero where the house flips from
buying to selling.

## Second round: axes and labels

**SoC moved to a fourth chart — via a shared axis that was built, tried and discarded.** Worth
recording both steps, because the intermediate one was implemented and the reason it was dropped
is the useful part.

The user's premise is correct: kWh-per-hour and kWh are commensurable here, because one-hour
buckets make kWh moved during an hour numerically the mean kW across it. So the first fix matched
the two axis ranges explicitly (`overlaying` axes autoscale independently, so Plotly cannot be
asked to do it) and suppressed the right axis's duplicate gridlines. Verified working, including
on a 10 kWh battery.

That verification is what showed the problem. With the ranges locked, a large store dictates the
scale for small flows: bars peaking at 1.2 kWh sat inside a 15-unit span. The commensurability
argument makes the two quantities *comparable in principle* without making them *comparable by
height on one plot area* — a stock and a flow still answer different questions, and a SoC line
crossing a bar top still reads as an event when it is a coincidence.

The user's next instruction resolved it: split SoC into its own frame beneath. That drops the
comparison-by-height entirely and keeps the only comparison that was ever valid — shape against
shape, read down the column. The x-axes are identical by construction (both take `a.hours`), so
an hour sits at the same horizontal position in both; chart 3's x-axis title is suppressed and
chart 4 carries it for the pair. In its own frame SoC also gets `rangemode: 'tozero'` (a stock has
a meaningful zero — an empty battery — and autoscaling would draw a floor at 4 kWh and imply the
battery emptied), and becomes a solid filled area rather than a dotted overlay, since it no longer
needs to distinguish itself from bars sharing its space.

The "make the line thinner" instruction was overtaken by this and is moot: nothing shares the
frame for it to be thin against.

**All eight bar labels rewritten to one grammar.** The user observed that the labels no longer
answer the question they were written for. Correct, and worse than the two collisions already
patched: the set had four grammars at once — sources ("From the grid"), destinations ("Into the
battery"), events ("Solar exported") and a bare state ("Curtailed") — so the legend read as four
kinds of thing rather than eight instances of one. Charts 1 and 2 can name one endpoint and let
the heading supply the other because each decomposes a single total; a diverging chart moving
energy between four places cannot.

Now `A → B` throughout (U+2192), which also makes the axis split legible in the legend itself —
every `→ house` is the above-axis group. `Solar curtailed` is deliberately arrow-less: curtailed
energy has no destination, and inventing one would be wrong. `household_load` and `soc` stay
un-overridden; they are lines naming quantities, not segments in the transfer grammar.

**Sequencing error, recorded because it cost a round of work.** Translations were dispatched
before the labels were settled, so four of five new Dutch strings were obsoleted immediately and
had to be redone. Settle user-facing wording before starting a translation cycle.

## Obstacle: a Tailwind class that silently does nothing

Chart 4 was first given `h-48`, to sit shorter than the three above it. It rendered 450px TALL —
taller than them, not shorter. `app/static/app.css` is a committed pre-built Tailwind bundle (the
app needs no Node at runtime, per `08-architecture.md` §5.1), so it carries only the utilities the
templates already used, and `h-48` appears nowhere else in this project. The class was absent from
the bundle, the div got no height rule, and Plotly fell back to its own 450px default.

Worth recording as a general trap: an unused Tailwind utility fails SILENTLY here. There is no
error, the class is present in the DOM, and the only symptom is the wrong size. Anything outside
the set already in the bundle needs a CSS rebuild and re-commit. Resolved by using `h-64` — the
same height as the other three charts, which reads fine and needs no rebuild.

Found by driving a real browser, not by any assertion. Every Python test was green with the chart
at the wrong height, and the node harness stubs Plotly so it never had a layout engine to ask.

## Known consequence, accepted

`curtailed` and `chg_pv` are now drawn, so nothing the `pv_total` line carried is lost — the
concern that prompted the first clarifying question is resolved by the four-bar design. Total
PV production is no longer readable as a single line, but it is recoverable as the sum of
`pv_to_home + chg_pv + exp_from_pv + curtailed`, all four of which are on the chart.

## Files modified

- `app/results_view.py` — publish `dis_grid` and `net_grid` in `average_day`; docstring updated
  for the diverging layout, the net-grid derivation and SoC's own frame.
- `app/templates/workspace_results.html` — diverging bars, net-grid line, the fourth SoC chart,
  the third label map; `pv_total` trace and the secondary axis removed.
- `app/templates/_panel_results.html` — chart-4 container and heading; all eight average-day
  labels; the axis note replacing the total-solar one; chart 1's standby note scoped to chart 1.
- `app/locales/` — catalogues regenerated, Dutch complete for all ten new strings.
- `tests/test_workspace_results.py` — the two `pv_total` tests rewritten; new tests for the
  net-grid identity and sign, and for the SoC split.

## Translation cycle

Ran the documented `pybabel update` (with `--no-fuzzy-matching`, per `babel.cfg`) for `nl` and
`en`, then `pybabel compile`. Five new msgids landed; `Total solar production` and the old
solar-line note became `#~` obsolete entries rather than being deleted.

### Revision: one "A → B" transfer grammar for all eight bars

The first pass translated per-bar prose labels (`Solar exported`, `Battery exported`,
`Grid charging the battery`). After reviewing the legend as a whole, the user replaced them with
a uniform `A → B` transfer grammar covering all eight bars. A second `pybabel update` obsoleted
the three superseded msgids to `#~`; `Net grid (import − export)` and the note under the chart
were unaffected and kept their existing translations.

The point of the label set is that it reads as one grammar, so the four endpoint nouns are fixed
and reused identically across every entry rather than varied for local fluency. Each is a term
the catalogue already carries: `Battery`→Batterij, `Grid`→Net, `Solar`→Zon,
`Household`→Huishouden, and `Curtailed`→Afgeregeld.

| msgid | Dutch |
| --- | --- |
| Battery → house | Batterij → huishouden |
| Grid → house | Net → huishouden |
| Solar → house | Zon → huishouden |
| Grid → battery | Net → batterij |
| Solar → grid | Zon → net |
| Battery → grid | Batterij → net |
| Solar → battery | Zon → batterij |
| Solar curtailed | Zon afgeregeld |
| Net grid (import − export) | Netto netgebruik (afname − invoeding) |
| Bars above the line … | Balken boven de lijn tonen energie die het huis binnenkomt; eronder energie die het huis verlaat of de batterij laadt. |

### Addition: heading for the split-out state-of-charge chart

State of charge moved out of the average-day chart into a fourth chart stacked underneath,
sharing its x-axis. The new `<h4>` heading is the only msgid this round added; nothing else
changed.

| msgid | Dutch |
| --- | --- |
| And how full is the battery? | En hoe vol is de batterij? |

It joins three question-form headings already in the column, all of which use a direct question
with an inverted verb, and it keeps that pattern. The leading "And" links the chart to the one
above it; Dutch `En` opens a sentence the same way, so the linking sense carries over without
needing to be dropped. Deliberately plainer than the catalogue's technical `State of charge` →
*Laadtoestand*, matching the plain register of the English.

### Notes on the label set

`Solar curtailed` deliberately carries no arrow — curtailed energy has no destination — and the
verification asserts the arrow is absent there and present exactly once in the other seven.

Both special characters are carried into the Dutch and verified by codepoint after compile: the
U+2212 minus in the net-grid label, and U+2192 in the seven arrow labels (the only non-ASCII
codepoint appearing in them, so nothing was silently substituted with a hyphen or lookalike).

`en` follows the file's existing split: short single-line msgids repeat the msgid as msgstr;
the long wrapped note is left empty to fall through. This matches how commit 193f121 (the
predecessor that built this tab) handled its own strings.

Verified by loading the compiled `nl` catalogue through Python's `gettext` and calling
`gettext()` on each of the five — not by grepping the `.po`, since a `msgstr ""` followed by
further quoted lines is the multi-line continuation form, not an empty translation.
`tests/test_no_english_leakage.py` passes (125 tests).

## Current status

Complete.

Verified: 349 tests across the four affected suites, 42 browser smoke tests, and the four charts
inspected in a real browser (traces, axis ranges, frame sizes, no page errors, no horizontal
overflow at 1280px). The net-grid sign test was confirmed to discriminate by inverting the
formula; the SoC-split test by deleting its div.

**One Dutch term corrected by the user before commit.** *Netto net* was flagged by the translator
as awkward through the repetition of *net*; the user replaced it with *Netto netgebruik (afname −
invoeding)*. A msgstr-only change — the English msgid is untouched, so no re-extract was needed,
only a recompile. Verified through `gettext` that it resolves and that the U+2212 minus survived.

Not verified: real Home Assistant data, and whether the remaining Dutch reads naturally to a
native speaker. One judgement call is still open — *Net* as the bare grid noun on both sides of
the arrows, rather than the directional *Netafname*/*Netinvoeding*, on the grounds that the arrow
already carries direction and varying the noun would defeat the uniform grammar. *huishouden* over
the shorter *huis* was the other, and stands.
