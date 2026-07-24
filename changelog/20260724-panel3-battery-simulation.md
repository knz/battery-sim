# Panel ③ — real battery simulation and results

## Task specification (user's original prompt)

> can we now add the battery simulation and results to panel 3

**Reading of the scope.** The previous increment
([20260724-panel3-prototype-zero-battery.md](20260724-panel3-prototype-zero-battery.md)) wired panel
③ end-to-end but with charge ≡ discharge ≡ 0, so every savings figure was structurally zero. This
task replaces that placeholder with the actual §6.6–§6.9 simulation: charge/discharge policies, the
battery step function, the A/B/C runs, and the §6.11 metrics — so panel ③'s KPI tiles, energy
breakdown and secondary metrics carry real simulated numbers.

## Context established from the specs + code (pre-plan reading)

- **What exists.** `app/domain/reconcile.py` produces the per-interval grid arrays (imp/exp/pv/
  batt_charge/batt_discharge) and the §6.3 reconstructed `load` over a resolved window.
  `app/results_view.py` turns that into the panel-③ view-model with all battery figures hard-zero.
  `POST /results` re-renders `_panel_results.html` on range change (fragment swap).
- **What does not exist.**
  - No simulation core: §6.6 `charge_request`, §6.7 `discharge_request`, §6.8 `battery_step`,
    §6.9 `simulate` / `simulate_baseline`, the A/B/C run harness, §6.11 metrics.
  - No battery/policy configuration object. `app/config.py` holds only the feature-interest egress
    pair; the appendix-A defaults (`usable_capacity_kwh` 10.0, `min_soc_pct` 10, `max_soc_pct` 100,
    `max_charge_kw`/`max_discharge_kw` 5.0, `roundtrip_efficiency` 0.90, `standby_w` 30,
    `initial_soc_pct` 50, `coupling` ac, `fuse_a` 25 → `max_import_kw` 5.75, `allow_grid_export`
    false) are not represented in code.
  - **Panel ② is still static sample markup** (`_panel_params.html` renders `sample_data`
    literals into unwired inputs) — no form submission, no persistence, no validation.
  - The spot price series (`price_spot`, a REQUIRED slot) is ingested and its avg/min/max are shown,
    but it is not resampled onto the simulation grid — the price bands in §6.6/§6.7 need a per-
    interval `st.spot` array, which `reconcile_grid` does not currently produce.
  - The §6.12 perfect-foresight DP (runs D/E) is not built, so panel ③ still emits no `benchmark`.

## Scope questions and the user's answers

1. **Panel ② wiring** — *included*. The increment wires panel ② for real (form + persistence +
   validation + re-simulation on parameter change), not just the appendix-A defaults. The user asked
   that the work be **organised in phases** and said further instructions would follow.
2. **§6.12 perfect-foresight benchmark** — *the energy DP (run D) is in scope*. Panel ③ gets the
   benchmark bars and the capture ratio, and the `perfect_foresight_saving ≥ policy_saving`
   invariant becomes a real test. The cost DP (run E) stays out (cost simulation is off).
3. **Runs** — *all three A/B/C*, per §6.9, so the breakdown's "Standby consumption" line is an exact
   run difference (`C − B`) rather than an estimate.

So the full increment covers: the simulation core (§6.6–§6.9), the §6.11 metrics, the §6.12 energy
DP, a real battery/policy configuration object with the appendix-A defaults, panel ② wired to it,
and panel ③ rendering real simulated results.

## Working method (user's instruction)

Organise the work in **phases**. For each phase use **sub-agents for implementation and review**,
iterating between them until the review is clean. Minor review items are either addressed
immediately or filed as follow-ups here. Commits are allowed between phases.

## Testing approach (user: "we'll also want adequate testing")

The specs already prescribe the harness: **§6.14 lists 22 numbered fixtures** and opens with "Write
these first — they are cheap, and several of them catch whole classes of error that are otherwise
invisible in plausible-looking output." So the in-scope fixtures LEAD each phase rather than
trailing it. Cost-only and ingest-only fixtures (4, 8–11, 13–15, 18–20, 22) are out of scope.

| Fixture | What it pins | Phase |
|---|---|---|
| 21 | Mixed resolutions — grid stays hourly, `spot` = arithmetic mean of the four quarter-hours | 1 |
| 7 | DST — a window spanning both transitions has 8,760 ± 1 intervals, no duplicates/drops | 1 |
| 1 | Trivial — flat load, flat price, disjoint bands; cycles/throughput analytically computable | 3 |
| 2 | Efficiency — 10 kWh at 90% RTE returns 9.0 kWh AC; loss is 1.0, NOT 0.9 or 1.11 | 3 |
| 3 | Conservation — `Σ(pv+imp+dis) == Σ(load+exp+chg)` for every run, to `CLOSURE_TOL` | 3 |
| 5 | Monotonicity — larger capacity never reduces savings (catches clamping bugs) | 3 |
| 16 | No-PV arbitrage — P2/D2 square wave, exactly one cycle/day, analytic saving | 3 |
| 17 | PV-invariance — all-zero PV series ≡ no PV series; pins "no `has_pv` branch in the core" | 3 |
| 6 | Bound — perfect-foresight ≥ policy saving, within the block, in its own units | 5 |
| 12 | Phase approximation — unsupported topology sets `approximated`, matches the 3-phase case | 6 |

Fixtures 2, 5 and 6 are load-bearing: 2 pins an efficiency-split convention wrong in two distinct
directions with plausible output either way; 5 catches clamping bugs no single-scenario test sees;
6 is described in the spec as catching "most policy and pricing errors".

Beyond the spec fixtures, per phase: price coverage shorter than the meter window, irregular price
series, mean-not-sum (Phase 1); rte bounds, band overlap, SoC-bound derivation, `economic_guard`
forced off (Phase 2); **§7.2 item 1 — the export limit applies to the BASELINE run too**, which the
spec flags as easy to get wrong and requires be asserted, plus SoC never escaping its bounds over a
long run, NaN gaps carrying SoC forward, simultaneous charge/discharge netting (Phase 3);
`saved_pct` denominator being simulated run A rather than observed import, standby ≡ `C − B`,
conversion-loss identity closure (Phase 4); the DP terminal constraint actually binding, and
unconstrained ≥ inheriting (Phase 5); persistence round-trip, validation surfacing, re-simulation on
parameter change (Phase 6).

`CLOSURE_TOL = 1e-6` (§6.14) is introduced in Phase 1 so the conservation fixtures have it from the
start.

**Testability caveat, stated plainly.** Phases 1–5 are pure domain code (arrays in, numbers out, no
I/O, no clock — §5.2), so the fixtures give real coverage. Phase 6 is form wiring and persistence:
route tests cover the round-trip and validation, but the RENDERED UI stays covered only by the
existing smoke test. No browser-level coverage of panel ② is planned unless asked for.

## Phase plan (approved by the user)

1. **Simulation frame** — resample `price_spot` onto the simulation grid (MEAN within interval, not
   a sum — it is a price, unlike energy), carry `dt_hours`, expose a §4.4 `SimulationFrame`-shaped
   object with `pv` always an array (all-zero without PV). Handle price coverage not spanning the
   window. Introduce `CLOSURE_TOL`. Fixtures 21, 7.
2. **Battery config object** — the appendix-A defaults as a real dataclass, `eta_c = eta_d =
   sqrt(rte)` with the DC bonus, derived SoC bounds in kWh, fuse → max import/export, policies
   P1–P3 / D1–D3, bands A–D, `allow_grid_export`. Validation (§7.3 checks 11, 12); `economic_guard`
   forced off (no cost model). Pure data + validation, no persistence yet.
3. **Simulation core (§6.6–§6.9), runs A/B/C** — `charge_request`, `discharge_request`,
   `battery_step`, `simulate`, `simulate_baseline`, run harness. The sequential heart and where the
   subtle bugs live: simultaneous charge/discharge netting, PV-first clamp, SoC headroom scaling,
   connection limits shedding grid charge before curtailing PV, and the export limit applying to the
   baseline too. Run B = C without standby. Fixtures 1, 2, 3, 5, 16, 17.
4. **§6.11 metrics + panel ③ on real results** — `saved_kwh`, `saved_pct` (denominator = simulated
   run A), `efc` on the storage side, conversion loss, self-sufficiency per scenario, SoC drift with
   the 2% warn threshold. Replaces the hard-zeros in `results_view.py`; drops the "no battery
   configured" caveat. A coherent, shippable state: panel ③ shows real numbers on the defaults.
5. **§6.12 energy DP (run D) + benchmark box** — DP over discretised SoC, both export baselines
   (inheriting + unconstrained while `allow_grid_export` is off), capture ratio, and the
   `perfect_foresight ≥ policy` invariant as a real test. Un-guards the template's `benchmark` block.
   Fixture 6.
6. **Panel ② wired** — real form, `POST /params` persistence, validation surfaced (band overlap,
   rte bounds), summary line computed from the actual config, re-simulation feeding panel ③,
   has_pv / no-PV policy gating (§2.3). Fixture 12.
7. **i18n + full-suite pass** — extract/translate new msgids EN/NL, recompile `.mo`, suite green,
   changelog finalised.

Sequencing note: phases 1–5 are a strict chain. Phase 6 depends only on Phase 2's config object and
could in principle run parallel to 3–5, but it touches `results_view.py` and `main.py` (which
phases 4–5 also touch), so it is kept after to avoid conflicts. Phase 4 is a natural stopping point
if a shippable intermediate state is wanted before the DP lands.

Baseline before this work: **133 passed, 2 skipped** (135 collected), measured on the branch head at
the start of this task. Note the previous changelog recorded 127 passed; that figure was stale
relative to this branch, so Phase deltas are measured against 133, not 127.

## Phase 1 — simulation frame (implementation + review)

> Detailed per-decision record: [20260724-simulation-frame-phase1.md](20260724-simulation-frame-phase1.md).
> Summarised here; that file carries the full rationale, the rejected alternatives and the
> fixture arithmetic.

**Built.** New `app/domain/simframe.py`: `CLOSURE_TOL = 1e-6`, a §4.4 `SimulationFrame` dataclass, and
`simulation_frame(dataset, window) -> SimulationFrame | None`. It BUILDS ON `reconcile_grid` rather
than re-deriving the grid, so the data-summary band and the simulation core cannot drift apart on
the energy numbers (asserted directly by a test). New `tests/test_simframe.py` (12 tests). No
existing file modified — `summary_view.py` and `results_view.py` untouched.

Price resampling per §6.2: **mean** when finer or equal to the grid (energy-unweighted, per the
spec's explicit choice), **forward-fill** when coarser or irregular (`held`; a price is "EUR/kWh
valid from" its timestamp, §4.4), **NaN** where uncovered — never 0, since §4.4 notes an all-zero
`spot` would not mean "no prices" but "prices are zero everywhere", making every band comparison
take a definite and wrong branch. Fields deliberately omitted rather than faked: `spot_min`/
`spot_max` (§6.16), `epoch_id` (§6.15), `tariff_zone` (§6.4), `quality` (no producer writes a
grid-reconciled bitfield yet).

**Orchestrator's own verification** (REPL, before reading the review): the mean is a true arithmetic
mean; the ffill boundary takes the price in force AT the interval start (no off-by-one); uncovered
mean-path buckets are NaN; the tz convention matches `reconcile._resample_sum` so price and energy
buckets align.

**Adversarial review verdict: MINOR ISSUES — no arithmetic defect.** It independently confirmed the
mean/ffill/NaN/tz/integration/§4.4 surfaces correct, and found three issues:

1. **`spot_complete` over-claimed on the forward-fill path.** The hold was unbounded, so a year of
   15-minute meters with an hourly price covering only the first 24 h produced a uniformly-stale
   `spot` across all 35,040 intervals with `spot_complete = True` — 99.7% of the dispatch signal
   extrapolated from one point, reported as fully covered. The implementer had flagged the
   asymmetry and defended it as "a property of the input, not a policy choice"; the review correctly
   called that overstated, since bounding the hold to the declared `resolution_s` was available and
   not taken.
2. **Fixture 21's price test was weaker than its docstring claimed.** `[0.10, 0.20, 0.30, 0.40]`
   does discriminate sum/first/last, but median == mean == 0.25 for a symmetric set, and the
   fixture's uniform hourly energy makes an energy-weighted mean identical to the unweighted one —
   so two plausible-but-wrong implementations passed.
3. **A tz docstring stated the convention's safety backwards.** `.replace(tzinfo=None)` is the call
   that shifts for tz-aware non-UTC input (verified: a `+02:00` window lands the index two hours
   off), not `astimezone()`. Pre-existing and shared with `reconcile.py`; latent because every
   current caller passes a UTC window.

**Fixes applied (iteration 1):** bound the hold to one `resolution_s` past the last good point on
the coarse-REGULAR path (NaN beyond), keeping the unbounded hold only for the truly-irregular path
where no interval length exists — and reporting it via a new extrapolated-interval count, with
`spot_complete` redefined to mean "every interval has an OBSERVED price" so a run precondition can
gate on it honestly; strengthen fixture 21 with asymmetric prices and intra-hour energy variation so
median and energy-weighted implementations now fail; correct the tz docstring to state the actual
precondition (correct GIVEN a UTC window, deliberately matching `reconcile._resample_sum`) without
changing behaviour, since diverging from reconcile would be worse than the latent bug.

### Follow-ups deferred from Phase 1 (not blocking)

- **The `.replace(tzinfo=None)` convention is unsafe for non-UTC-aware windows**, in
  `reconcile._resample_sum`, `summary_view._price_stats_in_window` and now `simframe`. Latent: all
  current callers pass UTC. The safe general form is `.astimezone(timezone.utc).replace(tzinfo=None)`.
  Fix app-wide in `reconcile.py` rather than diverging one module.
- **Fixture 21's `series`-block assertions are not tested** — the spec also asks that the price
  series' `reconciliation` read `"averaged"` and the energy series' `"exact"`. `normalize.reconciliation`
  implements this, but fixture 21's test does not tie them together.
- **The DST test (fixture 7) is a regression guard, not a DST repair test.** Its input index is
  already a clean UTC `arange`, so it verifies the pipeline does not corrupt a uniform axis rather
  than that it repairs a DST-shaped input. That is the right scope for this layer (ingest owns
  local→UTC conversion), but the test's framing should say so.
- **The frame's arrays alias `reconcile_grid`'s** (`load`, `pv`, `import_obs`, `export_obs` are the
  same objects, not copies). Harmless today. §6.9 does `st.load = frame.load + standby_kwh`, which
  rebinds rather than mutates; an in-place variant in Phase 3 would silently corrupt the
  data-summary band through the shared object. Carried into the Phase 3 brief as an explicit
  constraint.

**Fixes verified by the orchestrator** (REPL, independently of the agent's report): the stale-hold
hazard is gone — one hourly price over a 6-hour window now covers exactly its own hour and NaNs
thereafter, where it previously held 0.42 across all six. Fixture 21 now discriminates all five
wrong implementations (unweighted mean 0.20 vs sum 0.80, first 0.10, last 0.50, median 0.10,
energy-weighted ≈0.167). Suite: **145 passed, 2 skipped** (+12 over the 133 baseline).

One honest limitation the fix agent flagged and the orchestrator agrees with: the new discrimination
against an energy-weighted mean is somewhat hypothetical, since weighting by the HOURLY energy
replicated across quarters is mathematically identical to unweighted. It rules out an implementation
that reaches for a finer energy series present in the dataset — a real but narrow case. A stronger
version is not available without changing what fixture 21 is.

## Phase 2 — battery/policy configuration object (implementation + review)

> Detailed per-decision record: [20260724-sim-config-phase2.md](20260724-sim-config-phase2.md).

**Built.** New `app/domain/simconfig.py`: four dataclasses (`BatteryConfig`, `GridConfig`,
`PolicyConfig`, `TopologyConfig`) composed into `SimulationConfig`, grouped one-to-one with the
panel-② form boxes so an issue keyed `battery.min_soc_pct` names both the field and the box the user
must open. Flat `@property` accessors (`cfg.eta_c`, `cfg.band_a`, `cfg.max_import_kw`) let the
§6.6–§6.8 core read exactly as the spec pseudocode writes it. `validate() -> ValidationResult` returns
field-keyed `ConfigIssue(field, code, message)` tuples — `code` is a stable machine id so message text
can be translated without breaking tests. Construction never raises: an invalid parameter set must be
representable so Phase 6's form can render the user's bad value back with the error attached.
New `tests/test_simconfig.py` (75 tests). Suite: 220 passed, 2 skipped.

**Orchestrator's own verification** (REPL): the efficiency split is exactly right — 10 kWh AC in →
9.48683298 stored → 9.0 out, loss precisely 1.0 kWh, which is what §6.14 fixture 2 will demand in
Phase 3. Fuse derivation gives 5.75 kW (1×25 A) and 17.3 kW (3×25 A), matching appendix A. Forced
invariants hold on the CONSTRUCTOR path (`SimulationConfig(simulate_cost=False,
policy=PolicyConfig(economic_guard=True))` → False; `pv_coupling` → None without PV). Offerability is
correctly separate from dispatch (P1/P3 not offered without PV, P2 is).

### Defect found before review: derived values go stale on mutation

The derived quantities are cached `init=False` fields computed once in `__post_init__`, with no
invalidation. Mutating the config after construction leaves them stale, and nothing surfaces it:

    c = SimulationConfig()          # cap 10.0 → soc_max_kwh 10.0, eta_c sqrt(0.90)=0.948683
    c.battery.usable_capacity_kwh = 20.0
    c.battery.roundtrip_efficiency = 0.80
    c.soc_max_kwh   # → 10.0   (should be 20.0)
    c.eta_c         # → 0.948683 (should be sqrt(0.80)=0.894427)
    c.validate()    # → blocking False, ZERO issues

So a battery the user configured as 20 kWh would silently simulate as 10 kWh — a wrong headline
figure with no error anywhere. The same applies to `fuse_a` → `max_import_kw`. The only re-derivation
path is a private `_derive()`; `validate()` reports the stale object as perfectly valid.

The same bug class, less severe, affects the forced invariants: `economic_guard` is forced off in
`__post_init__` only, so `cfg.policy.economic_guard = True` sticks post-construction and `validate()`
does not flag it — while §6.7 requires it FORCED off, not merely defaulted off, because it reads
`p_export_net`, a cost-model output that does not exist in an energy-only run.

Neither is theoretical: **Phase 6 binds a mutable form to exactly this object**, so field-by-field
mutation is the intended usage. Fix dispatched with the review's assessment (options: frozen
dataclasses + `replace()`, properties over stored derived fields, or re-deriving inside `validate()`).

### Adversarial review verdict: DEFECT FOUND

The review confirmed the stale-derived-values defect independently (with a sharper case: `fuse_a=80,
phases=3` still reporting a 5.75 kW cap instead of 55.2 kW) and found four more:

- **D2 aliasing.** `_force_invariants` mutated the sub-objects it was handed, so passing one
  `BatteryConfig` into two `SimulationConfig`s let the second silently rewrite the first's `coupling`.
  Realistic in Phase 6, where cloning a config or comparing with/without PV reuses a group.
- **D3 construction raises**, contradicting the module's own stated contract ("construction NEVER
  raises"). `Decimal(str(None))` throws — and an empty form field arriving as `None` is precisely the
  case that contract was written for.
- **D4 the connection cap was rounded before use as a physical limit**, giving the simulated house up
  to 50 W of headroom it does not have (3×25 A → 17.3 vs an exact 17.25). Immaterial to annual kWh,
  but it baked a formatting decision into the physics.
- **D5 wrong field key** on the import-override error (keyed to `grid.fuse_a`, which was fine), so
  Phase 6's inline rendering would mark the wrong input invalid.

Confirmed correct by the review: all 19 appendix-A defaults, the efficiency split, the
check-11-blocks / check-12-warns discipline, and the no-PV dispatch invariance (checked field by
field). On test quality it was usefully blunt — two tests asserted the implementation's own formula
rather than a pinned number (`sqrt(r)*sqrt(r) == r` holds for any implementation using the same
expression twice), and **no test covered post-construction mutation at all**, which is why 75 tests
missed the highest-severity defect.

### Fixes applied (iteration 1) — option (b), chosen over freezing or `__setattr__`

Every cached `init=False` derived field was **replaced by a `@property`**, so nothing can go stale;
`_derive()` no longer exists. Freezing the dataclasses (the strongest guarantee) was rejected because
Phase 6 needs the mutable binding model, and `__setattr__` hooks were rejected as magic in a module
whose value is being plain data. The forced invariants now hold at three points: read-path properties
(`economic_guard`, `coupling`, `pv_coupling`) so a consumer that never calls `validate()` still cannot
observe a forbidden value; `__post_init__`; and re-run at the top of `validate()`. The raw user choice
stays stored, so re-enabling cost simulation restores it (appendix A is explicit that cost-only params
are retained, not reset). Sub-configs are defensively copied (D2). Construction genuinely never raises
and reports one blocking, field-keyed issue instead (D3). The cap is exact for computation with a
separate `*_display` helper carrying the `ROUND_HALF_UP` + magnitude-conditional rule (D4). The
override error keys to the override field (D5).

**Orchestrator verification** (REPL): all five confirmed fixed — mutation now tracks
(20 kWh → `soc_max_kwh` 20.0; RTE 0.64 → `eta_c` 0.8; 3×80 A → 55.2 kW); `economic_guard` reads False
without `validate()` while retaining the raw choice; a shared sub-config no longer leaks between
owners; `None`/`True`/`nan`/`"3"` all survive construction with exactly one blocking field; the cap is
exact 17.25 for computation and 17.3 for display, with 3×16 A correctly rounding DOWN (11.04 → 11.0).
Suite: **271 passed, 2 skipped** (+51; `test_simconfig.py` 75 → 126).

Note: one claim in the orchestrator's fix brief was wrong and the agent corrected it rather than
repeating it — §6.9's pseudocode does NOT hoist `cfg.*` into locals; it reads them directly inside
`battery_step` per interval. The don't-re-cache comment was written as a conditional
("if that ever measures as hot, the caller should hoist") instead of citing the spec.

### Phase 2 follow-ups (deferred, not blocking)

- **`_finite()` rejects `str`**, so `GridConfig(phases="3")` blocks rather than coercing. Defensible
  (coercion belongs to the form layer) but the opposite choice is equally defensible; revisit when
  Phase 6's form binding exists and shows which is less friction.
- **The `*_display` helpers have no consumer yet.** Phase 6's panel-② formatter is their intended
  caller; until it exists, the display-precision rule is inferred and untested against real UI.
- **The display-precision rule (2 dp below 10 kW, 1 dp at/above) is inferred from two published
  figures**, not specified. 230 V likewise appears nowhere in `specs/` and is pinned by the same two
  data points.
- §6.6's flat sentence "`charge_policy` is P2" without PV was read as describing what the UI OFFERS,
  since the same paragraph insists the code needs no `has_pv` branch. `charge_policy` is therefore not
  coerced; offerability is exposed separately.

## Status

**Phase 1 complete** — implemented, adversarially reviewed, fixes applied and verified, committed
(`9f639d2`).
**Phase 2 complete** — implemented, adversarially reviewed (DEFECT FOUND), all five defects fixed and
verified. Next: Phase 3 (the simulation core, §6.6–§6.9, runs A/B/C).
