# 6.14 Validation harness

> **Purpose:** the fixtures the implementation must reproduce exactly. Write these first —
> they are cheap, and several of them catch whole classes of error that are otherwise
> invisible in plausible-looking output.
> **Audience:** backend, QA.
> **Read with:** whichever file each fixture targets; links are given per item.

The domain layer is pure by design ([§5.2](08-architecture.md#52-why-this-split)), which
is what makes these fixtures possible: each is arrays in, numbers out, no I/O and no
clock.

Conservation and closure identities are asserted to `CLOSURE_TOL` (a module constant,
`1e-6`), the floating-point slack below which a sum-of-parts identity counts as exact.

1. **Trivial** — flat 1 kW load, no PV, flat price, P2/D2 with disjoint bands. Cycles,
   throughput and cost are analytically computable.
   → [§6.6–6.7](11-policies-and-battery.md#66-charge-policy)
2. **Efficiency** — one charge and one discharge of a 10 kWh battery at 90% RTE returns
   9.0 kWh AC. Round-trip loss is 1.0 kWh, not 0.9 or 1.11.
   → [§6.8](11-policies-and-battery.md#68-battery-step-function)
3. **Conservation** — for every run, `Σ(pv + imp + dis) == Σ(load + exp + chg) ± CLOSURE_TOL`.
   → [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction),
   [§6.8](11-policies-and-battery.md#68-battery-step-function)
4. **Waterfall closure** — `Σ(waterfall) == cost(A) − cost(C) − degradation ± CLOSURE_TOL`.
   Assert it on a run where all six per-interval lines are nonzero, so the identity cannot
   pass on a degenerate case, and additionally on a run where the **standby difference
   itself** moves the feed-in floor across zero — that is the only shape that distinguishes
   a standby line taken on the pre-top-up bills from one taken on the full bills
   ([§6.10](10-pricing.md#standby-is-a-per-interval-term-so-it-is-taken-on-the-pre-top-up-bills)).
   A window in which the floor merely binds in run A passes under both readings.
   → [§6.10](10-pricing.md#610-cost-accounting)
5. **Monotonicity** — larger capacity never reduces savings, all else equal. Violation
   indicates a clamping bug.
   → [§6.8](11-policies-and-battery.md#68-battery-step-function)
6. **Bound** — perfect-foresight saving ≥ every policy saving, for every configuration.
   This is a strong invariant and catches most policy and pricing errors. Assert it
   **within** each benchmark block, in that block's own units:
   `benchmarks.energy.perfect_foresight_saved_kwh ≥ policy_saved_kwh` in every run, and
   `benchmarks.cost.perfect_foresight_eur ≥ policy_eur` whenever cost is simulated. Do not
   compare across the two blocks — the cost-optimal dispatch routinely avoids *less* import
   than the import-optimal one, so asserting the bound across them would fail
   correctly-built code.

   **Assert it on drift-corrected figures**, per
   [§6.12](12-metrics-and-benchmarks.md#the-terminal-constraint-makes-the-two-sides-asymmetric--compare-them-drift-corrected):
   the DP must finish at or above its starting SoC and the policy run need not, so a policy
   that liquidates its opening charge books a saving the benchmark is forbidden to match and
   the raw comparison fails on correct code. Correct both sides by
   `saved + soc_delta_kwh × eta_d` before comparing. The literal uncorrected form is worth
   asserting *as well*, but only over configurations where the policy's drift is
   non-negative. Carry a slack of order 0.03 kWh for the DP's residual discretisation error
   (§6.12) rather than demanding exactness.

   Two further checks on the export baselines (§6.12): where the `*_unconstrained` fields
   are present, `perfect_foresight_*_unconstrained ≥ perfect_foresight_*` in the block's own
   units, since the unconstrained DP optimises over a superset of actions; and when
   `allow_grid_export` is on, the `*_unconstrained` fields are `null` (no second DP runs
   because it would be identical). With export off they are present and satisfy the strict
   bound above.
   → [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)
7. **DST** — a window spanning both the March and October transitions has 8,760 ± 1 hourly
   intervals with no duplicated or dropped index entries.
   → [§4.2](05-data-formats.md#column-rules); see also
   [open question §8.8](17-open-questions.md)
8. **Reset** — a synthetic register that resets to 0 mid-window yields the correct total.
   → [§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas)
9. **Epoch** — a synthetic window with PV switched on at the midpoint yields exactly two
   epochs with the correct boundary date, and per-epoch savings that sum to the aggregate.
   → [§6.15](13-configuration-epochs.md)
10. **Bracket ordering** — `saved_low ≤ saved_central ≤ saved_high` for every configuration
    where a bracket applies. Violation means charge and discharge price arrays were
    swapped.
    → [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)
11. **Offset recovery** — a series shifted by a known lag is recovered by
    `detect_time_offset` to within one interval, with confidence above
    `TIME_OFFSET_CONFIDENCE_MIN`.
    → [§6.17](14-diagnostics.md#617-timestamp-misalignment-detection)
12. **Phase approximation** — selecting an unsupported phase topology and continuing sets
    `topology.approximated = true` and produces results identical to the 3-phase case
    (the approximation *is* the 3-phase model).
    → [§2.5](03-topology-selector.md#b-battery-phase-configuration)
13. **Feed-in floor ordering** — over identical data with identical `(α, β)`, feed-in
    compensation revenue under `feedin_floor_mode = MONTHLY` is ≤ the revenue under
    `PER_INTERVAL`, with equality iff no interval has negative unclamped compensation.
    A violation means the clamp and the aggregate have been transposed. Construct the
    strict case with at least one negative-price interval carrying nonzero export.
    → [§6.5](10-pricing.md#the-feed-in-floor-is-a-period-aggregate-not-a-per-interval-clamp)
14. **Feed-in floor binding** — a synthetic month whose export earns a net negative
    unclamped amount yields exactly zero compensation revenue for that month under
    `MONTHLY`, and the shortfall appears in `feedin_floor_topup`, not in any other
    waterfall line. Fixture 4's closure must still hold to ±`CLOSURE_TOL` with the top-up nonzero.
    → [§6.10](10-pricing.md#610-cost-accounting)
15. **Incomplete register set** — a window in which T2 never increments yields
    availability `INCOMPLETE`, raises the check 8a installation warning, raises no gap or
    missing-series warning, does **not** block the run, is priced entirely from the normaal
    rate, and skips both `detect_dal_register` and the check 8b zone-mismatch test rather
    than reporting `UNCERTAIN` or a 100% mismatch. Assert additionally that the energy
    results are identical to the same data with the import split across two active
    registers — register partitioning must not reach the flow simulation at all.
    → [§6.4](09-ingest-algorithms.md#64-tariff-registers--availability-identification-and-use)
16. **No-PV arbitrage** — `has_pv = false`, no `solar_production` series, flat 1 kW load,
    and a square-wave price alternating daily between a low inside band `[A,B]` and a high
    inside band `[C,D]`. With P2/D2 the battery performs exactly one full cycle per day and
    the saving is analytically computable from the spread, the round-trip efficiency and
    the standby draw. Assert additionally that `reconstruct_load` returned `import −
    export` unmodified, that `ratios.self_consumption_*` are `null` rather than 0,
    that `topology.pv_coupling` is `null`, and that the run raises no missing-series
    warning for the absent solar sensor.
    → [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction),
    [§6.6–6.7](11-policies-and-battery.md#66-charge-policy),
    [§6.11](12-metrics-and-benchmarks.md#611-metrics)
17. **PV-invariance of the core** — the same input run twice, once with `has_pv = true` and
    an all-zero `solar_production` series, once with `has_pv = false` and no series at all,
    produces identical energy and cost figures. Only the nullable diagnostic and ratio
    fields may differ. This pins the decision that the numeric core takes no `has_pv`
    branch ([§4.4](07-internal-representation.md#44-internal-normalised-representation)).
    → [§6.8](11-policies-and-battery.md#68-battery-step-function)

18. **Cost-invariance of the energy results** — the same input run twice, once with
    `simulate_cost = true` and a full contract configuration, once with
    `simulate_cost = false`, produces **bit-identical** `window`, `series`, `energy`,
    `ratios`, `battery` (excluding `soc_delta_value_eur`), `benchmarks.energy`, `epochs`,
    `topology` and `diagnostics` (excluding the cost-only fields listed in §4.5) blocks, and
    an identical per-interval SoC trace. This is the central invariant of the optional-cost design: the
    cost model prices the flows, it never changes them, and it never changes what the flows
    are measured against either. Assert every block named above, not a sample — each of the
    three known ways to break this lands in a different one. A failure in `energy` or the
    SoC trace means a cost term has leaked into the dispatch path, most likely
    `economic_guard`, which must be forced off rather than left reading an absent
    `p_export_net`. A failure in `benchmarks.energy` means the perfect-foresight DP is being
    retargeted at euros instead of a second DP being added. A failure in `diagnostics` means
    §6.13 is selecting its basis from `simulate_cost` instead of always measuring kWh.
    → [§6.6–6.7](11-policies-and-battery.md#66-charge-policy),
    [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark),
    [§6.13](14-diagnostics.md#613-resolution-bias-diagnostic),
    [§4.5](07-internal-representation.md#shape-of-the-object-without-cost-simulation)

19. **Energy-only result shape** — a run with `simulate_cost = false` yields `cost`,
    `benchmarks.cost`, `price_bracket`, `battery.soc_delta_value_eur`,
    `monthly[].saved_eur` and `diagnostics.resolution_bias_pct_eur` all `null` — never
    `0.0` — while `benchmarks.energy` is fully populated. The exported per-interval CSV
    omits `p_import_eur_kwh`, `p_export_net_eur_kwh`, `base_cost_eur` and `batt_cost_eur`
    from its header entirely, and retains `spot_eur_kwh`. Assert the run raises no
    missing-series warning for absent contract configuration, and that
    `diagnostics.resolution_bias_pct` is populated rather than `None`.
    → [§4.5](07-internal-representation.md#shape-of-the-object-without-cost-simulation),
    [§4.6](07-internal-representation.md#46-per-interval-csv-export),
    [§6.13](14-diagnostics.md#613-resolution-bias-diagnostic)

20. **The cost-objective DP is a second run, not a retargeted one** — with
    `simulate_cost = true`, a square-wave price alternating daily between a low inside band
    `[A,B]` and a high inside band `[C,D]`, and a flat load: `benchmarks.cost` bounds the
    policy run on euros, `benchmarks.energy` bounds it on kWh, and the two DP dispatch
    traces are *not* identical. The last part is the point — if the two objectives produce
    the same trace, only one DP is really running and `transition_cost` is returning euros
    for both. Assert additionally that `benchmarks.energy` over this data is bit-identical
    to the same run with `simulate_cost = false`, which is what distinguishes "a cost
    benchmark was added" from "the benchmark was re-aimed".
    → [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)

21. **Mixed native resolutions** — hourly energy series and a 15-minute `price_spot` over
    the same window. Assert that the simulation grid is hourly (`window.dt_hours == 1.0`),
    that `series` reports `native_resolution_s` of 3600 for the energy series and 900 for
    the price series, that the price series' `reconciliation` is `"averaged"` while the
    energy series' is `"exact"`, and that `diagnostics.price_granularity_lost` is `true`
    with `price_native_resolution_s == 900`. The grid assertion is the load-bearing one: a
    selector that let the price series vote would pick 900 s and then have to upsample
    energy, which §6.2 forbids. Assert additionally that the hourly `spot` array holds the
    arithmetic mean of each hour's four quarter-hourly prices, and that running the same
    fixture with `simulate_cost = false` leaves both diagnostics fields populated and
    unchanged — they report a dispatch fact, not a pricing one, and fixture 18's invariance
    list covers them.
    → [§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling),
    [§4.5](07-internal-representation.md#45-result-object),
    [§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order)

22. **A failed slot upload is recoverable** — fill every required slot with a valid file
    except `price_spot`, into which a file with naive timestamps (no UTC offset) is
    uploaded. Assert that the upload is rejected against that slot with an error naming the
    missing offset, that the session state is unchanged and no `LOAD_FAILED` is emitted,
    that the already-filled slots still hold their files, and that `SOURCE_CONFIGURED` has
    not fired. Then upload a well-formed `price_spot` file into the same slot and assert
    that it is accepted, replaces nothing else, and that `SOURCE_CONFIGURED` now fires and
    the run completes normally. Assert additionally that uploading a second valid file into
    an already-filled slot replaces its contents rather than appending, leaving the series
    row count equal to the second file's. The point is that a bad supplier export is a
    panel-local condition: a validation failure on one slot must not be reachable from, or
    escalate into, the session's `DATA_ERROR` state.
    → [§4.2](05-data-formats.md#validation-and-failure),
    [§2.2](02-ux-wireframes.md#csv-variant-of-the-source-sub-panel),
    [§3.2](04-state-machine.md#32-events)
