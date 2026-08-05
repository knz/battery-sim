# Phase 5 — §6.12 perfect-foresight ENERGY benchmark (run D) and panel ③'s benchmark box

## Task specification

Implement §6.12's perfect-foresight benchmark for the ENERGY objective only (run D,
minimising kWh of grid import). The cost DP (run E) is out of scope — `simulate_cost` is
false throughout this increment.

Scope as given:

1. A DP module (`app/domain/benchmark.py`) implementing §6.12's `perfect_foresight`:
   discretised SoC state, signed AC-power actions, terminal constraint, linear
   interpolation of `V`, vectorised backward pass, forward roll of the policy.
2. Both export baselines: **inheriting** (primary) and **unconstrained**. Only the
   inheriting DP runs when `allow_grid_export` is on, and the unconstrained fields are then
   null.
3. Metrics + view-model: `perfect_foresight_saved_kwh = A.imp − D.imp`, the capture ratio,
   and the `benchmark` key panel ③'s template already guards on.
4. Measure the DP's cost on the real dataset and report before building any cache.

## High-level decisions

- **`dp_soc_levels` / `dp_action_levels` / `benchmark_divergence_display_threshold` added to
  `SimulationConfig`** as plain fields on a new `BenchmarkConfig` group? — No. Decided to add
  the two DP grid sizes as fields on `SimulationConfig` itself (flat), because appendix A
  lists them as run-wide tuning parameters, not as a panel-② form box, and the four existing
  groups mirror form boxes one-to-one. The display threshold is a VIEW constant and lives in
  `app/results_view.py`, not in the config — it changes no number the domain computes.
- **The DP re-derives the step function rather than calling `battery_step`.** `battery_step`
  is scalar and sequential; the DP needs the transition vectorised over
  (n_soc × n_actions). The DP's transition is written to obey the same limits in the same
  order (rated power, SoC window, connection caps, standby in the load) and is pinned against
  `battery_step` by a test that drives both over the same actions.
- **Actions are signed AC energies, and the DP's action set is the physically feasible one.**
  Infeasible (soc_next outside the window) transitions get +INF, per the pseudocode's
  `tot[~feasible(soc_next, cfg)] = +INF`.
- **Gap intervals are skipped by the DP exactly as run C skips them** — no energy moves, SoC
  carries forward, import is NaN. Otherwise the bound would be computed over a different
  interval set from the policy run and fixture 6 would compare unlike things.

## Files modified

- `app/domain/simconfig.py` — added `dp_soc_levels` (101) and `dp_action_levels` (41) fields
  with appendix-A defaults and validation.
- `app/domain/benchmark.py` — NEW. The §6.12 DP, both baselines, and the benchmark metrics.
- `app/results_view.py` — emits the `benchmark` key; the conditional fourth row and gloss.
- `tests/test_benchmark.py` — NEW. Fixture 6, the baseline ordering, the terminal
  constraint, interpolation, like-for-like limits, hand-computed tiny scenarios.
- `tests/test_results_view.py` — the benchmark block's presence and the conditional row.

## Obstacles and solutions

Four issues, all found by measurement rather than by reading, and each one made the DP fail to be
an upper bound at all.

1. **The starting SoC was not on the state grid.** §6.12's `linspace(soc_min, soc_max, n_soc)`
   almost never contains `initial_soc_kwh`, and the terminal constraint is stated against that
   value. Every level below it was infeasible and the nearest level above was strictly more charged
   than the run starts, so the DP had to charge before it could act and returned 123.05 kWh against
   122.80 for standing still. → `_DpLimits.of` moves the nearest level onto the starting SoC (level
   count and sort order preserved).

2. **The forward pass snapped the policy lookup to a grid level.** A second discretisation on top
   of the one `V` interpolation removes, worst exactly at the terminal boundary. → `_roll_forward`
   re-solves the one-step problem at the true continuous SoC against a stored per-interval `V`
   (~7 MB at 8,760 × 101). A few percent of the backward pass's cost.

3. **The policies dispatch on continuous quantities the 41-action grid cannot represent.** The PV
   surplus and the household deficit; the DP came out ~0.3 kWh (≈3 percent) below a P1/D1 policy.
   → `_interval_actions` appends those two exact points per interval.

4. **The action grid still cannot represent "return exactly to the starting SoC".** That action
   depends on the current SoC and cannot live in a row shared by every state without breaking the
   broadcast. Residual measured at **0.025 kWh**, never exceeded across 216 configurations, and it
   shrinks with `dp_action_levels`. It makes the bound conservative, which is the safe direction.
   → Documented in `_interval_actions`; `tests/test_benchmark._DP_SLACK_KWH` is 0.03.

## Two spec findings, flagged rather than resolved silently

**§6.12's terminal constraint is asymmetric with the policy run, and fixture 6 can fail on the raw
numbers because of it.** The DP must end at or above its starting SoC; nothing imposes the same on
run C, and §6.11 deliberately reports the drift rather than netting it out. A D1 policy that empties
a battery books import avoided that it funded from its opening charge. Measured on a 48-interval
square-wave fixture: policy +0.88 kWh against a bound of −1.69, with the policy's drift at −4.0.
Drift-corrected (`saved + soc_delta × eta_d`) the ordering is restored: −3.12 against −1.69. The
fixture is therefore asserted on the drift-corrected figures, with the literal form asserted
separately on windows where the policy does not liquidate. The spec says nothing about the policy
run's endpoint; this is a real gap, not an implementation choice.

**§6.12 says nearest-snapping causes "a systematic pessimism bias of several percent"; measured, it
is optimistic and far larger.** On a 96-interval PV fixture, snapping gives 17.41 kWh against
interpolation's 27.59 at 21 SoC levels, and converges UPWARD as the grid refines (9.41 at 11 levels,
27.13 at 401) while interpolation is stable at ~27.56 from 11 levels on. Snapping rounds a landing
SoC to the nearest level including upward, which credits the battery with energy it does not have —
a leak compounding over every transition — and its figure (17.41) sits below the realised dispatch's
27.64, i.e. it is unattainable and bounds nothing. §6.12's conclusion is right; its stated reason
appears to understate the problem. The tests assert what is demonstrable rather than the spec's
wording.

## Measured cost, and the recommendation

On the real dataset (8,760 hourly intervals, appendix A's 101 × 41 grids):

| | |
|---|---|
| runs A/B/C | 0.12 s |
| one DP | ~2.1 s |
| both DPs (export off, the default) | ~4.5 s |
| full `GET /` | **4.98 s**, against ~0.13 s before |

The benchmark is ~97 percent of the request. That is a real regression in page latency and it is
reported rather than papered over. No caching layer was built — the task was explicit that the
measurement comes first, and correctness mattered more than speed. The options, none chosen:

- **Cache keyed on (dataset id, window, config)**. Fits the shape of the problem — the panel-③
  range picker re-posts the same window repeatedly — and Phase 6 will make the config a real cache
  key. Costs an invalidation story.
- **Compute the box lazily on demand** (a separate fetch after the panel renders). Keeps the first
  paint fast and matches the existing fragment-swap machinery. Costs a second round trip and a
  loading state.
- **Skip the unconstrained DP on the energy objective.** Measured: with export off, the two
  dispatches are **bit-identical** on the real dataset — exporting battery energy earns revenue but
  avoids no grid import, so the export permission cannot change an import-minimising dispatch.
  Halves the cost for free, but it is an argument, not a proof, and §6.12 asks for both baselines.
  Worth establishing properly (it is close to what experiment X10 is for) before acting on it.
- **A coarser default grid.** Cheapest to do, and the one that trades away accuracy — the
  discretisation residuals above are already the binding limit on the bound's tightness.

My lean is the lazy-fetch option, because it leaves the numbers untouched and the machinery already
exists; but the cache is the better fit once Phase 6 gives the config a stable identity. Not a
decision to take here.

## Real-dataset figures

    baseline import (run A)      3,864 kWh
    policy saved (A − C)           341 kWh
    perfect-foresight bound        603 kWh
    capture ratio                 0.567
    unconstrained bound            603 kWh (identical — see above)
    DP SoC 5.00 → 9.47 (terminal constraint satisfied and non-trivially so)

Sanity: the ratio is below 1, as fixture 6 requires. 0.57 on a fixed-band P3/D1 policy is consistent
with §6.7's remark that fixed bands approximate a daily-moving price signal poorly — a figure near
1.0 would have been the suspicious one. The "…if export allowed" row does not render, correctly:
the two capture ratios are identical, so the divergence is 0 and §2.4's threshold omits the row.

## Current status

Complete. `uv run python -m pytest tests/ -q` → **364 passed, 2 skipped** (from 328/2). One existing
test changed: `test_results_reports_a_real_simulated_saving` asserted `"benchmark" not in r`, which
Phase 5 makes false; it now asserts the key is present and structurally sound.

Not done, and deliberately: run E / the cost DP, any euro figure, and any caching layer.

---

# Phase 5 review round — verdict, the presentation defect, and the lazy-load

## Review verdict

An adversarial review of the phase-5 work returned **DEFECT FOUND — one PRESENTATION defect**.
The DP itself was verified sound and is unchanged by this round:

- a 16,000-pair fuzz of `_transition` against `battery_step` found **zero divergence**;
- `_DP_SLACK_KWH` held up under mutation attack;
- the terminal constraint binds;
- both hand fixtures recompute correctly.

No DP arithmetic, no `_transition`, no action grid and no `_DP_SLACK_KWH` were touched.

## The defect: the capture ratio renders nonsense when the policy liquidates its opening charge

`_capture_ratio` guards only its DENOMINATOR (`abs(bound_saved) <= DIV_GUARD_EPS`); nothing
guards the ratio's sign or magnitude, and `_benchmark_block` printed `round(100 * ratio)`
unconditionally. The §6.12 terminal constraint is asymmetric — the DP must end at or above its
starting SoC, the policy run need not — so a policy that liquidates its opening charge books a
saving the DP is forbidden to book, and the ratio goes to places a percentage cannot mean.

Reproduced shapes:

| configuration | ratio | printed |
|---|---|---|
| 20 kWh, 100→10% SoC, 96×(1.0 load / 0.2 PV) | −4.93 | "captures −493 percent" |
| (reviewer variant) | 28.59 | "captures 2859 percent" |
| (reviewer variant) | −1.64 | "captures −164 percent" |
| bound ≈ 0, policy saving positive | None | "even a perfectly-informed battery could not have avoided any grid import" printed directly above a visible row reading "Your policy 9 kWh" |

The last is the worst: a gloss that contradicts a row the reader can see.

### The fix, and why it is in the VIEW rather than in the metric

`EnergyBenchmark.capture_ratio` stays UNCLAMPED. Its docstring already says a value > 1 is a
detectable fault and clamping would turn it into a plausible number; a test consumer wants to see
the fault. The defect is that the VIEW printed it as fact. So the whole fix is in
`app/results_view._benchmark_block`.

**Chosen: state the ratio on DRIFT-CORRECTED figures when the policy's drift is materially
negative, rather than suppressing it.** Accepted the reviewer's assessment that this does not
violate §6.11's "report drift rather than net it out": §6.11's rule governs the drift METRIC —
which is still reported in full, unnetted, by the existing SoC-drift caveat — not a RATIO whose
denominator is drift-constrained by the §6.12 terminal constraint. Comparing a drift-funded
numerator against a drift-neutral denominator is the actual category error; correcting the
numerator to the same basis is what makes the ratio mean anything. The correction is
`saved + soc_delta × eta_d` — the residual valued at what the inverter could still deliver — the
same `_saving_drift_corrected` basis `tests/test_benchmark.py` already asserts fixture 6 on. The
box says so in words, and the ratio is labelled as drift-corrected rather than presented bare.

**"Materially negative" reuses `SOC_DRIFT_WARN_FRAC` (2%) from `app/domain/metrics.py`** rather
than inventing a second threshold. The gate is `soc_delta < 0` AND
`|soc_delta| > SOC_DRIFT_WARN_FRAC × |policy_saved|` — the same test §6.11 uses to decide the
drift is worth surfacing, with the sign condition added because only a NEGATIVE drift funds a
saving out of opening charge. A positive drift makes the policy look worse, not better, so it
needs no ratio intervention. With no saving to be relative to, any drift above `DIV_GUARD_EPS`
counts, matching `metrics.soc_drift_significant`'s own degenerate branch.

Four presentation shapes are now distinguished, each with its own gloss:

1. **normal** — drift immaterial, `0 ≤ ratio ≤ 1`: renders as a plain percentage, as before.
2. **drift-funded** — materially negative drift: renders the DRIFT-CORRECTED ratio, labelled,
   with a sentence saying part of the raw saving was opening charge. If the corrected ratio is
   itself out of range the box falls back to shape 4.
3. **bound ≈ 0 (`ratio is None`)** — the gloss now BRANCHES on whether the policy saving is
   itself ≈ 0. When it is, the old "could not have avoided any grid import" wording stands. When
   the policy shows a positive saving against a ~0 bound, that wording would contradict the row,
   so the box says instead that the policy's apparent saving is not something a perfectly-informed
   battery could have reproduced under the terminal constraint, and points at the drift.
4. **ratio > 1** — never printed as a percentage. Either drift-funded (shape 2's explanation) or,
   with no drift to explain it, a fault: the box says the comparison did not come out usable over
   this period and states no number.

`EnergyBenchmark` gained one field, `policy_soc_delta_kwh` (run C's `soc_end − soc_start`), so the
view can see the drift at all. It is taken from the run C `Flows` already passed to
`energy_benchmark` — no second computation, and it cannot drift from `metrics.soc_delta_kwh`.

## The lazy-load (user-approved)

`GET /` measured **4.72 s** with the DP inline against **0.13 s** without it. Cost is linear in
window length (1 week 0.04 s, 30 days 0.19 s, 3 months 0.57 s, 1 year 2.29 s per DP), so only long
windows are slow. **The user chose lazy-loading**; no caching layer was built (explicitly not
chosen).

Shape:

- `results_from(dataset, window, *, with_benchmark=False)` — the DP runs only when asked. `GET /`
  and `POST /results` do not ask, so panel ③ paints at ~0.13 s from the §6.11 figures alone.
- **`POST /results/benchmark`** — NEW route, same window request shape as `POST /results`
  (`{"period"}` XOR `{"start","end"}`), same clean 4xx/409 error conditions, never a 500. Returns
  the rendered benchmark card only, from a new `_benchmark_box.html` partial.
- `_panel_results.html` renders `{% if results.benchmark %}` … `{% else %}` a placeholder
  `#benchmark-slot` div carrying a `⟳ …` loading state that matches the panel's existing
  "⟳ recalculating…" idiom, plus `data-benchmark-body` carrying the window request as JSON so the
  fetcher knows which window to ask for. The `{% if %}` guard still works for the sample view-model
  (`sample_data.py` still supplies a static `benchmark`), which is what the sample page and the
  smoke test see.
- **The listener lives in `index.html`**, never in the swapped fragment — a swapped-in `<script>`
  re-inserts but does not re-execute (documented in
  `changelog/20260724-panel3-prototype-zero-battery.md`). `window.loadBenchmark()` is called on
  initial load and again from `recompute()`'s success path, so the box re-fires after every
  panel-③ range-change swap. It reads the window off the freshly-swapped `#benchmark-slot`, so it
  needs no state of its own.
- **Graceful degradation**: a failed or timed-out request replaces the loading state with a short
  "could not be computed" line. The rest of panel ③ is untouched — the box is the only node the
  fetch writes to. A 20 s `AbortController` timeout bounds the wait.

## FIX 3 — the `_transition` vs `battery_step` fixture exercised no connection-limit branch

`test_dp_transition_agrees_with_battery_step` claims to manage "the one real risk in this module",
but its config gave `max_import_kw = max_export_kw = 5.75`, so across all 140 combinations
**neither connection-limit branch was ever entered** (instrumented: headroom 16 hits,
available-energy 24 hits, import cap 0, export cap 0). The fixture now runs the same grid under a
SECOND config with a binding fuse (`max_import_kw = 2.0`) and a tight export cap
(`max_export_kw = 0.5`), so all four clamp paths are exercised. About test power, not a suspected
bug — the reviewer's 16,000-pair fuzz found zero mismatches.

## FIX 4 — the SoC-grid snap could drop an endpoint at tiny `dp_soc_levels`

`_DpLimits.of` moves the nearest level onto the starting SoC. At `dp_soc_levels = 2` with
`initial_soc = 5.0` over `[1, 10]`, the nearest level IS `soc_min`, so the move deleted `soc_min`
from the grid — falsifying `perfect_foresight`'s comment that "the ends of `soc_levels` ARE the
window's ends", which `np.interp`'s clamping behaviour relies on. `validate()` permits
`dp_soc_levels >= 2`, so it is reachable by configuration; nothing in production sets it.

Fixed by **refusing to move an endpoint level**: the snap now searches only the INTERIOR levels
and no-ops when there is no interior level to move (`n_soc == 2`) or when the starting SoC is
itself an endpoint. Chosen over raising the validation floor because the floor would have to be 3
to fix only the `n_soc == 2` case while leaving the general "nearest is an endpoint" case — a
starting SoC very close to `soc_min` at any grid size — unfixed.

## Spec findings (prose corrections for a later editing pass — NOT code changes)

**(A) §6.12's terminal constraint is asymmetric with the policy run, and the spec does not address
it.** The DP must finish at or above `initial_soc_kwh`; nothing holds the policy run to the same
discipline, and §6.11 deliberately does not net the drift out. So fixture 6's literal form —
`perfect_foresight_saving ≥ policy_saving` — compares a drift-funded figure against a
drift-neutral one and can fail on correctly-built code. It is asserted here on the drift-corrected
basis. The spec should either state the correction, or state that the policy run is likewise held
to its starting SoC, or say explicitly that the comparison is raw and fixture 6 is expected to
fail on liquidating windows. This is also the root cause of the presentation defect above.

**(B) §6.12's stated reason for interpolating is measurably wrong in BOTH direction and
magnitude.** §6.12 says interpolation of `V` "avoids a systematic pessimism bias of several
percent". Independently reproduced at six grid sizes: nearest-snapping is **OPTIMISTIC**, not
pessimistic, and converges UPWARD — at 21 levels snapping gives 17.41 against interpolation's
27.59 and the realised dispatch's 27.64. A figure BELOW what the dispatch actually achieved bounds
nothing. The mechanism is that snapping rounds `soc_next` to the nearest level in both directions,
including upward, crediting the battery with energy it does not have — a leak that compounds over
every transition. The spec's CONCLUSION (interpolate) is right and unaffected. Its stated REASON
is backwards, and left uncorrected it would lead a future reader to treat snapping as the safe
conservative option, which is exactly wrong.

Both are corrections to spec PROSE for a later editing pass. No code depends on either wording.
