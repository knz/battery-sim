# Spec corrections found by implementing §6.12

## Task specification — the user's prompts, verbatim

The specs directory requires the user's original prompts be recorded (`specs/CLAUDE.md`). This task
is the tail of one conversation; the prompts that produced it, in order:

> can we now add the battery simulation and results to panel 3

> i'd like you to organize the work in phase; for each phase use sub-agents for implementaiton and
> review, and iterate between them until the review is clean. when there are minor review items
> either address them immediately or file for followup work. you are allowed to commit your work
> between phases.

> we'll also want adequate testing

> go ahead

> please update the spec

Answers given to scope questions during that work: panel ② wiring **included** ("option 2, organize
the work in phases"); the §6.12 **energy DP (run D) in scope**, cost DP out; **all three runs A/B/C**;
and, when the DP's cost forced a choice, **lazy-load the benchmark box** rather than cache, skip a DP
or accept a 4.7 s page.

Following the seven-phase implementation recorded in
[20260724-panel3-battery-simulation.md](20260724-panel3-battery-simulation.md), which surfaced four
findings against the specification itself. This task applies them to `specs/`.

## The findings, and their evidence

All four were found by building the thing the spec describes and measuring what came out. Each was
reproduced independently at least twice (implementer, adversarial reviewer, orchestrator).

### 1. §6.12's interpolation rationale is wrong in direction and magnitude

The spec says interpolating `V` "avoids a systematic pessimism bias of several percent". Measured at
six SoC-grid sizes on the same fixture, nearest-snapping is **optimistic**, not pessimistic, and much
larger than "several percent":

| `dp_soc_levels` | snapping | interpolation |
|---|---|---|
| 11 | 9.41 | ~27.56 |
| 21 | 17.41 | 27.59 |
| 51 | 22.72 | ~27.56 |
| 101 | 26.26 | ~27.56 |
| 201 | 26.86 | ~27.56 |
| 401 | 27.13 | ~27.56 |

Realised dispatch: **27.64**. Snapping converges *upward* as the grid refines while interpolation is
stable from 11 levels on. The mechanism: nearest-snapping rounds a landing SoC upward as often as
downward, and an upward round credits the battery with energy it does not have — a small leak at
every transition, compounding over the window.

**Why this matters beyond pedantry:** snapping's figure sits *below* the realised saving, so it does
not bound anything. The spec's stated reason would lead a reader to treat snapping as the safe,
conservative option when it is the unsafe one. The instruction to interpolate is right; only the
justification was wrong.

### 2. §6.12's terminal constraint is asymmetric with the policy run

§6.12 requires the DP to finish at or above its starting SoC. Nothing imposes that on run C, and
§6.11 deliberately reports SoC drift rather than netting it out. So a policy that ends emptier than it
started books grid import avoided that it funded from its opening charge, while the benchmark is
forbidden the same move — and fixture 6's bound can fail on raw numbers with no code defect anywhere.

Reproduced: a no-PV D1 policy over 48 flat hours drains its opening 5 kWh to the 1 kWh floor and books
**+2.35 kWh** of "saving" against a drift of −4.0. A second case (20 kWh battery, 100% initial SoC, 96
intervals) gave policy +14.20 kWh against a bound of **−2.88**, a raw capture ratio of −4.93.

The spec is silent on the policy run's endpoint, so this is a genuine gap rather than a misreading.

### 3. Fixture 6 needs to say what it is asserted on

Consequence of (2): the invariant holds on drift-corrected figures, not raw ones. Fixture 6 currently
states the bound without qualification, so a correct implementation can fail it.

### 4. §2.4's benchmark box needs a rule for a drift-funded capture ratio

Also consequence of (2). Left unqualified, the ratio renders as "−493 percent" or "2859 percent", or —
worst — as "even a perfectly-informed battery could not have avoided any grid import" printed directly
above a row reading "Your policy 9 kWh". The implementation resolved this by drift-correcting the
ratio for display while leaving §6.11's drift metric untouched; the spec should record the rule rather
than leaving each implementer to rediscover it.

## What was NOT changed, and why

- **The instruction to interpolate** (§6.12) — correct, only its rationale was wrong.
- **§6.11's "report drift rather than net it out"** — correct as stated. The correction in (4) applies
  to a *ratio* whose denominator is already drift-constrained by §6.12's terminal constraint, not to
  the drift metric.
- **The efficiency-split convention, the run table, the DP's complexity figures, both export
  baselines** — all verified correct in implementation.
- **`dp_soc_levels` = 101 / `dp_action_levels` = 41** — the defaults are fine. The implementation
  needed two additions the spec does not mention (snapping a state level onto the starting SoC, and
  appending the exact PV-surplus and household-deficit actions per interval), both recorded in §6.12
  as implementation notes rather than as changes to the defaults.

## Files modified

- `specs/12-metrics-and-benchmarks.md` — §6.12: the interpolation rationale corrected; the terminal
  constraint's asymmetry with the policy run named, with the drift-corrected comparison basis stated;
  two implementation notes added (starting SoC on the grid; representable actions).
- `specs/16-validation-harness.md` — fixture 6: states the basis the bound is asserted on.
- `specs/02-ux-wireframes.md` — §2.4: the capture ratio's presentation rule when the policy's drift is
  materially negative.
- `specs/README.md` — version bumped to 1.3 with a change summary, following the file's own
  convention.
- `specs/19-prototype-experiments.md` — **X13** was premised on the corrected claim, quoting the
  "pessimism bias" wording as evidence that the discretisation is coarse enough for the interpolation
  choice to matter. Rewritten: the measurements taken during implementation partly answer it (with
  interpolation the SoC grid is converged well before 101; the action-grid residual is quantified at
  0.025 kWh at 41 levels), so the open question is now whether 101 is wastefully *high*, and the
  method sweeps downward as well as up. The DP's measured ~2.3 s cost is noted, since a finding that
  the grid can be coarsened now has a directly felt payoff.
- `specs/implementation-progress.md` — a living implementation record, so brought in line with the
  build: a new "What is built" section naming the modules against the spec sections they implement
  and, explicitly, what is NOT built (the whole cost path, epochs, the price bracket, the
  resolution-bias and misalignment diagnostics, CSV ingest and export); `discharge_allow_export`
  moved from *Currently pending* to *Retired* (it shipped as a real checkbox); `chart_soc_price` and
  `chart_energy_flows` added as newly pending, matching `app/features.py`.

## Verification

- Every cross-link and anchor in the 24 spec files checked programmatically. The new
  §6.12 sub-heading anchor resolves exactly as linked from §2.4 and §6.14.
- **Pre-existing link rot noted, not fixed:** 23 anchors were already broken at `HEAD` before this
  task (25 after, the two added following the same established pattern). They point into
  `02-ux-wireframes.md` headings containing circled numerals (`Panel ①`) and similar symbols, where
  the anchor GitHub generates differs from what the links assume. Out of scope for a correctness
  pass, and worth a separate mechanical sweep.
- No stale copy of the corrected claims remains: the only surviving occurrences of "pessimism bias"
  are the two corrections quoting the old wording, both explicitly marked as such.

## Status

Complete. The four findings are applied, plus the two consequential updates (X13, the progress
record) that would otherwise have been left resting on superseded text.
