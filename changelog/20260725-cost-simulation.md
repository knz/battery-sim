# 2026-07-25 — Cost simulation (§6.5, §6.10, run E, cost benchmark, UI)

## Task specification

Original request: *"let's start implementing cost simulation now. with regards to UX, we'd like
the labels and fields in the panels that pertain to cost simulation to be rendered in a different
color."*

Two parts:

1. **The cost path**, which the spec has fully described and the build has entirely deferred:
   §6.5 price curves, §6.10 cost accounting and the waterfall, run E (the cost-objective
   perfect-foresight DP), `cost` / `benchmarks.cost` in the result object, the panel ② Pricing
   box, and the panel ③ COST SAVINGS section. Retiring the `simulate_cost` pending affordance is
   part of this.
2. **A UX addition not in the spec**: labels and fields belonging to cost simulation render in a
   distinguishing colour, in both panels.

Working method, at the user's direction: implementation and review by sub-agents, iterating until
review comes clean; minor review findings either fixed immediately or filed in `followups.md`;
commits between phases.

### The user's prompts, verbatim

Recorded because this task changed files under `specs/` — see `specs/CLAUDE.md`. In order:

> let's start implementing cost simulation now.
>
> with regards to UX, we'd like the labels and fields in the panels that pertain to cost
> simulation to be rendered in a different color.

> i'll welcome a plan in phases

> please proceed; use sub-agents for implementation and review and iterate between them until
> review comes clean (if there are minor issues in review either address them immediately or flag
> them for follow-up work in `followups.md`)
>
> you may commit your work between phases

> we'll also want to mark the existing items in followups.md as "DONE" in the doc, as they get
> solved

> leave it for the FIXED/VARIABLE increment

*(in answer to whether `tariff_zone` and the local-time axis should be built now)*

> from now on please proceed without my approval unless there are open decisions that need my
> input

Plus three plain "proceed" replies advancing the phases.

## Scope decisions (answered by the user before work started)

| Question | Decision |
|---|---|
| How much of the cost path | Full vertical slice — domain **and** UI |
| Contract types | DYNAMIC built; FIXED and VARIABLE ship as pending controls |
| The cost colour | daisyUI `accent` on labels + field accents |
| Adjacent features | Feed-in floor period top-up **in**; monthly savings (€) **in** |
| Deferred | §6.16 price bracket, §6.13 euro resolution bias, tiered TLK, §6.15 epochs, §4.6 CSV |

Two later decisions, taken mid-flight:

- **`tariff_zone` and the local-time axis are deferred to the FIXED/VARIABLE increment** (user's
  call). Only FIXED and VARIABLE read the dal window; DYNAMIC prices off spot. Recorded as
  followup H1 with an explicit DST warning — see *Obstacles* below.
- **Existing `followups.md` items are marked DONE as this work closes them**, following the
  `- DONE` convention already on section A.

## Phase plan

1. Cost parameters on the config *(done)*
2. §6.5 pricing module — DYNAMIC only, no `tariff_zone`
3. §6.10 cost accounting + waterfall, fixture 4
4. Run E, `benchmarks.cost`
5. Panel ② Pricing box
6. Panel ③ COST SAVINGS section
7. The accent colour
8. i18n, catalogs, `implementation-progress.md`

## Phase 1 — cost parameters on the config *(complete)*

### What was built

A fifth config group, `PricingConfig`, mirroring the panel-② Pricing box one-to-one exactly as the
existing four groups mirror theirs. Three enums (`Contract`, `FeedinFloorMode`, `TlkMode`) carry
all their spec values even where only one is built out, so the vocabulary does not change when the
rest ship. 15 fields, appendix-A defaults throughout.

### Decisions and rationales

- **Retention, not forcing.** Appendix A requires cost parameters to be *retained at their stored
  values* when `simulate_cost` is false, so enabling cost simulation restores the user's
  configuration rather than resetting it. `_force_invariants` therefore does **not** touch any
  pricing field — the opposite treatment from `economic_guard` and `pv_coupling`, which are
  genuinely forced. Both docstrings now state why the two differ, because the next reader will
  otherwise generalise the forcing pattern to a third group and silently wipe the user's contract
  settings on every toggle.
- **Validation is gated entirely on `simulate_cost`**, funnel included. An energy-only run — the
  default — must never be blocked by a field the user was never shown.
- **Inclusive bounds on α and VAT.** §6.5's preset table lists α = 0.00 (flat feed-in rate) and
  α = 1.00 (spot); exclusive bounds would reject two of four documented presets.
- **No sign check on `feedin_beta` or `supplier_markup`.** The "Spot minus fee" preset is
  β = −0.0200. A negative-value check there would reject the spec's own table.
- **No bound invented for `rate_normaal`/`rate_dal`.** §6.5 legislates none and no code reads them
  until FIXED ships; a guessed bound is worse than the finiteness funnel. Recorded as a deferral
  at the check site rather than as a judgement that negative rates are meaningful.
- **The dal window wrapping midnight is not an error.** Appendix A's default is 23 → 7, i.e.
  start > end. An inverted-range check of the kind used on the price bands would flag the shipped
  default.
- **`not_a_choice` on the three pricing enums** (added after review). §6.5 dispatches on these
  with an if/elif/else chain, so a `None` or a bare string takes a silent branch — `tlk_mode` falls
  through to `tiered_tlk_rate` with no tier table, a bad `contract` prices as whichever branch is
  last. A confident wrong euro figure is exactly what §1 refuses. `dal_weekends` is deliberately
  excluded: every object is truthy or falsy, so there is no unrepresentable value.

### Obstacles and solutions

- **`clone()` silently dropped the new group** — it rebuilds a config group by group, so any
  panel-② submission would have reset pricing to defaults. Same defect
  `test_clone_preserves_has_battery` already exists to guard against. One line plus a test.
- **`to_dict`/`from_dict` serialised four groups, not five**, so pricing survived in-process but
  not a restart — half-defeating the retention rule the phase was built around, and leaving
  Phase 5's form with nowhere to persist to. Built as Phase 1b rather than deferred, since Phase 5
  depends on it. Confirmed real: 8 of the new tests fail against the pre-fix store.
- **Two docstrings overstated their sources.** One justified four omissions as "each needs a
  structure rather than a scalar" when two of them (`feedin_floor_period`, `supplier_settlement`)
  are plain scalars omitted for a different reason — nothing consumes them yet. The other restated
  the feed-in floor statute as "at least one month", which §6.5 explicitly disclaims ("It does not
  say *ten minste* a month and it does not say *precies* a month"). Both corrected; the second
  matters because a settled-sounding legal claim in the module that names the parameter propagates
  into UI copy.
- **The local-time axis does not exist.** §6.4's dal mask is a wall-clock rule but the whole
  pipeline is UTC-naive by design. Deferred at the user's direction; see followup H1, which states
  the DST trap explicitly because nothing would catch it — the window would shift an hour in
  winter and two in summer, and no figure would look wrong.

### Files modified

- `app/domain/simconfig.py` — three enums, `PricingConfig`, wiring into `SimulationConfig` and its
  defensive copy, validation (funnel + range + enum checks), docstring updates throughout.
- `app/simconfig_store.py` — `clone()` carries pricing; `to_dict`/`from_dict` serialise it;
  docstrings updated ("four groups" → "five").
- `tests/test_simconfig.py` — appendix-A and §2.3 default tables extended; a pricing section
  covering the enum vocabulary, gating both directions, inclusive bounds, the wrapping dal window,
  retention round-trips (in-process, through a document, and through a real `save()`/`load()`),
  malformed enums and numerics, and the defensive copy.
- `followups.md` — new section H (H1–H8): what this increment defers, and the review findings not
  fixed.

### Review

One review pass, adversarial, against the spec. **No blocking findings.** It verified by brute
force that no input raises (480 constructions × every read path), that no pricing field is ever
reset, and that no pricing issue leaks in energy-only mode. Six minor findings: three fixed
immediately (the two docstrings, the enum gap, plus a disconnected piece of reasoning and an
unpinned warning assertion), four filed as H5–H8.

### Status

**Complete.** 638 passed, 2 skipped (the 2 skips pre-existing; suite was 617 before this work).

## Phase 2 — the §6.5 pricing module *(complete)*

### What was built

`app/domain/pricing.py` — `bare_supply_price` (DYNAMIC branch only), `import_price`,
`feedin_compensation` (unclamped), `export_price_net` (FLAT terugleverkosten only), and
`feedin_floor_topup` with both assessment modes. FIXED, VARIABLE and TIERED raise
`NotImplementedError` rather than falling back to a number, so an unbuilt contract cannot produce a
confident wrong figure. `tariff_zone` is not built (followup H1); DYNAMIC never reads it.

### Decisions and rationales

- **`PriceCurves`, a frozen bundle, rather than a tuple of arrays.** `compensation` and
  `p_export_net` are both EUR/kWh, both frequently negative, and differ by a constant — a
  transposed pair at a call site is invisible by inspection and would produce a wrong bill closing
  against a wrong waterfall. Named fields make that a typo instead of a silent sign error.
- **The top-up returns as a separate scalar**, never folded into `p_export_net`. §6.10 is explicit
  that there is no correct per-interval allocation of it, only conventions, and folding it in would
  turn the waterfall's exact identity into one. `FeedinFloorResult` carries the two §4.5
  diagnostics alongside it so they cannot drift from the number they describe.
- **`cfg` is `PricingConfig`, not `SimulationConfig`.** Nothing here reads outside the pricing
  group, and the narrower parameter makes the module testable without building a whole config.
- **NaN propagates through the price functions; the floor excludes it from its sums.** Matches
  `simulate.py`, which writes NaN into flow arrays and has consumers use `np.nansum`. A NaN top-up
  would poison the euro figure for a window priced almost everywhere.
- **`shorter_than_period` is derived from the window's duration, not its bucket count** (see
  below).

### Obstacles and solutions

- **The §7.4 short-window flag missed every sub-month window straddling a month boundary.** It was
  computed only in the single-bucket branch, so a 3-day run over 30 Jan → 2 Feb reported
  `shorter_than_period=False`. That is the case the flag most needs to fire on: such a window is
  assessed as two sub-month *fragments*, a weaker constraint than the same three days inside one
  month — which the bucket-count reading did flag. Now measured against the shortest month the
  window touches, which is the conservative direction (a window between the shortest and longest
  touched month is not flagged, since it may well cover a whole period). Any run started mid-month
  and shorter than a month hit this.
- **UTC month buckets are not Amsterdam month buckets.** Measured rather than assumed: an interval
  at 2026-03-31T23:00Z is 1 April CEST, and moving it across the boundary changes a constructed
  month's top-up from €0.30 to €0.60. Filed as H9 to be fixed alongside H1's timezone work, since
  both need the same conversion.

### Review

One review pass, adversarial, mutation-tested. It confirmed by mutation that the two floor modes
are not transposed (swapping them turns 9 tests red), that no clamp crept into the per-interval
compensation, that every unbuilt path raises rather than returning, and that each arithmetic term
is pinned — dropping the tax, dropping VAT, applying VAT before tax, or flipping any sign turns
tests red. It independently recomputed every asserted constant.

One real defect (the short-window flag, fixed above) and two cosmetic findings, both fixed: a
module-docstring adjacency that read as though FIXED's rates were missing when only VARIABLE's
schedule is, and a contiguity precondition on `index` that lived in a comment inside the function
rather than in its docstring where a caller would look.

### Status

**Complete.** 672 passed, 2 skipped.

### Note on fixture 18, for Phase 3

Fixture 18 (cost-invariance of the energy results) is stricter than a spot check: it requires
asserting `window`, `series`, `energy`, `ratios`, `battery`, `benchmarks.energy`, `epochs`,
`topology` and `diagnostics` block by block, plus a bit-identical per-interval SoC trace — "not a
sample, each of the three known ways to break this lands in a different one". The three failure
modes it distinguishes: a difference in `energy` or the SoC trace means a cost term leaked into
dispatch (most likely `economic_guard`); one in `benchmarks.energy` means the DP was retargeted at
euros instead of a second DP being added; one in `diagnostics` means §6.13 selects its basis from
`simulate_cost`. Written down here because the fixture becomes runnable in Phase 3 and its value
lies in the discrimination, not in the pass/fail.

## Phase 3 — §6.10 cost accounting and the waterfall *(complete)*

### What was built

`app/domain/costs.py` — `compute_costs` over flow arrays (returning `CostResult`: the marginal
bill, the top-up, and the pre-top-up bill), and the eight-line `waterfall` with §6.10's exact
labels. Fixture 4's closure identity was written test-first; fixture 14 pins that the floor top-up
appears in its own line and in no other.

### A spec defect found by writing the test first — §6.10's pseudocode does not close

**This is a correction to the specification, not a deferred item.**

§6.10 wrote the standby line as `cost(B) − cost(C)`. Since `compute_costs` returns
`per_interval − topup`, that drags a top-up difference into a line which is otherwise a
per-interval quantity, and the identity does not close. The residual is exactly `top(C) − top(B)`:
`top(C)` enters twice and `top(B)` once with the wrong sign.

Verified algebraically before accepting it, independently of the implementation. Taking the line on
the **pre-top-up** bills makes the three groups tile the difference exactly, each top-up appearing
once — lines 1–5 give `per(A) − per(B)`, line 6 gives `per(B) − per(C)`, line 7 gives
`top(C) − top(A)`.

This is the same argument §6.10 already makes for giving the top-up its own line: it is a
period-level scalar with no per-interval decomposition, so it must appear once and nowhere else.
`standby_consumption` is a per-interval term and must not carry a share of it.

**Why it survived review of the spec:** the error is invisible in almost every window, because both
top-ups are zero unless a period's export earned a net negative amount. It surfaces only under
fixture 14's conditions *and* only when the standby run difference is what moves the floor across
zero. A fixture that merely binds the floor in run A passes under both readings — which is what the
original brief asked for, and would have missed it.

Spec files changed: `specs/10-pricing.md` (the pseudocode plus a new subsection deriving the
residual) and `specs/16-validation-harness.md` (fixture 4 now requires both a run with all six
per-interval lines nonzero and a run where the standby difference moves the floor).

### Other decisions

- **`"enabled": false` on the degradation line is left to the view.** Whether degradation is
  enabled is a fact about the config (`degradation_eur_per_kwh == 0`); a run can produce €0.00 with
  degradation fully enabled by never discharging. Conflating the two here would lose that
  distinction.
- **`CostResult` does not carry the floor's two §4.5 diagnostics.** They describe the window, not
  the run, so they are identical across A/B/C; restating them per run would suggest C could clip a
  different number of months than A.
- **`waterfall` takes two arguments §6.10's signature omits** (`index`, `p_export_net`), appended
  after the spec's six so the leading arguments still read as §6.10. The pseudocode treats `cost()`
  and `topup()` as ambient.

### Review

Mutation-tested: 22 of 22 perturbations across the eight lines turned tests red, including the
literal-spec `cost(B) − cost(C)` standby form, so the corrected identity is genuinely pinned rather
than fitted. Every hand-computed constant was independently recomputed. Clean on closure
derivation, sign conventions, top-up separation and fixed-cost exclusion.

Four findings fixed:

- **The gap-alignment precondition was stated as fact but not enforced**, and the closure is
  silently wrong when it is violated — measured at €0.74 against a tolerance of 1e-6 on a
  three-interval misalignment. A difference gapped in one run but not another drops out of the
  A-vs-B group while remaining in the B-vs-C group, so the two sides stop partitioning the same
  window. Now asserted; `run_all` satisfies it by construction.
- **`lost_feedin_compensation` was documented as negative "by construction" and is not.** It flips
  positive exactly when compensation is negative — the case this tool exists to surface, where not
  exporting is a gain. Both the module's own primary fixture and fixture 14 produce it positive, so
  the docstring contradicted the tests beside it.
- **The degradation line's run was pinned only by a dispatch accident.** Every hand fixture gives
  runs B and C identical `withdrawn` (standby is served from the grid and from export, not by extra
  discharge), so swapping C for B was invisible to them; it turned exactly one test red, and only
  because real dispatch happened to differ there. Now asserted directly, and verified by mutation
  that the new test discriminates.
- **A forward-looking claim about TIERED was stated as settled.** §6.5 does not say what a window
  spanning a tier boundary resolves to, so the scalar `tlk` shape is chosen for what exists rather
  than as a prediction.

Two test docstrings overstated their coverage and were corrected rather than the tests changed: the
"arbitrage" run has no export at all (`allow_grid_export=False`, no PV, so four of eight lines are
zero — "arbitrage" there names the band policy, not arbitrage export), and the PV run's export is PV
surplus, which `allow_grid_export` does not gate.

Left as a known robustness gap rather than fixed: `waterfall` takes `compensation` and
`p_export_net` as positional arguments four apart, which is the transposition hazard `PriceCurves`
exists to prevent. Taking the bundle directly would remove it, but that trades away §6.10's
readable signature; the current tests do catch a transposition.

### Status

**Complete.** 693 passed, 2 skipped.

### Note on run E, for Phase 4

`_Transition` in `app/domain/benchmark.py` currently returns `soc_next`, `imp` and `feasible` — the
energy objective needs import alone. The cost objective prices **both** directions (`imp` at
`p_import`, `exp` at `p_export_net`, which may be negative), so run E needs `exp` carried out of the
transition as well. That is the one structural change to the DP; everything else §6.12 requires —
the interpolation, the starting SoC on the state grid, the exact PV-surplus and household-deficit
action points, the terminal constraint — is already built and is shared unchanged between the two
objectives. §6.12 is explicit that only `transition_cost` differs.

## Phase 4 — run E and `benchmarks.cost` *(complete)*

### What was built

§6.12's DP is now parameterised by an `Objective` whose only method is `cost(tr, i)` —
`transition_cost` and nothing else. `ENERGY_OBJECTIVE` minimises kWh of import; `CostObjective`
minimises `imp × p_import − exp × p_export_net`. One DP, one state space, one action set, one
feasibility rule, one terminal constraint. `_Transition` now carries `exp` as well as `imp` (it was
already computed as a local for the export cap; only the attribute is new). `cost_benchmark(...)`
returns a `CostBenchmark` mirroring `EnergyBenchmark`'s shape and its None conventions, billing the
DP dispatch through §6.10's `compute_costs` rather than reimplementing it.

A class rather than a callable or an enum: a closure makes "which prices was this computed under?"
unanswerable from the result, and an enum pushes the price arrays into `perfect_foresight`'s
signature as parameters required for one member and meaningless for the other — the arrangement
that lets a caller ask for euros and silently get kWh.

Run E follows run D's laziness (both cost ~4.6 s against ~0.12 s for runs A/B/C), so neither
`GET /` nor `POST /results` pays for a DP.

### Two spec gaps found, both recorded rather than papered over

- **§6.12's drift correction has no sound euro analogue (H10).** In kWh it is exact — a residual
  kWh is worth one avoided kWh whenever used. In euros the residual's worth depends on *when* it is
  used, and the two sides use it at different times by construction: the DP's terminal constraint
  forces it to hold charge through the expensive hours, a liquidating policy dumps it into the cheap
  ones. Measured: the median-price correction leaves fixture-6 violations up to €0.91; valuing at
  the window maximum nearly restores the ordering, which is evidence the *basis* is wrong rather
  than the DP. No correction is applied; the median price is reported as an input; fixture 6 is
  asserted over non-liquidating configurations, the form §6.14 itself names. Pinned by a test that
  asserts the correction *fails*, so nobody re-derives it as an improvement.
- **The feed-in floor top-up is not separable inside the DP (H11).** It is a period aggregate, so
  pricing it per-interval would need the period's running export revenue as a second state
  dimension. Run E minimises the per-interval bill and applies the top-up afterwards, flagging
  `floor_binds`. In a floor-binding window the bound is on the pre-top-up bill; how large a
  full-bill violation could get is unmeasured.

### Review

Verified independently rather than by inspection alone: the reviewer reproduced both drift
measurements to the digit (€0.913442 worst violation under median-price correction; exactly 0.0
over the 72 non-liquidating configurations), probed whether that clean 0.0 was a degenerate sweep
(it is not — 26 exact ties where the band policy genuinely *is* the euro optimum on a square wave,
46 with a median gap of €1.70), and re-ran all 17 cost tests at appendix-A grid resolution to check
that the coarse-grid reasoning was not producing false passes. It also confirmed the two objectives
diverge stably across grids (energy DP 48.00 kWh vs cost DP 49.72 kWh, each beating the other on
its own quantity by margins far outside discretisation).

Clean on: one-DP-not-two, fixture 18/20 bit-identity, no cross-block assertion, objective
divergence, run E laziness, and test-resolution honesty.

Three defects fixed:

- **A dead `template` parameter on `_dispatch_flows` whose docstring claimed it supplied the
  interval count and starting SoC** — both actually come off `result`. It had already produced a
  wrong-typed call in the tests (a `DispatchResult` passed where a `Flows` was annotated, working
  only because the argument was ignored), which is exactly what a dead parameter with a false
  docstring invites.
- **A stale §6.12 quotation the spec has retracted.** The module docstring described snapping as "a
  systematic pessimism bias of several percent"; §6.12 now records that this was wrong in both
  direction and magnitude — snapping is *optimistic* and lands below the realised saving, so it
  bounds nothing. The repo contained the retracted claim and its own contradicting test.
- **`CostBenchmark.capture_ratio` documented a routine outcome as a defect.** A euro ratio above 1
  is usually drift-funding: 48 of 144 swept configurations exceed it, up to 1.60. The energy block
  handles this by restating on the drift-corrected basis — which, per H10, does not exist in euros.
  The docstring now tells a view to branch on `policy_soc_delta_kwh` and say the comparison is
  unavailable, rather than reaching for a correction there isn't one of.

### Known scope limit

`cost_benchmark` has **no production caller yet** — it is exercised only by tests. `benchmarks.cost`
reaches the result object in Phase 6, when panel ③ renders the COST SAVINGS section. Staged
deliberately, but worth stating plainly rather than letting "Phase 4 complete" imply the figure is
on screen.

### Status

**Complete.** 709 passed, 2 skipped, 64.8s (the cost half adds ~8s).

### Groundwork noted for Phase 5

Panel ② already has the two mechanisms the Pricing box needs, so neither has to be invented:
`FIELDS` in `app/params_view.py` drives coercion in both directions from one table (so a field
converted on the way in is converted on the way out), and `_panel_params.html` already renders
disabled-with-a-reason radios for the PV-gated charge policies — the same shape FIXED and VARIABLE
need as pending controls.

## Current status

Phases 1, 1b, 2, 3 and 4 complete and committed (709 passed, 2 skipped). The whole domain layer
of the cost path is built; nothing of it is on screen yet. Phase 5 (the panel ② Pricing box) is
next, and is where `simulate_cost` stops being a pending control.

Working agreement from this point: phases run to completion without check-in; only genuine open
decisions are brought back to the user.
