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
`A`/`C`. They are shown in the data summary section inside panel ①
([§2.3a](02-ux-wireframes.md#23a-the-data-summary--your-data-at-a-glance)) as soon as data
loads, describing the household as it was recorded. The one energy metric that does need the
simulated battery is `efc`, which counts *its* cycles; and `saved_kwh` / `saved_pct` compare the
`A` and `C` runs, so both belong to panel ③'s savings section, not the data summary. Where the household already owns a
battery, note that `self_consumption` and the reconstructed `load` are net of it — the summary
section labels them so ([§2.3a](02-ux-wireframes.md#the-pre-existing-battery-and-what-net-of-your-battery-means)),
since [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) strips the existing
battery when reconstructing load. In that same existing-battery case `self_sufficiency` can be
negative over a finite window — import exceeds load when the battery ends more charged than it
started, or through round-trip losses — so the summary **display-clamps** it to `max(0, ·)` and shows
a caveat; the metric itself is unchanged, only its presentation
([§2.3a](02-ux-wireframes.md#23a-the-data-summary--your-data-at-a-glance)). When instead the
§6.3 negative-load clamp has discarded a *large* share of the load — export the reconstruction
cannot account for, usually an under-reporting PV sensor or an unmapped battery — `load` and hence
`self_sufficiency` and `consumption` are not trustworthy; the summary suppresses those two and warns,
keeping only the measured grid/price figures ([§2.3a](02-ux-wireframes.md#when-an-input-is-empty-or-the-reconstruction-is-unreliable-say-so)).

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
a few seconds in numpy.

**Interpolate `V`; do not snap to the nearest SoC level.** Snapping rounds a landing SoC
*upward* about as often as downward, and an upward round credits the battery with energy it
does not have — a small leak at every transition that compounds over the window. The result
is **optimistic, not conservative**, and it converges upward as the grid refines rather than
settling. Measured on one fixture (realised dispatch 27.64 kWh):

| `dp_soc_levels` | snapping | interpolation |
|---|---|---|
| 11 | 9.41 | ~27.56 |
| 21 | 17.41 | 27.59 |
| 101 | 26.26 | ~27.56 |
| 401 | 27.13 | ~27.56 |

Interpolation is stable from 11 levels on; snapping is still 0.5 kWh short at 401. The
practical point is that a snapped figure sits *below* the realised saving, so it **bounds
nothing** — the one thing this run exists to do. Do not treat snapping as the cheap
conservative option; it is neither.

> Earlier drafts of this file described the snapping error as "a systematic pessimism bias
> of several percent". That was wrong in both direction and magnitude, and it was corrected
> from measurement during implementation.

**Two things the pseudocode above leaves out, both needed for the bound to hold.** Each was
found by measuring a DP that came out *below* a policy run it is supposed to bound:

- **The starting SoC must be on the state grid.** A plain `linspace` over
  `[soc_min_kwh, soc_max_kwh]` almost never contains `cfg.initial_soc_kwh`, which is the
  value the terminal constraint is stated against — so the DP has to charge before it can
  act, and returns a bound worse than standing still. Move the nearest level onto the
  starting SoC (leaving the endpoints alone, so the grid still spans the window).
- **The action grid must be able to represent the actions the policies take.** A uniform
  `linspace` over `[−max_charge_kw, +max_discharge_kw]` cannot generally express the exact
  PV surplus or the exact household deficit that §6.6/§6.7 dispatch on, so the DP loses to
  a P1/D1 policy by a few percent. Append both exact points to the action set per interval,
  clipped to the rated powers. This strictly enlarges the set the DP minimises over, so it
  cannot itself break the bound — provided the forward pass uses the same per-interval set
  as the backward pass.

A residual discretisation error remains — "finish exactly at the starting SoC" is
state-dependent and cannot share a single action row. It is small (0.025 kWh at the default
41 action levels, shrinking to 0.003 at 321) and always in the conservative direction, so
assertions of the bound should carry a slack of that order rather than demand exactness.

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

### The terminal constraint makes the two sides asymmetric — compare them drift-corrected

The DP must finish at or above its starting SoC. **Nothing imposes that on the policy run**,
and [§6.11](#611-metrics) deliberately reports SoC drift rather than netting it out. So a
policy that ends emptier than it started books grid import avoided that it funded from its
*opening charge* rather than earned by dispatch — a move the benchmark is forbidden. The raw
comparison is then between a drift-funded figure and a drift-neutral one, and
`perfect_foresight_saving ≥ policy_saving` can fail **with no defect anywhere**.

This is reachable, not theoretical. A no-PV D1 policy over 48 flat hours drains its opening
5 kWh to the floor and books **+2.35 kWh** of "saving" against a drift of −4.0 kWh. A 20 kWh
battery started at 100% over 96 intervals books **+14.20 kWh** against a bound of −2.88.

So state the invariant on a comparable basis. Correct **both** sides for drift before
asserting:

```python
comparable_saving = saved_kwh + soc_delta_kwh * cfg.eta_d
```

`soc_delta_kwh` is `soc_end − soc_start` (negative when the run ended emptier). The `eta_d`
factor converts the stored residual to the AC side, which is the side `saved_kwh` is measured
on. The DP's own correction is normally zero — that is what its terminal constraint buys —
so this is even-handed rather than a thumb on the scale.

**This changes no reported figure.** §6.11's drift metric stays exactly as specified,
unnetted, and so does `saved_kwh`. What is corrected is the *comparison*, and the capture
ratio derived from it ([§2.4](02-ux-wireframes.md#24-panel--results-expanded) gives the
presentation rule) — a ratio whose denominator is already drift-constrained by the terminal
constraint above.

> This asymmetry was not addressed in earlier drafts: §6.12 constrained the DP's endpoint
> and said nothing about the policy run's. Added from implementation, where fixture 6 failed
> on correct code.

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
