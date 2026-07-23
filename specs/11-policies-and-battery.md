# 6.6–6.9 Policies, battery step function and main loop

> **Purpose:** the sequential core of the simulator — what the policies request, what the
> battery and the connection actually allow, and how the four runs per request fit
> together.
> **Audience:** backend, domain layer.
> **Read with:** [10-pricing.md](10-pricing.md) (costs these flows),
> [12-metrics-and-benchmarks.md](12-metrics-and-benchmarks.md) (summarises them),
> [16-validation-harness.md](16-validation-harness.md) (fixtures 1–6 test this file).

Reminder: flows are non-negative magnitudes in named directions; `dt` is the interval
length in hours. **[vectorisable]** marks numpy-over-the-whole-array functions.

## 6.6 Charge policy

```python
def charge_request(policy, i, st, cfg):
    """
    Returns (kwh_from_pv_surplus, kwh_from_grid) requested this interval,
    before any physical limit is applied.
    """
    solar_surplus = max(0.0, st.pv[i] - st.load[i])

    req_pv = solar_surplus if policy in (P1, P3) else 0.0

    in_band = cfg.band_a <= st.spot[i] <= cfg.band_b
    req_grid = cfg.max_charge_kw * st.dt if (policy in (P2, P3) and in_band) else 0.0

    return req_pv, req_grid
```

- **P1** — solar surplus only. Net zero at the grid on the export side.
- **P2** — grid charging only, while `A ≤ spot ≤ B`. "Maximise" means charge at full
  rated power. Surplus solar is *not* captured under P2 alone.
- **P3** — both. PV surplus is always taken; grid charging adds on top inside the band,
  with the combined request clamped to rated power in §6.8. PV takes priority in that
  clamp because it is free and, on a DC-coupled system, more efficient.

The band is compared against the **bare EPEX spot price**, per product decision.
Note that `A` is a lower bound and exists mainly to let the user *exclude* deeply negative
prices (unusual) or, more typically, to be left at a large negative value so only `B`
binds.

**Without PV, `st.pv` is all zeros**, so `solar_surplus` is identically zero and P1 charges
nothing while P3 degenerates to P2. Neither is offered in the UI in that case
([§2.3](02-ux-wireframes.md#without-pv)); `charge_policy` is P2. The code above needs no
branch on `has_pv` — it already computes the right answer — and should not acquire one.

## 6.7 Discharge policy

```python
def discharge_request(policy, i, st, cfg):
    """Returns (kwh_to_home, kwh_to_grid) requested, before physical limits."""
    deficit = max(0.0, st.load[i] - st.pv[i])

    req_home = deficit if policy in (D1, D3) else 0.0
    req_grid = 0.0

    in_band = cfg.band_c <= st.spot[i] <= cfg.band_d
    if policy in (D2, D3) and in_band:
        full = cfg.max_discharge_kw * st.dt
        req_home = min(full, deficit)               # serve the house first
        if cfg.allow_grid_export:
            req_grid = full - req_home

    if cfg.economic_guard and st.p_export_net[i] <= 0:
        req_grid = 0.0        # never pay to export

    return req_home, req_grid
```

- **D1** — serve household deficit only. Never exports.
- **D2** — discharge only while `C ≤ spot ≤ D`, at full rated power. Outside the band the
  battery does nothing, even if the house is importing. This is intentional and literal.
- **D3** — both.

All three remain available and distinct **without PV**, where the deficit `max(0, load −
pv)` is simply the whole load: D1 discharges whenever the house draws anything, D2 only
inside the price band. D1's label changes to "serve house load" in that case
([§2.3](02-ux-wireframes.md#without-pv)) since there is no solar to exceed, but its
behaviour does not.

**The no-PV configuration to think about is P2 with D2 or D3** — buy low, sell or self-use
high. It is the only way a battery earns anything without solar, it is entirely dependent
on the spread between the charge and discharge bands clearing the round-trip loss, and it
is what the perfect-foresight benchmark in
[§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark) will beat by a wide
margin, because fixed bands are a poor approximation of a price signal that moves daily.
Expect capture ratios well below the PV case, and do not treat that as a defect in the
simulator.

`allow_grid_export` defaults **off**. Under the 2027 regime, a kWh discharged to the house
displaces `p_import` (≈ €0.25 at €0.08 spot) while a kWh exported earns `p_export_net`
(≈ €0.04–0.09 minus terugleverkosten). Home discharge is worth roughly three times as
much, and grid arbitrage generally only clears when charging happened at negative prices.
The simulator should demonstrate this rather than assume it.

**Band overlap.** If `[A,B]` and `[C,D]` intersect, charge and discharge can both fire.
Validate at config time and warn (check 12 in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order)). At
runtime, net the requests:

```python
net = (req_pv + req_grid_chg) - (req_home + req_grid_dis)
charge_total, discharge_total = (net, 0) if net > 0 else (0, -net)
```

P1/D1 can never conflict, since `max(0, pv−load)` and `max(0, load−pv)` are never both
positive.

## 6.8 Battery step function

```python
def battery_step(soc, req_pv, req_grid_chg, req_home_dis, req_grid_dis, st, i, cfg):
    dt = st.dt

    # ---- 1. resolve simultaneous charge/discharge ------------------------
    chg_req = req_pv + req_grid_chg
    dis_req = req_home_dis + req_grid_dis
    if chg_req > 0 and dis_req > 0:
        net = chg_req - dis_req
        if net >= 0:
            scale = net / chg_req; req_pv *= scale; req_grid_chg *= scale
            dis_req = 0; req_home_dis = req_grid_dis = 0
        else:
            scale = -net / dis_req; req_home_dis *= scale; req_grid_dis *= scale
            chg_req = 0; req_pv = req_grid_chg = 0

    # ---- 2. clamp charge to rated power, PV first -----------------------
    chg_ac = min(req_pv + req_grid_chg, cfg.max_charge_kw * dt)
    chg_pv   = min(req_pv, chg_ac)
    chg_grid = chg_ac - chg_pv

    # ---- 3. clamp charge to SoC headroom --------------------------------
    #   DC-coupled systems skip one inversion on the PV path.
    eta_c_pv = cfg.eta_c_dc if cfg.coupling == DC_HYBRID else cfg.eta_c
    stored   = chg_pv * eta_c_pv + chg_grid * cfg.eta_c
    headroom = cfg.soc_max_kwh - soc
    if stored > headroom:
        scale = headroom / stored
        chg_pv *= scale; chg_grid *= scale; stored = headroom

    # ---- 4. clamp discharge to rated power and available energy ---------
    dis_ac = min(req_home_dis + req_grid_dis,
                 cfg.max_discharge_kw * dt,
                 (soc - cfg.soc_min_kwh) * cfg.eta_d)
    dis_home = min(req_home_dis, dis_ac)
    dis_grid = dis_ac - dis_home
    withdrawn = dis_ac / cfg.eta_d

    # ---- 5. resulting grid flows ----------------------------------------
    #   load here already includes standby draw (added in the caller).
    net_flow = st.load[i] + chg_pv + chg_grid - st.pv[i] - dis_ac
    imp = max(0.0,  net_flow)
    exp = max(0.0, -net_flow)

    # ---- 6. connection limits -------------------------------------------
    imp_cap = cfg.max_import_kw * dt
    if imp > imp_cap:                       # shed grid charging first
        excess   = imp - imp_cap
        cut      = min(chg_grid, excess)
        chg_grid -= cut
        stored   -= cut * cfg.eta_c
        imp      -= cut
        if imp > imp_cap:
            record_warning(IMPORT_LIMIT_EXCEEDED, i)   # household load alone exceeds it

    exp_cap = cfg.max_export_kw * dt
    if exp > exp_cap:                       # shed arbitrage export, then curtail PV
        excess = exp - exp_cap
        cut    = min(dis_grid, excess)
        dis_grid -= cut; dis_ac -= cut; withdrawn -= cut / cfg.eta_d; exp -= cut
        if exp > exp_cap:
            curtailed = exp - exp_cap
            exp = exp_cap
            record_curtailment(i, curtailed)

    # ---- 7. integrate ----------------------------------------------------
    soc_new = soc + stored - withdrawn
    assert cfg.soc_min_kwh - EPS <= soc_new <= cfg.soc_max_kwh + EPS

    return soc_new, Flows(imp, exp, chg_pv, chg_grid, dis_home, dis_grid, stored,
                          withdrawn, curtailed)
```

Efficiency split convention: `eta_c = eta_d = sqrt(roundtrip_efficiency)`. The user enters
a single **AC-to-AC** round-trip figure. `eta_c_dc = sqrt(roundtrip_dc)` where
`roundtrip_dc` defaults to `roundtrip + 0.04` for DC-coupled systems, overridable. Which
of the two applies is set by the PV-coupling selector in
[§2.5](03-topology-selector.md#a-pv-coupling--always-shown).

SoC bounds: `soc_min_kwh = usable_capacity * min_soc_pct/100`,
`soc_max_kwh = usable_capacity * max_soc_pct/100`. "Usable capacity" is the full 0–100%
window the battery reports; min/max SoC are additional user-imposed operating limits
inside it.

The export limit applies to the **baseline run too** — see
[§7.2](15-data-quality-and-limits.md#72-known-modelling-limitations--state-these-in-the-ui-not-just-here)
item 1, which is easy to get wrong and must be asserted in tests.

## 6.9 Main simulation loop

```python
def simulate(frame, cfg, include_standby=True):
    n   = len(frame.index)
    soc = cfg.initial_soc_kwh
    out = Flows.empty(n)

    standby_kwh = (cfg.standby_w / 1000.0) * frame.dt if include_standby else 0.0

    st = frame.view()
    st.load = frame.load + standby_kwh       # standby exists only with a battery

    for i in range(n):
        if i % 1024 == 0 and cancel_event.is_set():
            raise Cancelled

        if isnan(st.load[i]) or isnan(st.pv[i]):
            out.mark_gap(i); continue        # gaps excluded, SoC carried forward

        rp, rg  = charge_request(cfg.charge_policy, i, st, cfg)
        dh, dg  = discharge_request(cfg.discharge_policy, i, st, cfg)
        soc, f  = battery_step(soc, rp, rg, dh, dg, st, i, cfg)
        out[i]  = f
        out.soc[i] = soc

    return out


def simulate_baseline(frame):
    """[vectorisable] No battery, no standby."""
    net = frame.load - frame.pv
    return Flows(imp=maximum(net, 0), exp=maximum(-net, 0), ...)
```

The `cancel_event` check implements the cooperative cancellation described in
[§3.3](04-state-machine.md#33-concurrency-and-run-identity) and
[§5.3](08-architecture.md#53-compute).

**Four runs per request**, which together make the cost waterfall exact rather than
approximate:

| Run | Battery | Standby | Purpose |
|---|---|---|---|
| A | no | no | Baseline |
| B | yes | no | Isolates flow effects |
| C | yes | yes | The headline result |
| D | perfect foresight | yes | Upper bound |

`standby_cost ≡ cost(C) − cost(B)` exactly. Run A is vectorised, B and C are the
sequential loop, D is the DP in
[§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark). Total ≈ 1–3 s at
hourly resolution.

The battery state is **not** reset at configuration-epoch boundaries — it is one
continuous simulation, and only the reporting is segmented. See
[§6.15](13-configuration-epochs.md#615-configuration-epochs) and
[open question §8.11](17-open-questions.md).
