# 20260723 — Per-series granularity in the data overview

## Task specification

User request (verbatim, from `todo.txt`):

> UX/wireframes: the data overview may need to show different granularities for different
> data series.

Standing guidance at the top of `todo.txt`:

> Whenever possible, it will be preferable to rewrite/simplify existing paragraphs -- we do
> not have users who know the previous version so there is no need to inform them of what
> has changed.

Phase: **investigation only**. No spec file edited. Deliverable is (a) a statement of the
current resolution/granularity model, (b) an affected-file inventory, (c) clarifying
questions with options and recommendations.

## The current model, as the specs stand

Established by reading `05-data-formats.md` §4.1, `06-home-assistant-ingestion.md` §4.3,
`07-internal-representation.md` §4.4, `09-ingest-algorithms.md` §6.1–6.2,
`14-diagnostics.md` §7.1/§6.13, `15-data-quality-and-limits.md` §7.3 and
`02-ux-wireframes.md` §2.2.

1. **Series genuinely arrive at different native resolutions, and the specs already say
   so.** `05-data-formats.md` §4.1 opens by justifying the long CSV format on exactly this
   ground: "series legitimately arrive at **different resolutions** (hourly meter data,
   15-minute prices, 5-minute recent HA data). A wide format would force a common grid at
   ingestion time, which is precisely the wrong place to make that decision."
2. **Native resolution is carried per series.** `SeriesFrame.resolution_s: int | None`
   (`None` if irregular), and it is persisted per series — `08-architecture.md` §5.1 has
   `series_meta(id, dataset_id, name, kind, resolution_s, path)` and files named
   `<name>_<res>.parquet`. The data model already supports per-series granularity; nothing
   new needs inventing at that layer.
3. **One grid is chosen for the whole run, and it is the coarsest.** `choose_grid` in §6.2
   takes `max(resolution_s)` over the **energy** series that cover the window. Price series
   are excluded from the vote. Energy downsampling (summing deltas) is exact; upsampling
   energy is forbidden by assertion, since it would require assuming a within-interval
   profile. Prices downsample by unweighted mean and upsample by forward-fill (a price is a
   step function).
4. **Coarser-than-grid never happens for energy; finer-than-grid is the normal case.**
   Because the grid *is* the coarsest energy series, no energy series is ever coarser than
   the grid. A price series may be either: 15-minute prices against an hourly grid are
   averaged down (with an explicit warning note in §6.2 that this is only exact under
   uniform intra-hour consumption, and the residual error is bounded by §6.16); hourly
   prices against a 5-minute grid are forward-filled.
5. **Mixing resolutions mid-run is explicitly forbidden.** §6.2: "One grid is chosen for
   the **whole window**. Mixing 5-minute and hourly within a single run would make the
   battery's behaviour resolution-dependent mid-run and the results internally
   incomparable."
6. **The cost of the chosen grid is measured, not assumed.** §7.1 overlap (full window,
   always available) measures how much information the recording resolution destroyed;
   §6.13 resolution bias (trailing 5-minute window only) measures how much that changes the
   answer; §6.16 price bracket bounds the pricing half.
7. **What the user is told today is one line, and it is aggregate.** Panel ① data-quality
   box: `Resolution   hourly · 5-min available for last 9 days`. The collapsed panel ①
   summary says `Home Assistant · 5 series · hourly (5-min for last 9 days)`. Panel ③ says
   `2025-07-22 → 2026-07-21 · hourly · 8,760 intervals`. The result object carries
   `window.dt_hours` / `window.resolution` — a single simulation-grid figure.

**The gap the request names.** Native per-series resolution exists in the model
(`SeriesFrame.resolution_s`, `series_meta.resolution_s`) and is never surfaced. The one
resolution line the user sees conflates two different things — the simulation grid, and
the fact that a finer copy of *some* series exists for part of the window — and attributes
neither to a particular series. A user with hourly meter data and 15-minute spot prices is
told "hourly" and has no way to learn that their price granularity was averaged away, even
though §6.2 says that loss should be flagged and §6.16 exists to bound it.

## Phase 2 — the user's instructions (relayed by the coordinator, verbatim in substance)

> The user has reviewed your investigation and approved the work. Proceed with the edits
> now. Decisions — your recommendation is adopted on every question except Q6:
>
> **Q1: option (c)** — show both native resolution and how it was reconciled with the
> simulation grid, as two columns. The delta between them is the point.
>
> **Q2: option (b)** — informational table PLUS close the existing gap. Add the
> price-granularity-lost diagnostic that §6.2 already promises, as a warn-level finding
> when a price series is downsampled by a factor ≥ 2. Do not add a broader check family;
> energy downsampling is exact and warning about it would train users to ignore the box.
>
> **Q3: option (b)** — one row per series, with the native-resolution cell showing both
> resolutions and their coverage (e.g. `hourly (full) · 5-min (last 9 d)`) for the HA
> dual-fetch case.
>
> **Q4: option (b)** — add a per-series block to the result object in
> 07-internal-representation.md §4.5, not frontend-only. Include it in the "Where each
> block comes from" table. Per the established convention, state explicitly that this block
> is invariant under both the `has_pv` and `simulate_cost` toggles, and cover it in the
> cost/PV shape sections.
>
> **Q5: option (b)** — value plus a one-line "why", as prose beneath the box rather than
> inside it: the coarsest energy series sets the grid, and upsampling energy is refused
> rather than guessed.
>
> **Q6: DEFER — do not resolve.** The user wants the irregular-series hole
> (`resolution_s = None`) recorded in 17-open-questions.md as a new open question rather
> than settled now. Write it up properly: what is undefined today (what makes a series
> irregular, whether it blocks a run, and that `max()` over a list containing `None` is
> undefined in `choose_grid`), the options you identified, and note that it is pre-existing
> rather than created by this change. The overview should render such a series as
> `irregular` without committing to grid semantics — say that explicitly, so the UI is
> specified even though the ingest behaviour is not. Update the open-questions header
> count.
>
> On the CSV upload box (your inventory raised whether to show detected native resolution
> per uploaded file): the NEXT todo item is "when adding a CSV file, the user should be
> prompted to indicate what data series the CSV is for", which will rework that box anyway.
> Do the minimum here — do not redesign the upload box; leave the fuller treatment to that
> item.
>
> Also add the validation fixture you proposed: hourly energy + 15-minute prices asserts
> the grid is hourly, native resolutions are reported as 3600 and 900, the price series is
> marked downsampled, and the granularity-lost flag is set.
>
> Follow the todo.txt guidance: rewrite and simplify existing paragraphs rather than
> annotating what changed — there are no existing users, so never describe the previous
> version. Do NOT modify todo.txt and do NOT commit.

## Phase 2 — decisions and rationale

### The vocabulary, fixed once

Two terms are now used consistently across the package and defined in one place (§6.2):

- **Native resolution** — the spacing at which a series was recorded, per series. This is
  `SeriesFrame.resolution_s`, already in the model.
- **Simulation grid** — the single uniform spacing every series is reconciled onto before
  the run, chosen as the coarsest native resolution among the energy series.

Everything the request asks for is the difference between these two, made visible per
series. The specs previously used "resolution" for both, which is why one aggregate line
could stand in for a per-series fact without looking wrong.

### The per-series table (Q1, Q3)

Panel ①'s single `Resolution` row becomes a table with one row per mapped series and three
informative columns: native resolution (carrying both resolutions and their coverage in the
HA dual-fetch case), what the run used, and how the two were reconciled. The reconciliation
column is the load-bearing one — `exact` for energy summed down, `averaged` for a price
downsampled, `held` for a price forward-filled, `—` where native already equals the grid.

`averaged` is the only value that represents a real loss of information, and it is the only
one rendered with a warning marker. Energy downsampling by summation is exact and price
forward-fill is exact for a step function; marking either would dilute the one marker that
matters.

### The price-granularity diagnostic (Q2)

§6.2 already instructed the implementer to "record this in `diagnostics`" and no field
existed to record it in. That instruction is now discharged:
`diagnostics.price_granularity_lost` (bool) and `price_native_resolution_s` (int | None),
raised as a `warn` when a price series is downsampled by a factor ≥ 2, with check 3b added
to §7.3 in execution order beside the existing gap check.

The factor-of-2 threshold rather than "any downsampling" keeps the warning attached to the
case that actually costs the user something — 15-minute prices into an hourly grid, factor
4 — and avoids firing on a series whose native spacing merely differs by rounding.

The diagnostic is deliberately **not** gated on `simulate_cost`. The lost granularity is a
property of the data, and the spot series is a dispatch signal in both cost modes
([§1.4](../specs/01-product-brief.md)); a user running energy-only is subject to exactly the
same dispatch error. This follows the §6.13 precedent, where the kWh-basis figure is
computed unconditionally for the same reason. §6.16, which bounds the *pricing* half of the
same mismatch, remains cost-only and unchanged.

### The result-object block (Q4)

A `series` array is added to §4.5, one entry per ingested series, carrying `name`, `kind`,
`native_resolution_s`, `coverage`, `fine_resolution_s`/`fine_coverage` for the dual-fetch
case, and `reconciliation`. The `window` block keeps `dt_hours` and `resolution` and is now
explicitly labelled the simulation grid.

The block is **invariant under both toggles** and is stated as such in both shape sections.
It describes the input data, and neither `has_pv` nor `simulate_cost` changes what was
ingested — `has_pv` changes which series are *required*, and a series absent from the input
is simply absent from the array rather than present with null fields.

### The irregular-series hole (Q6, deferred)

Recorded as new open question §8.20 rather than settled. It is pre-existing: `resolution_s`
has always been `int | None`, and `choose_grid`'s `max()` over a list that may contain
`None` has always been undefined. The request only makes it visible, because a table column
must print something.

The UI half is specified anyway — such a series renders as `irregular` in the native column
and the reconciliation column reads `undefined`, with no claim about what the run does. This
keeps the frontend implementable while the ingest semantics stay open, which is the same
split the package already uses for the soft-blocked phase topologies.

### CSV upload box

Left as-is beyond a single line of prose noting that a wide-format upload has one native
resolution for every column by construction. The next todo item reworks that box.

## Files modified

| File | Change |
|---|---|
| `specs/02-ux-wireframes.md` | Panel ① quality box: `Resolution` row replaced by a per-series granularity table; explanatory prose beneath the box covering native vs simulation grid, why the coarsest energy series wins, and why energy is never upsampled; the `averaged` marker explained. §2.1 collapsed summary restated in terms of the simulation grid. §2.4 period line and caveats box name the simulation grid and carry the price-granularity caveat. One line added to the CSV box prose about wide format. |
| `specs/09-ingest-algorithms.md` | §6.2 rewritten around the native-resolution / simulation-grid vocabulary; the invariant that no energy series is ever coarser than the grid stated explicitly; the reconciliation outcomes named (`exact`, `averaged`, `held`); the "record this in diagnostics" note repointed at the named fields and check 3b; irregular series flagged as open question §8.20. |
| `specs/07-internal-representation.md` | §4.4 note on `resolution_s` as the source of the overview and what `None` means; §4.5 gains the `series` array and the two `price_granularity_*` diagnostics fields; `window` labelled the simulation grid; "Where each block comes from" table gains the row; both shape sections state the block is invariant. |
| `specs/05-data-formats.md` | §4.1 preamble connected forward to what the overview reports; §4.2 wide format states it fixes one native resolution across all columns. |
| `specs/06-home-assistant-ingestion.md` | Fetch strategy states how the dual hourly/5-minute fetch is reported in the overview — one series, two resolutions with their coverage. |
| `specs/15-data-quality-and-limits.md` | §7.3 gains check 3b (price granularity lost); the note beneath the table extended to say it is not cost-gated and why. |
| `specs/14-diagnostics.md` | Comparison table gains the granularity-loss row and distinguishes it from §6.16; §6.16 cross-reference added. |
| `specs/16-validation-harness.md` | New fixture 21 (mixed native resolutions). |
| `specs/17-open-questions.md` | New §8.20 (irregular series). |

Verified unchanged: `08-architecture.md` (`series_meta.resolution_s` already carries the
field), `04-state-machine.md` (computed at `LOAD_SUCCEEDED` with the rest of the QA),
`10-pricing.md`, `11-policies-and-battery.md`, `12-metrics-and-benchmarks.md`,
`13-configuration-epochs.md`, `appendix-a-defaults.md` (no new tunable — the factor-of-2
threshold is a fixed diagnostic constant, not a user parameter).

## Obstacles and solutions

- *"Resolution" named two different things throughout the package.* Solution: fix the two
  terms in §6.2 and use them consistently; most edits elsewhere are then a word change.
- *The §6.2 note promised a diagnostics field that did not exist.* Solution: name it, and
  add the check that raises it, rather than softening the note.
- *A per-series table has to print something for an irregular series while its ingest
  semantics stay open.* Solution: specify the rendering, not the behaviour, and point at
  §8.20.

## Current status

- [x] Investigation complete; findings returned and approved.
- [x] Decisions recorded above.
- [x] Edits applied to all nine affected spec files.
- [ ] User review of the applied edits.

`todo.txt` is unchanged and nothing is committed, both deliberately.
