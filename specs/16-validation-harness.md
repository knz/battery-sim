# 6.14 Validation harness

> **Purpose:** the fixtures the implementation must reproduce exactly. Write these first —
> they are cheap, and several of them catch whole classes of error that are otherwise
> invisible in plausible-looking output.
> **Audience:** backend, QA.
> **Read with:** whichever file each fixture targets; links are given per item.

The domain layer is pure by design ([§5.2](08-architecture.md#52-why-this-split)), which
is what makes these fixtures possible: each is arrays in, numbers out, no I/O and no
clock.

1. **Trivial** — flat 1 kW load, no PV, flat price, P2/D2 with disjoint bands. Cycles,
   throughput and cost are analytically computable.
   → [§6.6–6.7](11-policies-and-battery.md#66-charge-policy)
2. **Efficiency** — one charge and one discharge of a 10 kWh battery at 90% RTE returns
   9.0 kWh AC. Round-trip loss is 1.0 kWh, not 0.9 or 1.11.
   → [§6.8](11-policies-and-battery.md#68-battery-step-function)
3. **Conservation** — for every run, `Σ(pv + imp + dis) == Σ(load + exp + chg) ± 1e-6`.
   → [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction),
   [§6.8](11-policies-and-battery.md#68-battery-step-function)
4. **Waterfall closure** — `Σ(waterfall) == cost(A) − cost(C) − degradation ± 1e-6`.
   → [§6.10](10-pricing.md#610-cost-accounting)
5. **Monotonicity** — larger capacity never reduces savings, all else equal. Violation
   indicates a clamping bug.
   → [§6.8](11-policies-and-battery.md#68-battery-step-function)
6. **Bound** — perfect-foresight saving ≥ every policy saving, for every configuration.
   This is a strong invariant and catches most policy and pricing errors.
   → [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)
7. **DST** — a window spanning both the March and October transitions has 8,760 ± 1 hourly
   intervals with no duplicated or dropped index entries.
   → [§4.1](05-data-formats.md#column-rules); see also
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
    `detect_time_offset` to within one interval, with confidence above 3.0.
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
    waterfall line. Fixture 4's closure must still hold to ±1e-6 with the top-up nonzero.
    → [§6.10](10-pricing.md#610-cost-accounting)
15. **Single-tariff register** — a window in which T2 never increments is priced entirely
    from the normaal rate, raises no gap or missing-series warning, and suppresses the
    §6.4(b) zone-mismatch check rather than reporting 100% mismatch.
    → [§6.4](09-ingest-algorithms.md#64-tariff-register-identification-and-zone-assignment)
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
