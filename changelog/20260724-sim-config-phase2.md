# Simulation configuration object — Phase 2

## Task specification

Build the battery/policy configuration object the §6.6–§6.9 simulation core takes as
`cfg`. Pure data + derived quantities + validation. Explicitly OUT of scope, deferred to
Phase 6: persistence (config.toml / params file) and any UI wiring (panel ② form,
per-field error rendering).

Required content, with appendix-A defaults:

1. Battery parameters (capacity, SoC limits, powers, RTE + DC bonus, standby, initial SoC,
   coupling).
2. Grid connection (phases, fuse, derived max import, export limit).
3. Policies (P1–P3, D1–D3, bands A–D, allow_grid_export, economic_guard).
4. Topology (pv_coupling, battery_phases, approximated).
5. Flags (has_pv, simulate_cost).
6. Derived: SoC bounds in kWh, the efficiency split, max_import_kw.
7. Validation: §7.3 check 11 (block, field-keyed) and check 12 (warn, allow).

## High-level decisions

**Four dataclasses, not one flat bag, composed into one `SimulationConfig`.**
`BatteryConfig`, `GridConfig`, `PolicyConfig`, `TopologyConfig`. The grouping follows the
panel-② form boxes (§2.3) exactly — Battery / Grid connection / Installation topology /
Charge+Discharge policy — so Phase 6's per-field error rendering has a one-to-one mapping
from group to form box, and so an error key like `battery.min_soc_pct` names the box the
user must look in. Charge and discharge policies are one `PolicyConfig` rather than two
because check 12 is a cross-band check: putting the bands in separate objects would make
the one validation that spans them harder to express, not easier.

**Derived quantities are `@property`, computed on every access — nothing is cached.**
~~Originally: computed once in `__post_init__` and stored in `init=False` fields, on the
grounds that §6.8's `battery_step` reads `cfg.soc_max_kwh`, `cfg.eta_c`, `cfg.eta_d`,
`cfg.eta_c_dc`, `cfg.max_import_kw` inside the per-interval loop and recomputing a sqrt per
interval is wasteful.~~ **Reversed** — see defect D1 below. The dataclasses are mutable by
design (Phase 6 binds a form to them), so a cached derived field goes stale the moment the
user moves a slider, silently and with no error anywhere. Nothing cached means nothing can
go stale. The cost is a sqrt and a multiply per access; if that ever measures as hot, the
fix is for the §6.9 caller to hoist the values into locals before the loop, which is safe
because the loop body does not mutate `cfg`. Frozen dataclasses would also work but Phase 6
needs in-place mutation; a `__setattr__` re-derive hook is invisible magic that fails on
assignment to a nested object.

**The efficiency split.** `eta_c = eta_d = sqrt(roundtrip_efficiency)` per §6.8's stated
convention. This is what makes §6.14 fixture 2 come out: charging 10 kWh AC into an empty
battery stores `10 × sqrt(0.9) = 9.4868 kWh`, discharging it back yields
`9.4868 × sqrt(0.9) = 9.0 kWh` AC — a round-trip loss of exactly 1.0 kWh. Splitting the
loss the other plausible ways (all on charge, or 5%/5% linear) gives 0.9 or 1.11 kWh.
`eta_c_dc = sqrt(roundtrip + roundtrip_dc_bonus) = sqrt(0.94)`, applied to `chg_pv` only.

**`max_import_kw` is derived, not tabulated — and the computed value is EXACT.**
`connection_capacity_kw(phases, fuse_a)` returns `phases × fuse_a × 230 / 1000` with no
rounding at all; it is the physical limit §6.8 step 6 compares the net flow against.
`connection_capacity_kw_display()` is a separate, display-only helper for panel ②.

*(This paragraph previously described the rule as "rounded half-away-from-zero to one
decimal ... 5.75 exact, 2 dp", which was drift on two counts: the implemented rule was
magnitude-conditional rather than one-decimal-with-an-exception, and the rounded value was
being used as the physical cap rather than only for display. Both are corrected — see D4.)*

The display rule, as implemented: `ROUND_HALF_UP`, then 2 dp below 10 kW and 1 dp at or
above. Python's `round()` is banker's rounding and gives 17.2 for 17.25, so it cannot
produce appendix A's published 17.3 at all; `decimal.ROUND_HALF_UP` is used deliberately.
The magnitude condition reproduces both published figures — 1×25 A → 5.75 (2 dp, as
appendix A and the §2.3 wireframe print it) and 3×25 A → 17.3 (1 dp, as appendix A and
background E-A print it). **That precision rule is INFERRED, not specified**: two data
points do not determine it, and other rules ("2 dp only when the second digit is non-zero",
"3 significant figures") fit them equally. Nothing downstream depends on it now that the
output is display-only. The 230 V constant is likewise inferred — it appears nowhere in
`specs/` and is pinned by exactly those two figures.

**`economic_guard` and `pv_coupling` are forced on READ, over a retained raw value, and
additionally normalised in `__post_init__` and at the top of `validate()`.** Appendix A and
§6.7 both say `economic_guard` is forced (not merely hidden) without a cost model, because
it reads `p_export_net`, which does not exist in an energy-only run. §2.5 says the same for
`topology.pv_coupling = null` / `cfg.coupling = ac` without PV. Three points of enforcement,
with different jobs:

* `SimulationConfig.economic_guard` / `.coupling` / `.pv_coupling` are properties applying
  the forcing at access time. **This is what makes it safe** — dispatch must not depend on
  the caller having called `validate()`, and a consumer that flips `simulate_cost` after
  construction must not be able to observe a forbidden value.
* `_force_invariants()`, run from `__post_init__` and again from `validate()`, normalises
  the STORED values so a persisted parameter file or a debugger view also looks right.
* The raw user choice stays on `policy.economic_guard` / `topology.pv_coupling`, so Phase 6
  can round-trip the form and re-enabling cost simulation (or PV) restores the user's
  answer. Appendix A is explicit that cost-only parameters are "retained at their stored
  values" rather than reset.

**No `has_pv` branch in dispatch semantics.** §6.6 is explicit that the code needs none and
should not acquire one. Policy OFFERABILITY (which options panel ② shows) is exposed as a
separate query `offerable_charge_policies()` / `offerable_discharge_policies()`, clearly a
UI-gating concern and clearly not read by §6.6/§6.7. `charge_policy` itself is NOT coerced
to P2 when `has_pv` is false: P1/P3 already compute the right answer there, and coercing
would silently rewrite the user's stored choice if they later turn PV back on.

**Validation returns a structured result, does not raise.** `ValidationResult` carries
`errors` and `warnings`, both lists of `ConfigIssue(field, code, message)` where `field` is
a dotted path (`battery.roundtrip_efficiency`) Phase 6 can key a form field on, and `code`
is a stable machine identifier so the message text can be translated without breaking
tests. `blocking` is `bool(errors)`. Construction never raises — an invalid config is a
representable object the form must be able to hold and show errors against; refusing to
construct it would leave the form nothing to render.

**Where the spec is silent, warn rather than block.** Blocking rules are exactly check 11's
list plus the physics bound. Everything else found genuinely suspect —
`initial_soc_pct` outside `[min_soc_pct, max_soc_pct]`, negative standby, band A > B or
C > D, SoC percentages outside 0–100 — is examined case by case in the code comments.
Percentages outside 0–100 and a negative standby are structurally impossible states rather
than aggressive settings, so they block; an inverted band and an out-of-window initial SoC
warn, since neither makes the simulation ill-defined (an empty band simply never fires; the
initial SoC is clamped once at t=0).

## Ambiguities found in appendix A

* `max_export_kw` is listed as "= import" with no independent default. Modelled as
  `max_export_kw: float | None = None` meaning "follow import", with `effective_max_export_kw`
  derived. A plain float default would lose the distinction between "the user chose 5.75"
  and "the user chose to track import", which matters as soon as they change the fuse.
* `battery_phases` defaults to `three_phase` but is "only offered when connection is
  3-phase", while `phases` defaults to 1. So the default configuration carries a
  battery_phases value that is not offered. Resolved by treating the stored value as inert
  on a 1-phase connection (the simulator has no per-phase model in v1 anyway) and exposing
  `battery_phases_offered`. Flagged rather than silently normalised.
* Appendix A gives no defaults for bands A–D; it says so explicitly. The panel-② wireframe
  shows −0.050 / 0.040 / 0.180 / 9.999, and `app/sample_data.py` renders those. Those are
  used as the dataclass defaults, sourced to §2.3, not to appendix A.
* Appendix A tabulates no default for the charge/discharge policies themselves. §2.3's
  wireframe preselects P3 and D1, and sample_data agrees; used as defaults.
* `topology.approximated` (§2.5, §4.5) is carried on `TopologyConfig` as a plain flag set
  by the caller when the user continues past the unsupported-phase-topology soft block. It
  is not derived, because §2.5 makes it the record of a user's explicit choice.

## Adversarial review — defects found and fixed

A review of the finished Phase-2 code returned DEFECT FOUND. Five items, all fixed in the
same module; the appendix-A defaults (all 19), the check-11/12 block-vs-warn discipline and
the no-PV dispatch invariance were reviewed and confirmed correct, and are unchanged.

**D1 (high) — derived values went stale on mutation, and the "forced" invariants were not
forced.** `_derive()` ran only in `__post_init__` while the dataclasses are mutable, so
`cfg.battery.usable_capacity_kwh = 20.0` left `cfg.soc_max_kwh` answering 10.0;
`roundtrip_efficiency = 0.64` left `eta_c` at 0.94868 instead of 0.8; a post-construction
fuse/phase change left `max_import_kw` at 5.75 instead of 55.2. `validate()` reported none
of it, because it compared the same stale numbers. A stale `eta_c` or `soc_max_kwh` corrupts
every figure §6.8 produces with nothing raised and nothing in the result looking wrong.
Same class, smaller radius: `cfg.policy.economic_guard = True` set after construction stuck,
and `cfg.has_pv = False` afterwards left both couplings at `dc_hybrid`.

Fixed by removing every cached `init=False` derived field and making each one a property
(rationale in the "Derived quantities" decision above), and by moving the forced invariants
onto the read path as described. Two alternatives were considered and rejected: frozen
dataclasses (Phase 6 needs the mutable binding model) and a `__setattr__` re-derive hook
(invisible, and defeated by assignment to a nested object).

**D2 — aliasing between configs.** `_force_invariants` writes to the sub-objects it is
handed, so `SimulationConfig(battery=shared, has_pv=False)` silently rewrote the coupling of
an earlier config built from the same `shared`. Realistic in Phase 6, where "clone this
config" or a with-PV/without-PV comparison naturally reuses a group. Fixed by
`dataclasses.replace`-copying all four sub-configs in `__post_init__`; a shallow copy is
enough since every field in them is a float, bool, None or enum. The existing
`default_factory` usage was already correct and was left alone.

**D3 — construction raised, contradicting the stated contract.** The module docstring said
"construction never raises", and the sqrt-flooring was justified by it, but `Decimal(str(x))`
raised `decimal.InvalidOperation` for `phases=None`, `fuse_a=None` and nan/inf — and an
empty Phase-6 form field arriving as `None` is exactly the case that rationale was written
for. Separately, `GridConfig(phases="3")` derived a capacity through the `Decimal` path while
`phases not in (1, 3)` then blocked it, so the derivation and the check disagreed on what a
valid phase count is.

Fixed with a single `_finite()` funnel: anything that is not a finite real number (including
`bool`, since `True == 1` would otherwise derive a plausible 5.75 kW single-phase connection
AND pass `phases in (1, 3)`) becomes `None`, derived properties substitute 0.0, and
`validate()` reports a blocking `not_a_number` issue keyed to the field. Strings are rejected
rather than parsed: coercion is the form layer's job and must happen before the value is
stored, or the dataclasses' declared types stop meaning anything.

Two follow-on keying fixes fell out of D3: a non-numeric `phases` derives a 0.0 cap, which
tripped "max import must be greater than 0" against a perfectly good 25 A fuse; and a bad
import figure propagated through the follow-import path to a second error on
`grid.max_export_kw`, a field the user never touched. Both cascades are now suppressed, so
one mistake produces one error against one input.

**D4 — the connection cap was rounded before being used as a physical limit.** The rounded
value was what §6.8 step 6 compared against: 3×25 A gave 17.3 where the physics is 17.25
(+50 W), 3×16 A gave 11.0 where it is 11.04 (−40 W). Immaterial to an annual kWh total,
which is precisely why it should not be a rounding artefact — a formatting decision was
baked into the physics. Split into an exact `connection_capacity_kw()` for computation and a
`connection_capacity_kw_display()` (plus `max_import_kw_display`) for panel ②, with the
inferred-precision caveat recorded at the display helper.

**D5 — wrong field key.** `GridConfig(max_import_kw_override=-1)` keyed its error to
`grid.fuse_a`. The fuse is fine; the override is the bad input, and Phase 6 renders errors
inline against the field the user typed in. Now keyed to `grid.max_import_kw_override` when
an override is set and to `grid.fuse_a` otherwise.

**Test weaknesses repaired.** `test_roundtrip_identity_holds_to_closure_tol` asserted
`sqrt(r) * sqrt(r) == r`, which is true of any implementation using the same expression
twice and so near-unfailable; replaced by a test pinning the literal 0.9486832980505138 and
asserting that a linear 0.95/0.95 split does NOT reproduce fixture 2's 1.0 kWh loss.
`test_efficiency_split_is_geometric` wrote `math.sqrt(0.90)` — the implementation's own
formula — and now uses hardcoded literals. `test_no_pv_does_not_touch_the_dispatch_relevant_fields`
excluded `coupling` and `eta_c_dc` correctly (those ARE forced by §2.5) but its docstring
claimed broader coverage than it checked; the exclusion and its reason are now named, with a
pointer to the test that does cover them.

**Recorded rather than changed: §6.6's "`charge_policy` is P2".** §6.6 says flatly, of the
no-PV case, "Neither is offered in the UI in that case; `charge_policy` is P2." Read here as
describing what panel ② OFFERS, not as an instruction to coerce a stored value — the same
paragraph insists the dispatch code "needs no branch on `has_pv` — it already computes the
right answer — and should not acquire one", which would be false if the value had to be
rewritten first. So `charge_policy` is still not coerced, and `offerable_charge_policies()`
still carries the UI-gating answer. Flagged here because the sentence reads as a directive
in isolation and a future reader may reasonably question the reading.

## Files modified

* `app/domain/simconfig.py` — new. The four dataclasses, `SimulationConfig`, the derived
  quantities, `ConfigIssue` / `ValidationResult`, `validate()`, offerability queries.
  Revised for the review: derived fields → properties, sub-configs copied on construction,
  `_finite()` / `_num()` numeric funnel, `connection_capacity_kw()` made exact with a
  separate `connection_capacity_kw_display()`, forced invariants moved onto the read path
  and re-applied in `validate()`, `not_a_number` validation issues, corrected error keys.
* `tests/test_simconfig.py` — new. Table-driven defaults check against appendix A, the
  efficiency-split round-trip identity to `CLOSURE_TOL`, SoC derivation, fuse derivation,
  check 11 per-condition blocking with field keys, check 12 warn-not-block, forced
  `economic_guard`, forced-null `pv_coupling`, offerability without PV. Extended for the
  review with: post-construction mutation of every derived quantity, the forced invariants
  under mutation and without any `validate()` call, the raw-value round trip, the aliasing
  case, construction with None/str/nan/inf, exact-vs-display caps (including 3×16 A, the
  case that rounds down), and the corrected error keys.

## Obstacles

* The forced invariants and the copy interact: `_force_invariants` writes to the
  sub-objects, which is what made the aliasing (D2) possible in the first place. Copying in
  `__post_init__` resolves both — the forcing has its own object to write to.
* Suppressing the D3 error cascades required threading "was this field already reported as
  non-numeric?" through the range checks. Done with a local `numeric(name)` predicate over a
  set built by the first pass, rather than by reordering the checks.

## Current status

Complete, with the adversarial review's five defects fixed. Not committed (orchestrator
commits). No persistence and no UI wiring — Phase 6.

Test counts: `tests/test_simconfig.py` 75 → 126; full suite 220 passed / 2 skipped → 271
passed / 2 skipped. No test outside `test_simconfig.py` changed or broke.

Left for Phase 6 to consume, not built here: `max_import_kw_display` /
`connection_capacity_kw_display()` exist and are tested, but nothing calls them yet — panel
②'s formatter is their intended and only consumer.
