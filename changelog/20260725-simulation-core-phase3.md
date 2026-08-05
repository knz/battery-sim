# Simulation core — Phase 3 (§6.6–§6.9)

## Task specification

Implement the sequential simulation core the specs define in
`specs/11-policies-and-battery.md` §6.6–§6.9, consuming the Phase-1
`SimulationFrame` (§4.4) and the Phase-2 `SimulationConfig`:

1. `charge_request` (§6.6) — (kwh_from_pv_surplus, kwh_from_grid), no `has_pv`
   branch, no `simulate_cost` branch, band against the bare spot price.
2. `discharge_request` (§6.7) — (kwh_to_home, kwh_to_grid); D2/D3 serve the house
   first, export only when `allow_grid_export`; `economic_guard` per spec but
   dead in this increment (Phase 2 forces it False without a cost model).
3. Band-overlap netting per §6.7's closing block.
4. `battery_step` (§6.8) — all seven numbered steps in order.
5. `simulate` (§6.9) — the sequential loop; standby added to load, exists only
   with a battery; NaN load/pv → gap, SoC carried forward.
6. `simulate_baseline` (§6.9) — vectorised, no battery, no standby, BUT the
   export limit and PV curtailment apply to it too (§7.2 item 1).
7. A `Flows` result container with per-interval arrays plus gap marking.
8. A run harness for runs A, B, C (§6.9's table). Runs D/E are Phase 5.

Out of scope, explicitly: §6.11 metrics, §6.10 cost accounting, §6.12
perfect-foresight DP, §6.15 epochs, §6.16 bracket, UI wiring.

## High-level decisions

**One module, `app/domain/simulate.py`.** The four §6.6–§6.9 functions are one
concern (dispatch → physical limits → integration) and share the `Flows`
container and the hoisted-config locals; splitting them across files would put
the netting rule in a different file from the step that consumes it.

**`Flows` is a struct-of-arrays, allocated once per run.** Ten float64 arrays
(`imp, exp, chg_pv, chg_grid, dis_home, dis_grid, stored, withdrawn, curtailed,
soc`) plus a boolean `gap` mask and a list of import-limit-exceeded indices.
§6.8 returns a per-interval `Flows(...)` in the pseudocode and §6.9 writes
`out[i] = f`; a per-interval object would allocate n small objects for no gain,
so `battery_step` returns a plain tuple (`StepFlows`, a NamedTuple) and the
caller scatters it into the arrays. `Flows.empty(n)` and `out.mark_gap(i)` keep
the spec's names.

**Gap intervals are NaN in the flow arrays, not 0.** The same reasoning §4.4
gives for `spot`: a 0 in `imp` means "imported nothing", which is a claim about
an interval the simulation deliberately did not evaluate. `Flows.empty` fills
with NaN and `mark_gap` leaves it, setting only `soc[i]` (carried forward) and
`gap[i] = True`. Metrics (Phase 4) must therefore use `np.nansum`; `Flows`
exposes `totals()` so that decision is made in one place. §6.14 fixture 3's
conservation identity is asserted over non-gap intervals only, which is what
"gaps excluded from sums" (§7.3 check 3) means.

**Runs A/B/C are a `RunSet` dataclass built by `run_all(frame, cfg)`.** B and C
are the same `simulate` call differing only in `include_standby`, so the harness
is thin on purpose; its value is that `standby_kwh ≡ C.load_total − B.load_total`
is exact by construction and Phase 4 can read `C − B` without re-deriving it.

**The export limit applies to run A (§7.2 item 1).** `simulate_baseline` is
vectorised — `net = load − pv`, `imp = max(net,0)`, `exp = max(−net,0)` — and
then applies `exp_cap` with the excess recorded as `curtailed`, exactly as
§6.8 step 6's second half does for the battery run. Without this, run A would
export freely past a cap the battery run respects and the battery would be
credited with avoiding a constraint the baseline never faced. Asserted in tests.

**Cancellation is an injectable hook, not a threading model.** §6.9's
`cancel_event` / `CANCEL_CHECK_INTERVAL` presuppose a run orchestration layer
that does not exist yet. `simulate(..., should_cancel=None)` takes an optional
zero-argument callable polled every `CANCEL_CHECK_INTERVAL` (1024) intervals and
raises `Cancelled` when it returns True. Default `None` skips the check
entirely, so nothing here invents a threading or event model — Phase 6 supplies
one and passes `run_event.is_set`.

**NaN spot idles the battery, deliberately.** Phase 1 emits NaN for an interval
no price covers. `A <= nan <= B` is False in Python, so both bands fail and the
battery neither charges from grid nor discharges in-band; P1/P3 PV surplus and
D1/D3 deficit service are unaffected, since neither reads `spot`. That is the
right behaviour (dispatch on an unknown price would be an invention), but it
must be explicit rather than accidental, so the code says so at the comparison
and a test pins it.

## Rationales and alternatives

**Config values are hoisted into loop locals in the CALLER**, exactly as
Phase 2's module comment instructs — `eta_c`, `eta_d`, `eta_c_pv`, the SoC
bounds, the per-interval energy caps. `battery_step` therefore takes them as
explicit arguments rather than re-reading `cfg` per interval. Nothing is cached
on the config object.

**Frame arrays are never modified in place.** `st.load = frame.load +
standby_kwh` REBINDS a new array; the frame's own `load`/`pv` arrays are the
same objects `reconcile_grid` produced and are shared with the data-summary band
and the panel-③ results view. Any `+=`, `[:] =` or `out=` on them would silently
corrupt the band's published numbers. A `_View` object holds the rebound `load`
alongside the frame's other arrays so the frame itself is never touched.

**`req_grid` in §6.7 is computed but the `full − req_home` remainder only flows
when `allow_grid_export`** — implemented literally. The economic-guard branch is
written per spec and marked as unreachable in this increment.

## Obstacles and solutions

* **An `initial_soc_pct` outside `[min, max]` crashed step 7's bound assertion.**
  §7.3 check 11 does not block it — Phase 2 warns and allows it, and Phase 2's
  own warning text says the value "will be clamped at the first step". But §6.8's
  steps cannot bring an out-of-window SoC back in (step 3 charges only toward
  `soc_max`, step 4 discharges only down to `soc_min`), so nothing did the
  clamping and interval 0 asserted. Found by the randomised SoC-containment test,
  which was written with a below-floor start on purpose. Fixed by clamping in
  `simulate` before the loop, which is where the spec's own wording puts it;
  `soc_start` records the clamped value so §6.11's drift figure measures against
  the SoC the run actually began from.
* **Step 4's available-energy term goes negative for the same input.**
  `(soc − soc_min) × eta_d` is negative when the SoC starts below the floor, and
  a negative `dis_ac` would run the arithmetic backwards — `withdrawn` negative,
  step 7 CHARGING the battery on a discharge request. Floored at 0, which is the
  physical reading ("nothing available to discharge"). Latent even with the
  clamp above, since it also guards any future path that could leave the SoC low.
* §6.8's pseudocode leaves `curtailed` undefined on the path where the export
  cap does not bind — initialised to 0.0 up front.
* §6.8 step 6 sheds `chg_grid` on import overrun but does not re-derive `chg_ac`;
  `stored` is decremented by `cut * eta_c`, which is the spec's own line, and is
  correct because the shed energy is grid energy charged at `eta_c`.
* The naive conservation identity `Σ(pv+imp+dis) == Σ(load+exp+chg)` does not
  close: it omits curtailed PV (generated but never delivered). The asserted
  form adds it to the right-hand side — see the test's comment.
* **Three fixture-16 tests were silently hitting the default connection cap.**
  Found by the adversarial review, which instrumented the shed path: the
  appendix-A default is 1×25 A → 5.75 kW, and fixture 16's 5 kW charge request
  plus the ~1 kW load exceeds it, so §6.8 step 6 shed grid charging from 5.0 to
  4.72 kWh/h (20 sheds in the main arbitrage test, 8 in each sibling). The
  RESULTS were unaffected — the 12-hour low-price window has enough slack that
  the battery still fills, one hour later — but the analytic derivation in the
  docstring reasons about a 5 kW rate the run never reached, so the test did not
  assert what it claimed to. Fixed with `max_import_kw_override=100.0` on
  `_arbitrage_cfg`, matching how fixture 2 already handled the same problem.
  Verified rather than assumed: every asserted quantity (`efc`, `saved`,
  `standby_kwh`, `conversion_loss`, all ten flow-array totals, the per-day SoC
  maxima and end values) is unchanged to within 1e-14, well inside the 1e-6/1e-9
  tolerances. Only the per-interval SoC trajectory moves, by the one-hour shift.
  Re-instrumenting after the fix confirms no import shed remains anywhere except
  the two tests whose subject IS the connection limit; the remaining export
  sheds are likewise all in cap-focused tests, plus the randomised run, where
  reaching step 6 from an unplanned direction is part of the point and is now
  noted in that test's docstring.

## Adversarial review

`app/domain/simulate.py` was put through an adversarial review against the spec.

**Verdict: CLEAN — no correctness defects found in the module.** The review did
not modify it, and it has not been modified since. The two findings it did raise
are both about the TESTS, and are recorded above and below.

The review independently confirmed three earlier judgement calls:

* **Both spec-pseudocode defects are real.** §6.8's `curtailed` is genuinely left
  unbound on the non-curtailing path, and step 4's available-energy term
  genuinely goes negative for a below-floor starting SoC. The workarounds this
  phase chose (initialise to 0.0; floor `dis_ac` at 0) are the right readings.
* **Recording the CLAMPED `soc_start` is required, not merely defensible.** This
  had been argued on readability grounds; the review supplied the numeric
  argument, which we re-verified directly. With `initial_soc_pct=5%` under a 20%
  floor on a 10 kWh battery, §6.11's conversion-loss identity
  `chg − dis − (soc_end − soc_start)` closes at exactly 0.0 with the clamped
  value (2.0 kWh) and yields −1.5 with the raw value (0.5 kWh) — a negative
  conversion loss, i.e. energy created by the inverter. So the choice is forced
  by a downstream metric, not a matter of taste, and Phase 4 depends on it.
* **The mutation check was spot-verified.** One of the seven defects was
  re-introduced independently and the same tests failed, so the mutation results
  reported below reflect real coverage rather than an untested claim.

**The fixture-3 conservation identity is weaker than it looks — and this matters
for Phase 4.** The asserted identity is §6.8 step 5 algebraically rearranged:
step 5 DEFINES `imp` and `exp` as the two signs of
`load + chg_pv + chg_grid − pv − dis_ac`, and substituting that back into
`pv + imp + dis_home + dis_grid == load + exp + chg_pv + chg_grid + curtailed`
returns step 5 unchanged. So whenever no connection cap binds, conservation
closes BY CONSTRUCTION, and a defect confined to step 5's inputs is invisible to
it. Demonstrated empirically by the review and re-confirmed here: mutating
`withdrawn = dis_ac / eta_d` to `withdrawn = dis_ac` — dropping the discharge
conversion, which genuinely creates energy — leaves both conservation tests
passing. `withdrawn` is a storage-side quantity and no storage term appears in
the identity at all. What catches that mutation is the hand-computed fixtures 1,
2 and 16, whose expected values were derived from the spec's efficiency
convention rather than from the implementation's arithmetic.

This does not make the test worthless: once a cap binds, §6.8 steps 6 and 7
adjust seven quantities by hand after step 5 computed its residual, the
rearrangement stops holding trivially, and that is where the identity earns its
place. `test_fixture_3_conservation_holds_with_curtailment_and_gaps` is that
case; the unconstrained sibling is a regression guard on step 5 keeping its
residual form.

**Consequence for Phase 4 (§6.11 metrics), stated explicitly because the metrics
are computed from these same arrays:** conservation is not a general safety net
over them. It cannot detect a wrong efficiency convention, a wrong `withdrawn`,
a wrong SoC trajectory, or any error that stays on the storage side of the
inverter. Each new metric needs its own hand-computed fixture. This is written
into `_assert_conservation`'s docstring and into both fixture-3 tests so a
Phase-4 implementer reading the tests cannot miss it.

## Files modified

* `app/domain/simulate.py` — new. §6.6–§6.9 core, `Flows`, `RunSet`, `run_all`.
  **Unchanged by the review and by the two fixes below** — the review found no
  correctness defects in it.
* `tests/test_simulate.py` — new. Fixtures 1, 2, 3, 5, 16, 17, §7.2 item 1, plus
  the clamping/gap/netting/limit/NaN-spot cases. Subsequently: the connection
  override on `_arbitrage_cfg`, and comments recording what the conservation
  identity does and does not cover.

## Verification

25 new tests; full suite 296 passed / 2 skipped, up from 271/2, with no existing
test affected.

The new tests were mutation-checked rather than merely run: seven deliberate
defects were introduced one at a time into `simulate.py` and each was caught —
baseline ignoring the export cap (2 failures), all round-trip loss on the charge
side (3), the export shed order reversed (1), band-overlap netting removed (1),
standby written into the frame in place (6), import-limit shedding removed (2),
and the headroom clamp left in AC units (3). The file was restored after each.

## Current status

Implementation and tests complete; full suite green at 296 passed / 2 skipped,
unchanged by the adversarial review and by the two test fixes it prompted (no
test count moved, and no asserted number moved). `app/domain/simulate.py` is as
originally written — the review found no correctness defects in it.

Not committed (the orchestrator commits). Runs D/E (§6.12 DP) and §6.11 metrics
remain for the later phases; Phase 4 should read the note above on what the
conservation identity does not cover before relying on it.
