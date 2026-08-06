# Two money heatmaps on the SoC + price tab, renamed "Battery rhythm"

Scope grew during the task: it began as ONE chart (the user's "second graph on
the new tab") and became two, the third requested after the second landed. Both
are recorded here rather than in separate files, because they are one continuous
piece of work on one tab and the second only makes sense against the first.

## Task specification

Follows on from `20260806-soc-price-chart-tab.md`, which built the tab's first
chart (the SoC heatmap) and left the second as a heading-only placeholder,
recorded as followup C2a.

The user's request, verbatim:

> let's move to the second graph on the new tab.
>
> it's not going to be a "price" graph exactly, instead "how much money flow in
> and out because of the battery" (you can propose a better title)
> also a heatmap
>
> the value plotted is "house load served from battery" + "battery discharge
> into grid" - "battery charge from grid"
> more green when higher than zero, more red when lower than zero
>
> I'll welcome feedback on the design before we implement anything

Subsequent user prompts, verbatim, in order (recorded per
`docs/specs/AGENTS.md`, since this task edits the specs directory):

> i meant the value computed by the formula I just gave, multiplied by spot
> price

Then, after design feedback argued against bare spot:

> - ok with your formula
> - only show this plot when simulate_cost is enabled
> - I don't understand your other questions?

Then, after the two open questions were restated in plain terms:

> q1: let's do symmetric
> q2: "Battery rhythm" for the title of the tab, "Gross battery earnings" for
> the chart title

Then, on approving the plan:

> let's add a footnote, yes.
> use sub-agents for impl/review so the main agent stays focused on
> orchestration.
> avoid running the full test suite (there are expensive benchmarks in there),
> use focused tests.

Then, after the footnote's "above"/"below" fix, a THIRD chart was requested:

> let's add a third heatmap, also positive/negative money like the second
>
> the formula should be net grid cost (import * p_import - export * p_export)
> with battery+PV, minus net grid cost with only PV
>
> as before, welcoming feedback before impl

Explicit scope notes:

- The chart is a heatmap, same family as the first chart on the tab.
- The user invites design feedback BEFORE implementation. No code is to be
  written until a design is agreed and approved.
- The user offers the title as open ("you can propose a better title").

## Status

Both charts complete, tested and committed. See "Current status" at the foot of
this file for what was deliberately left open.

Each chart was built by two subagents in parallel on disjoint file sets — the
server half (`app/results_view.py`, `tests/test_results_view.py`) and the client
half (templates, JS, catalogs, `tests/test_smoke.py`) — against a payload
contract fixed in advance by the approved plan, with the main agent
orchestrating and verifying. That was the user's instruction, and it held up:
no contract mismatch was reported by either pair.

## Requirements changes during the design discussion

The user's opening formula was `(dis_home + dis_grid - chg_grid)`, later
qualified as "multiplied by spot price". Design feedback argued against bare
spot; the user accepted the revised pricing. Four decisions, all from the user:

1. **Price each term at what it is really worth**, not at bare spot:
   `dis_home * p_import + dis_grid * p_export_net - chg_grid * p_import`.
2. **Show the chart only when `simulate_cost` is enabled.**
3. **Symmetric colour scale** — one range spanning both directions, so a green
   and a red cell of equal intensity mean equal euros.
4. **Titles**: the TAB becomes "Battery rhythm"; the CHART is titled
   "Gross battery earnings".
5. **A footnote pointing at the KPI tile**, so a reader who takes "earnings"
   for the net saving is told where the net figure lives. Added on approval of
   the plan, in response to the risk the plan itself raised.

## Third chart: "Saved against no battery"

Requested after the second chart landed. The user's formula:

    net grid cost (battery+PV) - net grid cost (PV only)

with `net grid cost = imp * p_import - exp * p_export_net`.

This is `bill(C) - bill(A)`, and it already exists in the codebase: the closure
at `app/results_view.py:2464-2468` computes exactly that bill and differences
the two runs to feed `_monthly_saved_eur`. Run A is "PV only, no battery" by
construction (`app/domain/simulate.py:665-671` — load minus PV, with the export
cap applied). So the chart is largely a re-plot of an array already built.

User decisions, after feedback:

1. **Flip the sign** — plot `A - C`, not the literal `C - A`. The literal
   direction is negative when the battery helps, since a cost went down, which
   would render "battery saved money" as red. Green-when-good matches chart 2.
2. **Heading: "Saved against no battery."**
3. **Independent clip** — chart 3 computes its own 99th-percentile range rather
   than sharing chart 2's. The two charts are different quantities, so a shared
   range would imply a cell-for-cell comparability that does not hold.

### Why charts 2 and 3 differ, and why that must be said on screen

They will visibly disagree, and a reader seeing two green/red grids stacked will
assume they should match:

- **Chart 2** attributes value to battery FLOWS. Its cells sum to nothing on the
  panel — a self-consumed PV kWh that never touched the battery is worth the
  same under both runs and appears in neither.
- **Chart 3** is the COUNTERFACTUAL: what the household's whole grid bill did.
  It includes effects with no battery flow at all, such as PV the battery stored
  that would otherwise have been curtailed.

Chart 3 reconciles with the MONEY SAVED tile; chart 2 does not. The two captions
carry that distinction rather than leaving the reader to reconcile them.

Known caveat, inherited rather than new: the feed-in floor top-up is a
period-level scalar with no per-interval allocation
(`app/results_view.py:2269-2275`), so in the rare window where the floor binds,
the cells sum to slightly LESS than the headline saving. The existing monthly
euro chart already carries this caveat; chart 3 reuses its wording.

### Obstacles and findings from the chart-3 build

**A pre-existing test was weaker than it read.** `_cost_dataset`, the fixture behind
`test_monthly_saved_eur_buckets_like_the_kwh_series_and_sums_to_the_saving`,
exports the SAME amount under runs A and C. The export term therefore cancels out
of the difference, and a sign flip on it is invisible there — that test would have
passed a bill with `+ exp` instead of `− exp`. The new sum-to-headline test
asserts over a second fixture whose two runs export differently, which does catch
it. The existing test was left unmodified (its own assertions still hold) but it
is not the guard it appears to be.

**Uncommitted work was destroyed and recovered.** The client agent ran
`git checkout tests/test_smoke.py` while reverting a probe, discarding the whole
file's uncommitted changes — including the chart-2 browser test, which had never
been committed. Recovered in full from an earlier stash commit. Verified after the
fact: all three heatmap tests present and all four chart browser tests pass, which
a partial recovery would not survive. The lesson is the ordinary one — the work
was only at risk because it was uncommitted for a long stretch across two agents.

**"Cost simulation on" is not sufficient for the euro charts to appear.** The
shared `_seed_reconstructable_dataset` / `_flows_dataset` fixtures write energy
meters only and carry no `price_spot` slot, so every price is NaN, every cell is
NaN, and the builders correctly return None. Both euro charts' tests seed their
own priced datasets. This is correct behaviour on both sides, but it means a
workspace with cost simulation enabled and no spot-price series still shows only
the SoC grid.

**`<f4` rather than `np.float32`.** The byte order is stated explicitly in the
dtype. The SoC grid's uint8 payload has no byte order to get wrong; a float32 one
does, and the browser's `Float32Array` reads the platform's order. A big-endian
server would otherwise ship a payload that decodes to nonsense.

**One coverage gap left open, deliberately.** The explicit `drawSavedHeatmap()`
call in `recompute()` is not isolated by any test: after a tab click,
`restoreChartTab()` redraws the tab anyway, so deleting the explicit call still
passes. It matters only when no tab was ever selected. Chart 2 has the same gap.
Documented in the test docstring rather than left implied; closing it needs a test
that recomputes with no prior tab click.

## Approved plan

Per interval, in euros, from run C:

    dis_home * p_import + dis_grid * p_export_net - chg_grid * p_import

- Server: `_earnings_heatmap()` in `app/results_view.py`, sharing the local-day
  / time-of-day axis construction with `_soc_heatmap` by extracting it rather
  than copying, so the two grids cannot drift apart.
- Encoding: float32 base64 inline, NOT the byte quantisation the SoC heatmap
  uses — euros are signed and unbounded, so a 0..254 ramp does not apply.
- Colour: symmetric diverging scale, red/transparent/green, `zmid` at zero,
  range clipped to the 99th percentile of absolute value. Cells beyond it
  saturate rather than widening the range for everything else.
- NaN: gap intervals are NaN in the flow arrays and price arrays are NaN where
  spot was missing; `NaN * price` stays NaN, so both reasons for "cannot say"
  blank out with no special-casing. Verified before planning.
- Gated on `cfg.simulate_cost`; returns None when off so the chart is absent
  rather than empty.
- The internal `socprice-*` element ids are NOT renamed: renaming reaches into
  the tab-restore machinery for no user-visible gain. The template comment
  records the mismatch.

## Working constraints for this task

- Implementation and review are delegated to subagents; the main agent
  orchestrates. (User instruction.)
- **Focused tests only — never the full suite**, which contains expensive
  benchmarks. `tests/test_benchmark.py` must not be invoked. (Standing user
  instruction, restated for this task.)

## Findings

The three terms in the user's formula map one-to-one onto existing per-interval
fields of `Flows` (`app/domain/simulate.py:167-179`) — `dis_home`, `dis_grid`
and `chg_grid`. No new simulation output is required to compute the quantity.

The request said "money", but those three fields are kWh, so the pricing had to
be settled first. `app/domain/pricing.py:159-198` prices the two directions very
differently: import carries energy tax and VAT, feed-in carries neither and is
further reduced by terugleverkosten. On the shipped defaults a kWh serving the
house is worth substantially more than the same kWh exported, and
`pricing.py:194-198` notes the export net goes NEGATIVE below about 8 ct/kWh
bare — so bare-spot pricing would have coloured loss-making exports green. That
is what the design feedback argued, and what the user accepted.

### Three prices, not two — surfaced during implementation

`price_curves` does not build `p_import` from spot directly. It applies
`bare_supply_price` (spot + supplier markup) FIRST, then `import_price` on top
of that. So there are three distinct per-kWh values in play — raw spot, bare,
and all-in import — not two. A test asserting against `import_price(cfg, spot)`
is wrong by roughly 7% and the implementation agent's first attempt failed on
exactly that. The implementation was correct throughout (it reads
`curves.p_import`); only the test's expected value was wrong. Recorded because
"catches bare spot" is a weaker claim than it sounds: the discrimination has to
hold against the middle value too.

### The `simulate_cost` gate is redundant through the public path

`_earnings_heatmap` is called from inside an existing `if cfg.simulate_cost:`
block, so removing the in-function guard is invisible when exercised through
`results_from`. The toggle test therefore calls `_earnings_heatmap` DIRECTLY as
well; without that, the sabotage of removing the guard passed. Kept anyway —
the function is not private to that call site and should not depend on its
caller's gate for correctness.

## Design decisions

1. **Shared axes rather than a second implementation.** The local-day /
   time-of-day construction was extracted from `_soc_heatmap` into
   `_heatmap_axes` and is now called by both. The alternative — a second copy —
   would let the two grids on one tab drift apart under later edits, and a
   sabotage introducing a drifting row axis was caught by four tests.
2. **float32, not the SoC chart's byte quantisation.** The SoC ramp is bounded
   0..1, which is what makes a 254-level byte honest there. Euros are signed and
   unbounded, so the same trick does not apply.
3. **NaN carries "cannot say" with no special-casing.** Gap intervals are NaN in
   the flow arrays and price arrays are NaN where spot was missing, so
   `NaN * price` propagates on its own. Verified before the plan was written,
   and a sabotage substituting `np.nan_to_num` was caught.
4. **Values are NOT clipped in the payload.** The 99th-percentile `clip` is sent
   as a scalar for the client to use as its colour range; the underlying values
   travel intact, so hover reports what actually happened rather than a
   saturated figure. A sabotage that clipped before encoding was caught.

## Client-side implementation

### Files modified

- `app/templates/_panel_results.html` — tab label renamed to "Battery rhythm";
  the heading-only placeholder replaced with a real chart block (heading, plot
  div `#socprice-earnings`, caption, footnote), gated on
  `results.earnings_heatmap`; a new `#socprice-earnings-data` JSON node beside
  the existing `#socprice-data`; the two stale comments that described the tab
  as having an unbuilt price half rewritten.
- `app/templates/workspace_results.html` — `drawEarningsHeatmap()` added beside
  `drawSocHeatmap()`; the `socprice` entry in `CHART_TABS` now runs both draws;
  the recompute redraw path calls the new function too.
- `app/locales/{nl,en}/LC_MESSAGES/messages.po` + `.pot` + compiled `.mo` —
  five new msgids, three msgids obsoleted (the old tab label and the two
  placeholder strings).
- `tests/test_smoke.py` — new browser test
  `test_the_earnings_heatmap_draws_beside_the_soc_heatmap`; the existing SoC
  test's placeholder assertion inverted (the placeholder is gone) and two stale
  comments corrected.

### Decisions taken on the client side

1. **A separate `#socprice-earnings-data` node, not extra keys on
   `#socprice-data`.** The two payloads are gated differently — the SoC grid
   exists whenever there is a simulation, the earnings grid only with cost
   simulation on. One node carrying both would have to encode "half of me is
   missing" and both draws would have to check.
2. **The tab's draw entry is unconditional and the gate lives inside
   `drawEarningsHeatmap`,** which returns early when its node is absent. So the
   tab keeps working with cost simulation off, carrying the SoC chart alone.
3. **Two coincident colour stops at the midpoint, not one.** Plotly interpolates
   RGB and alpha independently, so a single transparent mid stop would carry
   each half's hue part of the way towards the other before the alpha reached
   zero — tinting small losses green-ish and small gains red-ish.
4. **Transparent at zero rather than white.** The panel renders on both light
   and dark themes and a white midpoint would read as a bright band on the dark
   one.
5. **The new smoke test seeds its own dataset, including `price_spot`.** The
   shared `_seed_reconstructable_dataset` writes energy meters only; with no
   spot series every price is NaN, every earnings cell is NaN, and the server
   correctly returns no payload — so the test would have asserted on a chart
   that is legitimately absent. The seeded prices carry a real day/night spread,
   which is also what puts cells on both sides of zero.
6. **The footnote names the KPI tile by its rendered label** ("MONEY SAVED" /
   "BESPAARD GELD"), so the pointer is findable by eye in both languages rather
   than being an abstract reference to "the tile above".

### Obstacles

- The first run of the new test failed on a missing payload. Cause: no spot
  price in the shared seed helper, not a bug in either half. Solved by seeding
  a `price_spot` frame in the test (decision 5 above).

### Verification

- Focused runs: `pytest tests/test_smoke.py` (46 passed),
  `pytest tests/test_i18n.py tests/test_no_english_leakage.py` (205 passed).
  `tests/test_benchmark.py` was never invoked.
- Two sabotages, both caught by the new test: dropping `drawEarningsHeatmap()`
  from the tab's draw entry, and forcing every decoded cell to `null`.

### Open item

`test_no_english_leakage` renders default pages, and the earnings chart's
strings only appear on a page whose workspace has both cost simulation on and a
spot price stored. So the three new Dutch sentences are translated and compile,
but no test currently renders them — the same J3-shaped gap that file's
docstring already describes.

## Verification of the whole task (main agent, independent of the subagents)

Re-run from the orchestrating session rather than taken on the subagents'
reports:

- `pytest tests/test_results_view.py tests/test_i18n.py
  tests/test_no_english_leakage.py tests/test_workspace_results.py` — 393 passed
- `pytest tests/test_smoke.py -k "heatmap or chart_tab"` — 4 passed
- `tests/test_benchmark.py` never invoked, per the standing instruction.

Sabotage totals across both charts: 9 for chart 2, 7 for chart 3, 2 + 2 in the
browser. All caught. Two of them only after the test was strengthened — the
`simulate_cost` guard needed a direct call because the public path already gates
it, and the client's clip-independence check had to read the PLOTTED `zmax`
rather than the DOM JSON node, which passed the sabotage.

The sum-to-headline property was verified directly here, not just via the
subagent's report: cells sum to `saved_eur` and to the monthly bars, on two
fixtures including one where the battery loses money over the window.

## Files modified

- `app/results_view.py` — `_heatmap_axes` (extracted), `_earnings_heatmap`,
  `_saved_heatmap`, `_per_interval_bill` (extracted to module level), two clip
  constants, wiring and module-header inventory.
- `app/templates/_panel_results.html` — tab renamed, two chart blocks, two JSON
  data nodes, captions and footnotes, comments rewritten.
- `app/templates/workspace_results.html` — `drawEuroHeatmap` shared routine plus
  two named wrappers, tab-map and recompute wiring.
- `app/locales/**` — five new msgids per chart, Dutch at 100%, catalogs
  recompiled.
- `tests/test_results_view.py` — 15 new tests across the two charts.
- `tests/test_smoke.py` — two new browser tests.
- `docs/specs/02-ux-wireframes.md` — §2.4 rewritten for three charts.
- `docs/specs/followups.md` — C2a closed, C2 corrected.
- `docs/specs/implementation-progress.md` — retired-key row updated.

## Current status

Complete and committed. The *Battery rhythm* tab ships three heatmaps on one
shared axis. C2a is closed.

Deliberately NOT done, and still open:

- **C2's second question** — whether the SoC grid should be overlaid or
  differenced against the perfect-foresight benchmark. Untouched by this work,
  and a fourth grid would now have to earn its place against three.
- **The recompute-path coverage gap** described above.
- **The pre-existing `_cost_dataset` weakness** — its two runs export the same
  amount, so that fixture cannot see a sign error on the export term. The new
  tests work around it with a second fixture; the old test was left as it was.
