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

## Current status

Phase 1 and 1b complete and committed. Phase 2 (the §6.5 pricing module, DYNAMIC only) is next.
