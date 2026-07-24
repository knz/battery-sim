# 6.11–6.12 Metrics and the perfect-foresight benchmark

> **Purpose:** the headline figures derived from the simulation runs, and the upper bounds
> that make them interpretable.
> **Audience:** backend, domain layer.
> **Read with:** [11-policies-and-battery.md](11-policies-and-battery.md) for the runs
> `A`/`B`/`C`/`D` referenced throughout, [10-pricing.md](10-pricing.md) §6.10 for the
> waterfall, and [07-internal-representation.md](07-internal-representation.md) §4.5 for
> where these land in the result object.

## 6.11 Metrics

```python
saved_kwh  = A.imp.sum() - C.imp.sum()
saved_pct  = 100 * saved_kwh / A.imp.sum()

# Equivalent full cycles, counted on the storage side.
# Convention matters: AC-side throughput gives a figure ~5% lower.
efc = C.withdrawn.sum() / cfg.usable_capacity_kwh

# Self-consumption is undefined without PV: nothing was generated to consume.
# Report null, never 0 or 1 — both would assert something the data cannot support.
self_consumption = (1 - export.sum() / pv.sum()) if pv.sum() > DIV_GUARD_EPS else None
self_sufficiency = 1 - import.sum() / load.sum()        # per scenario; always defined

# Conversion loss = AC in - AC out - energy still sitting in the battery.
# Equivalently (charge_ac - stored) + (withdrawn - discharge_ac).
charge_ac        = (C.chg_pv + C.chg_grid).sum()
discharge_ac     = (C.dis_home + C.dis_grid).sum()
conversion_loss  = charge_ac - discharge_ac - (soc_end - soc_start)
```

The denominator of `saved_pct` is the **simulated** baseline (run A), not observed import.
The reasoning is in
[§7.1](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly) —
mixing the two information sets produces a number that is wrong in a direction nobody can
reason about.

**Energy metrics and cost metrics divide cleanly**, and the split is not obvious from the
names. It is the same line twice over: it determines which metrics are regime-dependent,
and it determines which survive when cost simulation is off.

| | Metrics | Regime-dependent? | Present without cost simulation? |
|---|---|---|---|
| **Energy** | `saved_kwh`, `saved_pct`, `efc`, `self_consumption`, `self_sufficiency`, `conversion_loss`, the energy benchmark in §6.12 | No | Yes |
| **Cost** | the waterfall ([§6.10](10-pricing.md#610-cost-accounting)), `soc_delta_value_eur`, the cost benchmark in §6.12 | Yes | No |

The energy metrics are functions of the flows alone: they do not change if the pricing
regime changes, they are valid over a window spanning 1 January 2027, and they are computed
identically whether or not costs are modelled. The cost metrics are computed under a single
regime, per [§1.3](01-product-brief.md#13-regulatory-regime--fixed-decision), and are not
computed at all when `cfg.simulate_cost` is false.

**A subset of the energy row needs no simulated battery, and is surfaced before panel ②.**
`self_sufficiency`, `self_consumption`, and the raw import/export/PV/load totals behind them are
functions of the *ingested* series and the [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction)
load reconstruction alone — they do not reference the battery capacity, the policy, or the runs
`A`/`C`. They are shown in the data summary band
([§2.3a](02-ux-wireframes.md#23a-the-data-summary-band--your-data-at-a-glance)) as soon as data
loads, describing the household as it was recorded. The one energy metric that does need the
simulated battery is `efc`, which counts *its* cycles; and `saved_kwh` / `saved_pct` compare the
`A` and `C` runs, so both belong to panel ③, not the band. Where the household already owns a
battery, note that `self_consumption` and the reconstructed `load` are net of it — the summary
band labels them so ([§2.3a](02-ux-wireframes.md#the-pre-existing-battery-and-what-net-of-your-battery-means)),
since [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) strips the existing
battery when reconstructing load.

**Cost simulation only ever adds.** Every metric in the energy row is bit-identical between
a run with `simulate_cost` off and the same run with it on; enabling the toggle appends the
cost row and touches nothing above it. This is the invariant the whole optional-cost design
rests on, and the reason §6.12 below runs *two* dynamic programs rather than retargeting
one. It is pinned by fixture 18 in
[16-validation-harness.md](16-validation-harness.md).

**SoC drift correction.** The battery does not end the window at its starting SoC. Report
`soc_end − soc_start` always, and surface the drift when it exceeds `SOC_DRIFT_WARN_FRAC`
(2%) of the energy saving. With cost simulation on, also value it at the median import price
and surface it additionally when that value exceeds `SOC_DRIFT_WARN_FRAC_EUR` (2%) of the
euro saving — a separate constant sharing the same default, since the kWh and euro bases are
independent decisions. The two tests are a union, so
enabling cost simulation can only raise the drift caveat where it was previously silent,
never withdraw it: whether the user sees the warning at all does not depend on the toggle.
Without a cost model there is no median import price, so `soc_delta_value_eur` is `null`;
the kWh figure is unaffected. The point of the correction holds in both modes — without it,
a policy that simply ends the year empty looks better than it is.

## 6.12 Perfect-foresight benchmark

An upper bound obtained by dynamic programming over discretised SoC. Its only purpose is
to make the headline number interpretable: "€331" means little; "€331 of a theoretical
€478" means a great deal. The same applies to the energy figure — "1,412 kWh saved" is
uninterpretable until it is "1,412 kWh of a possible 1,988".

**There is one benchmark per headline figure, and each is optimised for its own quantity.**
A headline is compared against the best that could have been done *at the thing the
headline measures*, which means two objectives:

| Benchmark | `transition_cost` returns | Bounds | Runs |
|---|---|---|---|
| Energy | kWh of grid import in the interval | `saved_kwh`; capture ratio in kWh | Always |
| Cost | EUR spent in the interval | `saved_eur`; capture ratio in euros | Only when `cfg.simulate_cost` |

Both are well-formed minimisation problems over the same state space, the same action set
and the same feasibility constraints, so the DP below, its terminal constraint and its
interpolation serve both unchanged — only `transition_cost` differs. They land in the
result object as two sibling blocks, `benchmarks.energy` and `benchmarks.cost`, the latter
`null` in an energy-only run
([§4.5](07-internal-representation.md#45-result-object)).

**Why two runs rather than one retargeted run.** The two objectives generally have
*different* optima: a cost-optimal dispatch does not minimise import, because it will
happily import more during cheap hours. A single DP whose objective followed
`cfg.simulate_cost` would therefore hand the energy section a different ceiling — and a
different capture ratio — depending on whether the user had asked for euros, which would
make a kWh figure move for a reason that has nothing to do with the household's battery.
Running both keeps the energy benchmark identical across the toggle and gives the cost
benchmark a ceiling that is actually optimal for euros. The second DP costs a few seconds
([§6.9](11-policies-and-battery.md#69-main-simulation-loop), run E) and buys the invariant.

The energy objective is not a degraded substitute for the cost one. Minimising grid import
is a coherent goal in its own right — it is what a household optimising for
self-sufficiency rather than for money would want — and the capture ratio it produces is a
real measurement in every run, not a placeholder for the euro figure.

```python
def perfect_foresight(frame, cfg):        # n_soc = cfg.dp_soc_levels, n_actions = cfg.dp_action_levels
    n_soc, n_actions = cfg.dp_soc_levels, cfg.dp_action_levels
    soc_levels = linspace(cfg.soc_min_kwh, cfg.soc_max_kwh, n_soc)
    V          = zeros(n_soc)

    # Terminal constraint: must finish at or above the starting SoC.
    # Without it the DP simply liquidates the battery and inflates the bound.
    V[soc_levels < cfg.initial_soc_kwh - SOC_COMPARE_EPS_KWH] = +INF

    policy = zeros((len(frame), n_soc), dtype=int8)

    for i in reversed(range(len(frame))):
        # action = signed AC power, negative = charge, positive = discharge
        actions = linspace(-cfg.max_charge_kw, cfg.max_discharge_kw, n_actions) * frame.dt
        # [vectorisable] over (n_soc x n_actions)
        soc_next, cost = transition_cost(soc_levels[:, None], actions[None, :],
                                         frame, i, cfg)
        Vn   = interp(soc_next, soc_levels, V)      # linear interpolation
        tot  = cost + Vn
        tot[~feasible(soc_next, cfg)] = +INF
        V         = tot.min(axis=1)
        policy[i] = tot.argmin(axis=1)

    return roll_forward(policy, frame, cfg)
```

Complexity `O(T · n_soc · n_actions)` ≈ 8,760 × `dp_soc_levels` × `dp_action_levels`
(≈ 8,760 × 101 × 41 ≈ 36M at the default levels) vectorised operations —
a few seconds in numpy. Interpolation of `V` rather than snapping to the nearest SoC level
avoids a systematic pessimism bias of several percent.

The DP obeys the same power, SoC and connection limits, and the same standby draw, so the
comparison is like-for-like. It does **not** obey the user's price bands — that is the
point.

**Both export baselines are computed, not one.** Rather than pick whether the DP inherits
`allow_grid_export` — [open question §8.2](17-open-questions.md) — each benchmark is run
under both readings and both bounds land in the result object, so accumulated runs supply
the answer §8.2 was asking a person to guess ([experiment X10](19-prototype-experiments.md#x10--does-the-benchmarks-export-permission-matter)):

- **inheriting** — the DP plays by the same export permission the user's policy plays by,
  so the capture ratio measures decision quality alone. This is the primary figure.
- **unconstrained** — the DP may always export, so the bound is the true physical maximum
  and the capture ratio also absorbs the cost of the user's export setting.

When `allow_grid_export` is **on** the two readings coincide by construction, so only the
inheriting DP runs and the unconstrained fields are `null` — the second pass is skipped
because it is provably identical, not merely similar. When it is **off** — the default —
the second DP runs, differing only in that `feasible()` permits grid export. That is the
one case where the two bounds can diverge, and the case X10 measures. The extra pass costs
what one DP costs (§6.12 complexity above), and only in the export-off case.

`perfect_foresight_saving ≥ policy_saving` for every configuration is a strong invariant
and catches most policy and pricing errors — fixture 6 in
[16-validation-harness.md](16-validation-harness.md). Assert it **within** each benchmark
block, in that block's own units: the energy DP cannot be beaten on kWh of import avoided,
and the cost DP cannot be beaten on euros. Asserting it across the two blocks is
meaningless and will fail correctly-built code, since the cost-optimal dispatch routinely
avoids less import than the import-optimal one.

A second invariant governs the two export baselines within a block:
`unconstrained_saving ≥ inheriting_saving`, in that block's units, because the
unconstrained DP optimises over a superset of the inheriting DP's action set. Assert it
whenever the unconstrained figure is present. When `allow_grid_export` is on the two are
equal by construction and the unconstrained fields are `null`, so the assertion is on
equality-or-null there, strict `≥` only in the export-off case.

Note also
[§7.2](15-data-quality-and-limits.md#72-known-modelling-limitations--state-these-in-the-ui-not-just-here)
item 6: the capture ratio is a floor on achievable improvement, not a target, because no
real controller knows every future price.
