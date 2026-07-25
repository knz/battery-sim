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

### Cross-phase follow-up: the `newstyle=True` gettext trap (found in Phase 4)

`app/i18n.py:90` — `install_gettext_translations(..., newstyle=True)` %-formats the result of `_()`,
so a literal `%` in any dynamic translated string is treated as a format placeholder: it is silently
eaten before a letter, and RAISES `ValueError` before a non-ASCII character (a 500 on a page a user is
looking at). Not currently triggered — KPI values bypass `_()` by template design and the Phase 4
caveats were worded around it — but it is a live trap for the next dynamic string carrying a
percentage. Fix at the root (escape `%` → `%%` before translation, or `newstyle=False`) as its own
task, since it touches i18n and every catalog. Related to the pre-existing "dynamic caveat strings
render in English under NL" follow-up from the zero-battery increment: both are consequences of
passing runtime-built strings through `_()` at all.

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

## Phase 3 — the simulation core, §6.6–§6.9, runs A/B/C

> Detailed per-decision record: [20260725-simulation-core-phase3.md](20260725-simulation-core-phase3.md).

**Built.** New `app/domain/simulate.py`: `charge_request` (§6.6), `discharge_request` + band-overlap
netting (§6.7), `battery_step` with all seven numbered steps (§6.8), the sequential `simulate` loop
and vectorised `simulate_baseline` (§6.9), a struct-of-arrays `Flows` container, and a `run_all`
harness for runs A/B/C. Run B exists solely so `standby_kwh = C.imp − B.imp` is an exact run
difference rather than `standby_w × hours` — the two differ whenever standby was served by PV or the
battery. Runs D/E are absent, not stubbed. New `tests/test_simulate.py` (25 tests).

### Two defects in the SPEC's own §6.8 pseudocode

Both reachable from `initial_soc_pct` outside `[min, max]` — which §7.3 check 11 **warns about but
does not block**, so it is a live runtime input, and Phase 2's own warning text already promises the
value "will be clamped at the first step":

- **Nothing clamps a below-floor starting SoC.** Step 3 charges only toward `soc_max` and step 4
  discharges only toward `soc_min`, so an out-of-window start stays out of window and trips step 7's
  assertion on interval 0 — a crash on a configuration the spec permits.
- **Step 4's `(soc − soc_min) × eta_d` goes negative** for the same input, so `withdrawn` goes
  negative and the arithmetic runs backwards: a *discharge* request *charges* the battery.

Confirmed independently by the orchestrator by hand before the review, and by the review afterwards.
Fixed by clamping once in `simulate` before the loop (the only placement §6.8's steps allow) and
flooring step 4's available energy at 0 as an independent guard.

The review established that recording the CLAMPED value in `soc_start` is **required, not merely
defensible**: with `initial_soc_pct = 5%` under a 20% floor, §6.11's
`conversion_loss = charge_ac − discharge_ac − (soc_end − soc_start)` closes at exactly 0.0 with the
clamped value, and gives a physically impossible −1.5 with the raw one.

### Conservation identity — and its limit

The naive §6.14 form does not close. What is asserted:

    pv + imp + dis_home + dis_grid  ==  load + exp + chg_pv + chg_grid + curtailed

`curtailed` is the added term (PV that reached the AC bus and was neither exported, consumed nor
stored); `load` must be the standby-inclusive load in runs B/C; and NO SoC term appears, because
`chg_*`/`dis_*` are AC-side so conversion losses already sit outside the balance.

**The review found this identity is weaker than it looks, which neither the orchestrator nor the
implementer had noticed:** it is §6.8 step 5 algebraically rearranged, so it holds BY CONSTRUCTION
whenever the connection caps do not bind, and cannot catch a defect confined to step 5's inputs.
Demonstrated: mutating `withdrawn = dis_ac` (dropping `/eta_d` — a genuinely energy-creating defect)
leaves conservation closing perfectly, and is caught only by the hand-computed fixtures 1, 2 and 16.
Its real value is on the shed and curtailment paths (steps 6–7), where the rearrangement no longer
holds trivially. **Phase 4 must not treat conservation as a general safety net.**

### Fixture 16 returns a NEGATIVE saving, and that is correct

A no-PV arbitrage battery costs **−1.774 kWh/day** in an energy-only run, decomposing exactly into
standby (0.030 × 24 = 0.720) plus round-trip loss (10 × (1/√0.9 − √0.9) = 1.054). Verified by the
orchestrator by hand and by the review, which also confirmed the battery genuinely performs exactly
one cycle per day (SoC saturates at 10.0 for hours 2–11, empties at hour 21) and `efc == days` to
1e-15. This is §7.2 item 9: without PV the battery's value lies entirely in the price *spread*, a
euro quantity, so a kWh-only measurement of an arbitrage config captures only its costs. The spec
requires reporting it rather than hiding it.

### Adversarial review verdict: CLEAN — no correctness defects

After hand-computed scenarios, compound-clamp attacks and a 120-config randomised fuzz: no flow array
ever went negative; `imp`/`exp` were never simultaneously positive; SoC never escaped its window;
float drift over 8,760 intervals of strict daily cycling was exactly 0.0 (the clamps reset error each
cycle); the loop is linear (0.059 s for 8,760 intervals, well inside the §6.9 target). Verified
correct: shed order and arithmetic on both caps, the DC bonus applying to the PV path only, the
headroom clamp being in storage units, D2/D3 serving the house first, single-application netting,
§7.2 item 1 (the baseline curtails identically in kind to run C), no in-place mutation of the shared
frame arrays, and B/C differing only in standby.

The implementer's claim that it had mutation-tested its own suite was **spot-checked rather than
taken at face value**: the review re-applied four mutations in a scratch copy and reproduced the
reported failure counts exactly (2, 1, 6), plus one of its own. No test asserts the implementation
against itself — `_ETA` is a hard literal with a comment explaining that `math.sqrt(0.9)` would be
circular, and fixture 2 pins the intermediate stored value precisely because an output-only test
passes for the wrong loss convention.

### Fixes applied (iteration 1) — both minor

Three fixture-16 tests were silently hitting the appendix-A default 1×25 A / 5.75 kW connection cap
(the import shed fired 20× in one, 8× in each sibling), throttling charging from 5.0 to 4.72 kWh/h.
Results were bit-identical — the 12-hour low-price window has enough slack that the battery still
fills, one hour later — but the docstrings' analytic derivation reasons about a 5 kW charge rate the
run never achieved. Overridden explicitly. And the fixture-3 tests gained a comment stating what the
conservation identity does and does not cover, so a Phase 4 implementer reading it understands the
limit.

**Worth carrying forward:** the shipped default connection (1×25 A → 5.75 kW) is tight enough to shed
a 5 kW charge request against a ~1 kW household load. That is appendix A's default, not a bug, but it
will shape Phase 4's headline numbers on a default configuration.

## Phase 4 — §6.11 metrics + panel ③ on real results

> Detailed per-decision record: [20260725-metrics-and-real-results-phase4.md](20260725-metrics-and-real-results-phase4.md).

**Built.** New `app/domain/metrics.py` (`EnergyMetrics`, `SOC_DRIFT_WARN_FRAC`, `energy_metrics`) —
pure: runs + frame + config in, bare numbers out. `app/results_view.py` rewired to build a
`SimulationFrame`, construct a `SimulationConfig` (appendix-A defaults until Phase 6 wires the form),
call `run_all`, compute metrics and populate the tiles, breakdown, secondary metrics and caveats. The
"No battery is configured yet" caveat is deleted — it is no longer true. New `tests/test_metrics.py`
(20 hand-computed fixtures).

**Every metric has its own hand-computed fixture**, per the Phase 3 review's finding that the
conservation identity cannot catch metric-arithmetic defects. The core scenario (4 hours, load 1/1/3/3,
PV 5/5/0/0, 10 kWh battery, P1/D1) is worked out on paper in the test module header and each figure
asserted as a literal.

### Panel ③ now shows real numbers

Over the persisted dataset (8,760 hourly intervals, 2025-07-24 → 2026-07-24), on the default battery:

    GRID IMPORT SAVED        341 kWh   +8.8 %
    SELF-SUFFICIENCY         21% → 33%   +12 pp
    EQUIVALENT FULL CYCLES   138   0.38 / day   1,311 kWh throughput

    Grid import, no battery      3,864 kWh      Charged into the battery   1,462 kWh
    Grid import, with battery    3,523 kWh      Discharged from battery    1,311 kWh
    Grid import avoided            341 kWh      Conversion losses            146 kWh
                                                Standby consumption          195 kWh
    Self-consumption ratio  34% → 60%    Grid export  2,030 → 1,275 kWh

Orchestrator-verified as internally consistent: 3,864 − 3,523 = 341; charged 1,462 − discharged 1,311
= 151 ≈ the 146 kWh conversion loss plus a small SoC change.

**Simulation cost: 0.130 s per request** (frame build 0.004, `run_all` 0.115). No caching — the cost
is acceptable, and a cache key over config + window + dataset id raises a staleness question the spec
has not framed and Phase 6 would change. Revisit when Phase 5's DP (seconds, per §6.12) lands on the
same request path; that is a different order of magnitude.

### Pre-existing i18n defect found by looking at the live page

`app/i18n.py:90` installs gettext with `newstyle=True`, which applies %-formatting to the RESULT of
`_()`. Any dynamic string passed through `_()` therefore has its literal `%` interpreted as a format
placeholder:

    "90% round-trip efficiency"  ->  "90{}ound-trip efficiency"      (character eaten)
    "21% → 33%"                  ->  ValueError: unsupported format character '→'   (would 500)

**Orchestrator assessment of the blast radius** (the agent reported the eaten character; the raising
case is worse and was found in follow-up): the exposure is bounded to `_()`-wrapped strings. KPI values
and breakdown figures render as `{{ k.value }}` / `{{ row.value }}` WITHOUT `_()`, so the live page is
correct and `"21% → 33%"` never reaches gettext — safe by template design, not by luck in the string.
Today the only `_()`-wrapped dynamic strings are the caveats, and both live caveats were verified to
render safely after the agent worded them without `%`.

That workaround is right for this phase but leaves a trap: the next person to write a caveat
containing a percentage gets a mangled string, or a 500 if a non-ASCII character follows the `%`.
Filed as a follow-up below; the root fix (escaping `%` before translation, or `newstyle=False`) touches
i18n and every catalog and does not belong in this phase.

### Adversarial review verdict: DEFECT FOUND — observed and simulated figures mixed in one comparison

The §6.11 arithmetic in `metrics.py` was verified correct on every point (saved_pct's denominator,
storage-side efc, null-not-zero self-consumption, the three ambiguity resolutions, SoC drift's
`abs()` on both sides, gap masking, standby as the exact run difference). **All defects were in the
PRESENTATION layer** — `results_view.py` mixing information sets:

- **The SELF-SUFFICIENCY tile compared observed against simulated.** Left half was
  `1 − rec.imp_total/rec.load_total` (the METER); right half was `metrics.self_sufficiency_battery`
  (SIMULATED). Orchestrator-verified on the real dataset: observed import 3,924.49 kWh vs run A's
  3,864.17 — a 60.32 kWh gap from §7.1 resolution damage. The tile read **+12 pp** where like-for-like
  is **+10 pp**, and the bias flattered the battery in EVERY preset (+29/+25, +28/+26, +31/+28,
  +26/+23, +12/+10). A correct `self_sufficiency_baseline` was computed and never read.
- **Self-consumption compared a 162-day PV window against a 365-day one.**
- **Two unexplained "grid import"/"grid export" figures on one panel** (3,924 vs 3,864; 2,096 vs 2,030).
- Minor: a zero-load household reported "0% → 100%"; "Extra grid import" was missing from the NL
  catalog; `_fmt_kwh` used ASCII `-` where `_fmt_signed_kwh` used U+2212.

The code comment showed the self-sufficiency choice was a DELIBERATE trade — taken from the
reconciliation so the tile would agree with the band above it. §7.1 rules the other way and prescribes
both halves of the remedy: *"Use the simulated baseline (run A), so that both scenarios see identical
information. Report the observed import alongside it, with the difference labelled as resolution
loss."*

### Fixes applied (iteration 1)

Both halves of both comparisons now come from `EnergyMetrics`; the band's Grid figures gained an
"as your meter recorded them" caption (in the shared macro, so panel ① gets it too — correct, they are
measured in both places); and a caveat names the gap per §7.1. Displayed figures moved to the honest
like-for-like values — 1-year self-sufficiency **23% → 33% (+10 pp)**, self-consumption **36% → 60%**.

**The implementer corrected the review's DEFECT-2 diagnosis, and the correction is right.** The
windowing was NOT the cause: §6.9 computes export as `max(0, pv − load)` over a §6.3-clamped
non-negative load and `frame.pv` is zero outside PV coverage, so a run cannot export where `pv == 0`.
Orchestrator-verified: run A's export where `pv == 0` is exactly 0.0, and run A's total export is
2030.033745 kWh masked and unmasked alike. The 34% → 36% shift came entirely from the §7.1
information-set switch. The PV mask was kept anyway on a structural argument: it converts an agreement
that holds *because of how §6.9 happens to define export* into one the metrics layer states for itself,
so a later phase giving a run another export path (D3 grid arbitrage) cannot silently break it.

**Why no existing test caught this:** every panel-③ fixture had `export = 0`, so measured and simulated
import coincided and the defective view passed. The new tests use an overlap fixture (2 kWh/h import
AND 1 kWh/h export in the same hour) where the two information sets differ by a factor of two —
measured self-sufficiency 50%, simulated 75% — with both candidates pinned in each assertion.

Suite: **328 passed, 2 skipped**.

### Phase 4 follow-ups (deferred, not blocking)

- **The band's own derived ratios stay measured** (Household self-sufficiency 21%, Solar
  self-consumption 34%) and so still differ from the tiles' 23% / 36%. That is the intended split —
  §2.3a describes the band as battery-free measured data — and the caveat now says the savings section
  is simulated while everything above it is the meter's. Moving the band's ratios to simulated figures
  would be a further product decision, not taken here.
- The resolution-loss caveat fires when the gap rounds to ≥ 1 kWh; that threshold is a judgement call,
  not spec-derived.
- `pybabel update` needs `--no-location` (the committed catalogs carry no `#:` comments) and
  `--no-fuzzy-matching` (fuzzy matching mistranslated "Extra grid import" as "Netafname T2"). Worth
  documenting in `babel.cfg`'s workflow; not changed here.

## Phase 5 — §6.12 perfect-foresight energy DP (run D) + the benchmark box

> Detailed per-decision record: [20260725-perfect-foresight-benchmark-phase5.md](20260725-perfect-foresight-benchmark-phase5.md).

**Built.** New `app/domain/benchmark.py` — the §6.12 DP minimising kWh of grid import, backward pass
vectorised over (n_soc × n_actions), `np.interp` on V, terminal constraint seeded as `+INF` below the
starting SoC, and both export baselines (inheriting + unconstrained; the second skipped as provably
identical when `allow_grid_export` is on). `dp_soc_levels` (101) / `dp_action_levels` (41) added to
`simconfig`. `results_view.py` emits the `benchmark` key the template already guarded.

**Real-dataset figures** (orchestrator-verified live): baseline import 3,864 kWh, policy saved 341,
perfect-foresight bound 603, capture ratio **0.567**, DP SoC 5.00 → 9.47 (terminal constraint binds
non-trivially). A 57% capture on a fixed-band P3/D1 policy is consistent with §6.7's remark that fixed
bands approximate a daily-moving price signal poorly — a figure near 1.0 would have been the
suspicious one. The "…if export allowed" row correctly does not render: both bounds are identical, so
divergence is 0 and §2.4's 0.02 threshold omits it.

### Four defects the implementer found by measurement (each broke the upper bound)

1. **Starting SoC not on the state grid** — §6.12's plain `linspace` rarely contains
   `initial_soc_kwh`, which the terminal constraint is stated against, so the DP had to charge before
   acting and returned a bound *below* standing still. Fixed by snapping the nearest level onto it.
2. **The forward pass snapped the policy lookup**, reintroducing the discretisation interpolation
   removes. Now re-solves at the true continuous SoC against a stored per-interval V (~7 MB, verified).
3. **The 41-action grid cannot represent the PV surplus or household deficit** the policies dispatch
   on, so the DP came out ~3% BELOW a P1/D1 policy. `_interval_actions` appends both exact points.
4. **A 0.025 kWh residual** from "return exactly to the starting SoC" being state-dependent;
   `_DP_SLACK_KWH = 0.03` absorbs it.

### Adversarial review verdict: DEFECT FOUND (presentation) — the DP itself verified sound

The review attacked the DP hard and cleared it: a **16,000-pair fuzz** of `_transition` against
`battery_step` across 400 randomised configs found **zero divergence**, including the clamp paths the
shipped fixture missed; the stored-V index has no off-by-one (backward value 7.000000 vs forward
realised 7.000000, diff 0.00e+00); appended actions cannot break the bound (they strictly enlarge the
set both passes minimise over); the terminal constraint binds; both hand fixtures recompute; the DP
never reads price (all-NaN spot gives bit-identical import). **The slack constant survived a mutation
attack** — it shrinks with `dp_action_levels` (0.025 → 0.0031 at 41 → 321) and is invariant to
`dp_soc_levels`, exactly as a discretisation artefact should be, while injected defects blew through
it by 2.17 and 4.80 kWh. It leaks into no reported figure (test-only).

**The defect: the implementer found §6.12's terminal-constraint asymmetry, fixed it in the TESTS, and
did not follow it into the VIEW.** The DP must end at or above its starting SoC; run C need not. So a
policy that liquidates its opening charge books a "saving" the benchmark is forbidden to match, and
the capture ratio becomes meaningless. Orchestrator-reproduced (20 kWh battery, 100% initial SoC, 96
intervals): policy saved 14.20 kWh funded by an **−18.00 kWh drift**, bound −2.88, ratio −4.93 → the
panel printed **"captures -493 percent"**. The review found three further shapes including
"2859 percent" and — worst — a `None` ratio glossing "even a perfectly-informed battery could not have
avoided any grid import" directly above a row reading "Your policy 9 kWh". Reachable with only a high
initial SoC and a short window, both of which the range picker and Phase 6's form expose.

**Fixed in the view, not the metric** (`capture_ratio` stays unclamped — correct for a test consumer
that wants to see a fault). Drift-correction was chosen over suppression on the review's argument:
§6.11's "report drift rather than net it out" governs the drift METRIC, which is untouched and still
reported unnetted by its own caveat; what is corrected is a RATIO whose denominator is already
drift-constrained by §6.12. Leaving the numerator raw does not preserve information — it produces a
quotient of two incompatible quantities. The correction uses the same basis the fixture-6 assertion
already used, so box and test agree. "Materially negative" reuses the existing `SOC_DRIFT_WARN_FRAC`
(2%) with a sign condition rather than inventing a threshold. The gloss now explains the residual in
words instead of printing a number.

### Performance: lazy-loaded on the user's decision

The DP costs ~2.3 s per run, ~4.6 s for both, taking `GET /` from 0.13 s to **4.72 s** — ~97% of the
request. Cost scales linearly with window length (1 week 0.04 s, 30 days 0.19 s, 3 months 0.57 s).
Presented as four options; **the user chose lazy-loading**. `results_from(..., with_benchmark=False)`
by default; a new `POST /results/benchmark` returns the box fragment; `window.loadBenchmark()` lives
in `index.html` so it survives the panel-③ fragment swap, re-firing after every range change, with a
20 s timeout and a token check so a stale in-flight response cannot land in a newer slot.

Orchestrator-verified live: **`GET /` 0.14 s** (was 4.72), benchmark endpoint 4.87 s separately, box
numbers unchanged (341 / 603 / 57 percent), the window attribute correctly HTML-escaped, and error
paths clean (400 on a bad preset, 400 on period+range, 422 on a non-object body — no 500s).

Suite: **384 passed, 2 skipped**.

### Two findings against the SPEC (prose corrections for a later editing pass — no code change)

- **§6.12's terminal constraint is asymmetric with the policy run.** The DP must finish at or above
  its starting SoC; nothing imposes that on run C, and §6.11 deliberately reports drift rather than
  netting it out. Fixture 6's bound can therefore fail on raw numbers through a spec gap rather than a
  code defect. The spec says nothing about the policy run's endpoint.
- **§6.12's claim that nearest-snapping causes "a systematic pessimism bias of several percent" is
  measurably wrong in both direction and magnitude.** Independently reproduced by the implementer and
  the reviewer at six grid sizes: snapping is **optimistic** (17.41 vs interpolation's 27.59 vs a
  realised 27.64 at 21 SoC levels) and converges *upward* as the grid refines, while interpolation is
  stable from 11 levels on. An upward-rounded landing SoC credits energy the battery does not have, so
  snapping's figure sits *below* the realised dispatch and bounds nothing. The spec's conclusion
  (interpolate) is right; its stated reason would lead a future reader to treat snapping as the safe
  conservative option, which is backwards.

### Phase 5 follow-ups (deferred, not blocking)

- **A `1e-6` tolerance on the ratio's range test is the implementer's judgement**, not review-specified:
  a policy that exactly matches the bound corrects to `1.0000000000000024` and would otherwise be
  reported as a fault. Display tolerance on a float artefact; real breaches are orders of magnitude
  larger (−4.93, 28.59).
- **`| e` on `data-benchmark-body` is load-bearing** — without it the raw `"` terminates the attribute
  early and the fetcher reads `{`. Verified escaped in the live page, but its correctness depends on a
  filter that is easy to drop.
- With export off, both DPs are **bit-identical** on this dataset (import 3261.476807 either way), and
  the review confirmed the feasibility masks genuinely differ (180 infeasible cells vs 0) — so the
  second DP really does optimise over a superset and simply cannot improve an import-minimising
  objective. That is an argument, not a proof, and it is what experiment X10 exists to settle.

## Status

**Phase 1 complete** — implemented, adversarially reviewed, fixes applied and verified, committed
(`9f639d2`).
**Phase 2 complete** — implemented, adversarially reviewed (DEFECT FOUND), all five defects fixed and
verified, committed (`6a8707c`).
**Phase 3 complete** — implemented, adversarially reviewed (CLEAN), two minor test fixes applied
without moving any number, committed (`bf52cb4`).
**Phase 4 complete** — implemented, adversarially reviewed (DEFECT FOUND: observed/simulated mixing),
all defects fixed and verified, committed (`18d5f7a`).
**Phase 5 complete** — implemented, adversarially reviewed (DEFECT FOUND: drift-funded capture ratio),
fixed, benchmark box lazy-loaded on the user's decision, verified live, committed.
Next: Phase 6 (panel ② wired), then Phase 7 (i18n + full-suite pass).
