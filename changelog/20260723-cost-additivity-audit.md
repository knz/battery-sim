# 2026-07-23 — Making cost simulation a strictly additive layer

Two phases in one entry: an audit of whether `cfg.simulate_cost` was purely additive over
the energy results, and the edits that made it so. The audit is kept because the fixes only
make sense against the violations they close.

## Task specification

### Phase 1 — audit. Original request (relayed via the orchestrating agent, paraphrased)

Verify a specific invariant across the specs as they now stand after
`changelog/20260723-optional-cost-simulation.md`:

> **Cost simulation must be a purely ADDITIVE layer on top of energy results.**
> Enabling `simulate_cost` should ADD cost results and must NOT change any user-facing
> energy result. The same input data with the toggle off vs on must produce identical
> energy numbers, identical charts of energy quantities, identical secondary metrics,
> and identical diagnostics expressed in kWh.

Investigation only — no spec edits. Find every place where the invariant is violated or
ambiguous, be adversarial, and for each finding assess severity, whether the invariant is
achievable, and the fix options. Also check whether any validation fixture asserts
energy-invariance across the toggle, and whether it is stated correctly.

Suspicious areas named in the request: the perfect-foresight DP benchmark and any capture
ratio; `economic_guard`; charge/discharge policy availability; §6.13 resolution-bias
diagnostic; SoC drift / `soc_delta_value_eur`; §6.4 tariff registers and checks 8a/8b;
panel ③ layout; per-interval CSV and result JSON.

## Findings (summary; full detail returned to the caller)

Ordered most severe first.

1. **Perfect-foresight benchmark inside the ENERGY SAVINGS section — genuine violation,
   high severity.** `02-ux-wireframes.md` §2.4 renders a `Benchmark` box (ceiling
   1,988 kWh, "captures 71%") inside `═══ ENERGY SAVINGS ═══`. Per
   `12-metrics-and-benchmarks.md` §6.12 the DP objective follows `simulate_cost`, and both
   files state the two objectives have different optima. Enabling cost therefore changes two
   numbers already displayed in the energy section. §2.4's own note and open question §8.19
   acknowledge this in prose without treating it as a violation.
2. **`benchmarks` excluded from every invariance statement — ambiguity that hides (1).**
   `07-internal-representation.md` "Shape of the object without cost simulation" asserts
   bit-identity for `energy`, `ratios`, `battery`, `epochs`, `topology`, remaining
   `diagnostics` — silently omitting `benchmarks`. It also cites fixture 19 (a shape
   fixture) rather than fixture 18 (the invariance fixture). Fixture 18 likewise omits
   `benchmarks`.
3. **§6.13 resolution-bias `bias_pct` changes with the toggle — genuine violation, medium.**
   `14-diagnostics.md` selects `saved_eur` vs `saved_kwh`, so `diagnostics.resolution_bias_pct`
   differs between modes, yet §4.5 lists `diagnostics` (minus two feed-in fields) as
   bit-identical. Two spec statements contradict each other.
4. **SoC-drift surfacing threshold switches basis — minor violation.** §6.11 applies the 2%
   test to the euro saving with cost on and to the energy saving with cost off, so whether
   the drift caveat appears can flip. `soc_end − soc_start` itself is invariant.
5. **Monthly-savings chart plots kWh vs euros — display swap, not a value change.**
6. **Ambiguity: no statement that the DP's *dispatch* is excluded from the energy claim.**

Not violations, verified clean: `economic_guard` (default `false`, forced off, so the
default path is identical); charge/discharge policy availability (all six remain, no branch
on `simulate_cost`); §6.4 registers and checks 8a/8b (explicitly stated not to reach the
flow simulation, pinned by fixture 15); result JSON and per-interval CSV energy fields;
checks 4/13 (do not gate energy series); `simulate_cost` defaulting to `false`.

**Does an energy-invariance fixture exist?** Yes — fixture 18 in
`16-validation-harness.md`, correctly framed ("bit-identical", names `economic_guard` as
the likely leak) but incomplete: it excludes `benchmarks` and does not mention the
`diagnostics` block, so it would pass over findings 1 and 3.

## Phase 2 — the user's instruction (verbatim in substance, relayed by the coordinator)

> The user has reviewed your audit and approved fixes for all five findings. Proceed with
> the edits now. Make cost simulation a strictly additive layer: enabling it must only ADD
> results, never change a user-facing energy result.
>
> **Finding 1 (benchmark) — your option (a).** Always run the import-objective DP; its
> ceiling and capture ratio are the energy section's, in both modes. When cost is on,
> additionally run the cost-objective DP and show its result in the COST SAVINGS section.
> Two DP runs when cost is on; accept the ~1–3 s. Update §6.12, the panel ③ layout, and
> `benchmarks` in the result object — it now needs to carry both objectives' results when
> cost is on, so revisit the `benchmarks.objective` field; it may become two named blocks
> rather than one block plus an objective tag. Rewrite open question §8.19 from "is the
> second objective worth the maintenance" to record that the second objective is required
> by additivity, and remove the line about the capture ratio changing for reasons unrelated
> to the battery, since it no longer will. Update §6.9's four-run table — with cost on
> there are now five runs.
>
> **Finding 2 (invariance claim).** Fix §4.5: repoint the citation from fixture 19 to
> fixture 18. Once finding 1 is fixed, `benchmarks`' energy-denominated fields ARE
> invariant, so state that positively rather than carving out an exception — the
> cost-objective benchmark is an additional block, not a mutation of the existing one.
>
> **Finding 3 (resolution bias) — your option (a).** Always compute the kWh-basis bias with
> the 5 kWh floor; that is what §6.13 says it measures (dispatch error, which is
> invariant). When cost is on, additionally compute and report the euro-basis figure.
> `resolution_bias_pct` in diagnostics stays invariant. Update §6.13 and the diagnostics
> fields, and resolve the contradiction with §4.5.
>
> **Finding 4 (SoC-drift surfacing).** Use the energy-basis 2% test in both modes, and when
> cost is on add the euro-basis test as an additional trigger — union of conditions, so
> enabling cost can only add a caveat, never remove one.
>
> **Finding 5 (monthly chart).** Keep the kWh series always; when cost is on, add euros as
> an additional chart option (or second axis — your judgement, but state which).
>
> **Fixture repair.** Extend fixture 18's bit-identity list to cover `diagnostics` and the
> kWh-denominated benchmark fields, so it actually guards the invariant. Fixture 20
> currently requires the two DP dispatches to differ — that remains a correct test of the
> cost-objective DP, but re-scope it so it tests the cost-objective run specifically and
> does not read as sanctioning a change to the energy ceiling. Check the other fixtures for
> any that now need adjusting.
>
> Also sweep for the general case of finding 6: the UX and result-object files assert
> invariance in prose. Now that the invariant genuinely holds, make those statements
> accurate and unqualified, and remove any remaining Run-D exception language that finding
> 1's fix makes obsolete.
>
> Follow the todo.txt guidance: rewrite and simplify existing paragraphs rather than
> annotating what changed — there are no existing users. Do NOT modify todo.txt and do NOT
> commit.

## Phase 2 — decisions

The user reviewed the audit and approved a fix for every finding, choosing the
strictest available reading of the invariant: **enabling cost simulation may only add
results, never change a user-facing energy result.** The decisions below are the user's,
recorded verbatim in substance.

### The governing principle, now stated once

Where a quantity has both an energy reading and a euro reading, the energy reading is
computed **always**, on its own basis, and the euro reading is an **additional** output
computed only when cost simulation is on. Nothing switches basis. This replaces the earlier
"select the metric from `simulate_cost`" pattern, which was applied in three places
(§6.12's DP objective, §6.13's bias basis, §6.11's drift threshold) and was the root of
three of the five findings.

### Finding 1 — the perfect-foresight benchmark

**Two DP runs when cost is on** (audit option (a)). The import-objective DP runs in both
modes and owns the energy section's ceiling and capture ratio; a second, cost-objective DP
runs only when cost is on and owns the cost section's. The ~1–3 s of extra compute is
accepted. Rejected alternatives, both considered in the audit: moving the benchmark out of
the energy section (leaves the ceiling objective-dependent, only relabelled), and dropping
the energy benchmark entirely (restores additivity by deleting the number, leaving the
headline kWh figure unanchored — which is what §6.12 exists to prevent).

Consequences carried through the package:

- `benchmarks` becomes **two named blocks**, `benchmarks.energy` and `benchmarks.cost`,
  rather than one block plus an `objective` tag. The tag existed to say which objective had
  been used; with both present unconditionally-or-additively there is nothing to
  disambiguate, and a consumer that finds `benchmarks.cost === null` knows exactly as much.
- §6.9's run table gains run E. Four runs without cost, five with.

### Finding 2 — the invariance claim

`benchmarks.energy` is now invariant like everything else, so §4.5 states the invariant
**positively and without carve-outs** and lists the cost-side blocks as additions. The
citation moves from fixture 19 (a shape fixture) to fixture 18 (the invariance fixture).

### Finding 3 — resolution bias

**Always compute the kWh-basis bias** with the 5 kWh floor, and additionally the euro-basis
figure when cost is on (audit option (a)). §6.13 says it measures *dispatch* error, and
dispatch is invariant, so the kWh basis is the one that matches the diagnostic's stated
purpose; the euro figure is a genuine addition rather than a substitution.
`diagnostics.resolution_bias_pct` is invariant, resolving its contradiction with §4.5.

### Finding 4 — SoC drift surfacing

**Union of conditions.** The energy-basis 2% test runs in both modes; the euro-basis test is
an additional trigger when cost is on. Enabling cost can add a caveat, never remove one.

### Finding 5 — the monthly chart

**Kept as kWh always, with euros as an additional chart option** rather than a second axis.
A second axis was rejected: the two series are not comparable in shape (a euro figure moves
with tariff structure as well as with kWh), and overlaying them re-creates in one chart the
false equivalence that §2.4's two-section split exists to prevent.

### Fixtures

Fixture 18 now covers `diagnostics` and `benchmarks.energy`, so it fails against the
pre-fix specification rather than passing over findings 1 and 3. Fixture 20 is re-scoped to
test the cost-objective DP as an addition — it still asserts the two objectives produce
different dispatches, which remains true and is still the only way to catch a
`transition_cost` that never stopped returning euros, but it no longer reads as sanctioning
a change to the energy ceiling. Fixture 6 asserts the bound per benchmark block.

### Finding 6 — the prose sweep

The Run-D exception language is obsolete and removed wherever it appeared. Statements about
what survives an energy-only run are now unqualified.

## Files modified

| File | Change |
|---|---|
| `specs/02-ux-wireframes.md` | Panel ③ benchmark box relabelled and kept in the energy section unconditionally; a cost benchmark tile added to the cost section; the §2.4 notes rewritten around the two-DP model; monthly chart keeps kWh and gains a euro option; "Panel ③ without cost simulation" simplified |
| `specs/07-internal-representation.md` | `benchmarks` split into `energy` and `cost` blocks, `objective` removed; `diagnostics` gains `resolution_bias_pct_eur`; §4.5's invariance paragraph restated positively and repointed to fixture 18 |
| `specs/11-policies-and-battery.md` | §6.9 run table gains run E; the surrounding prose rewritten from "run D's objective moves" to "run E is added" |
| `specs/12-metrics-and-benchmarks.md` | §6.11 metric table and SoC-drift paragraph rewritten around the union test; §6.12 rewritten for the two-objective, two-run model |
| `specs/14-diagnostics.md` | §6.13 computes the kWh bias always and the euro bias additionally; the availability note rewritten |
| `specs/16-validation-harness.md` | Fixtures 6, 18, 19 and 20 updated |
| `specs/17-open-questions.md` | §8.19 rewritten: the second objective is required by additivity, not a maintenance trade-off |
| `specs/appendix-a-defaults.md` | Note that both DP runs use the same `dp_soc_levels` / `dp_action_levels` |

Unchanged and verified still correct: `09-ingest-algorithms.md` §6.4,
`15-data-quality-and-limits.md` checks 8a/8b, `10-pricing.md`'s gating note.

## Obstacles and solutions

- *`benchmarks.objective` had two jobs — naming the objective and implying which fields were
  populated.* Splitting into two blocks removed both jobs at once; no replacement tag is
  needed.
- *§6.12's "different optima" warning was written to excuse the capture ratio moving.* It is
  still true and still worth stating, but its purpose changed: it now explains why two runs
  are needed rather than why one number changes.

## Current status

- [x] Read AGENTS.md, specs/README.md, prior changelog.
- [x] Surveyed 02, 07, 09, 10, 11, 12, 14, 15, 16, 17, appendix-a.
- [x] Findings returned and approved.
- [x] Edits applied to all eight affected spec files.
- [ ] User review of the applied edits.

`todo.txt` is unchanged and nothing is committed, both deliberately.
