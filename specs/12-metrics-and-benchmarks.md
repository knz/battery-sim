# 6.11–6.12 Metrics and the perfect-foresight benchmark

> **Purpose:** the headline figures derived from the four runs, and the upper bound that
> makes them interpretable.
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

self_consumption = 1 - export.sum() / pv.sum()          # per scenario
self_sufficiency = 1 - import.sum() / load.sum()        # per scenario

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

**SoC drift correction.** The battery does not end the window at its starting SoC. Report
`soc_end − soc_start` and value it at the median import price; if it exceeds 2% of the
headline saving, surface it. Without this, a policy that simply ends the year empty looks
better than it is.

## 6.12 Perfect-foresight benchmark

An upper bound obtained by dynamic programming over discretised SoC. Its only purpose is
to make the headline number interpretable: "€331" means little; "€331 of a theoretical
€478" means a great deal.

```python
def perfect_foresight(frame, cfg, n_soc=101, n_actions=41):
    soc_levels = linspace(cfg.soc_min_kwh, cfg.soc_max_kwh, n_soc)
    V          = zeros(n_soc)

    # Terminal constraint: must finish at or above the starting SoC.
    # Without it the DP simply liquidates the battery and inflates the bound.
    V[soc_levels < cfg.initial_soc_kwh - EPS] = +INF

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

Complexity `O(T · n_soc · n_actions)` ≈ 8,760 × 101 × 41 ≈ 36M vectorised operations —
a few seconds in numpy. Interpolation of `V` rather than snapping to the nearest SoC level
avoids a systematic pessimism bias of several percent.

The DP obeys the same power, SoC and connection limits, and the same standby draw, so the
comparison is like-for-like. It does **not** obey the user's price bands — that is the
point. Whether it should also inherit `allow_grid_export` is
[open question §8.2](17-open-questions.md).

`perfect_foresight_saving ≥ policy_saving` for every configuration is a strong invariant
and catches most policy and pricing errors — fixture 6 in
[16-validation-harness.md](16-validation-harness.md). Note also
[§7.2](15-data-quality-and-limits.md#72-known-modelling-limitations--state-these-in-the-ui-not-just-here)
item 6: the capture ratio is a floor on achievable improvement, not a target, because no
real controller knows every future price.
