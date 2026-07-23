# 6.1–6.4 Ingest and normalisation algorithms

> **Purpose:** turning raw meter registers into a clean `SimulationFrame` — deltas and
> resets, choice of simulation grid, household load reconstruction, tariff registers.
> **Audience:** backend, domain layer.
> **Read with:** [05-data-formats.md](05-data-formats.md) and
> [06-home-assistant-ingestion.md](06-home-assistant-ingestion.md) upstream,
> [07-internal-representation.md](07-internal-representation.md) §4.4 for the output
> types, [10-pricing.md](10-pricing.md) downstream.

Reminder of the conventions: energy in kWh, timestamps UTC, `dt` in hours, flows are
non-negative magnitudes in named directions. **[vectorisable]** marks functions that
should run in numpy over the whole array.

## 6.1 Cumulative meter register → interval deltas

```python
def cumulative_to_delta(ts, values):
    """
    Meter registers are total_increasing. They reset on meter replacement,
    integration reload, or sensor unavailability. A naive diff() turns a reset
    into a large negative spike; a naive clip(0) turns it into a lost interval
    but a *rollover* into a spurious huge positive one. Both are wrong.
    """
    d = diff(values)                       # length n-1, aligned to interval start
    flags = zeros_like(d, dtype=uint16)

    for i where d[i] < 0:
        drop = -d[i]
        if drop < RESET_TOLERANCE_KWH:     # 0.01 — float noise / rounding
            d[i] = 0
        elif values[i+1] < RESET_FLOOR_KWH:  # 1.0 — register restarted near zero
            # Genuine reset: energy consumed since the reset is the new reading.
            d[i] = values[i+1]
            flags[i] |= RESET_CORRECTED
        else:
            # Ambiguous: register went backwards but not to zero. Do not guess.
            d[i] = 0
            flags[i] |= RESET_CORRECTED
            record_warning(AMBIGUOUS_REGISTER_DECREASE, ts[i], drop)

    return d, flags

# NOTE: when ingesting from HA's `statistics_during_period`, prefer the `sum`
# column, which HA has already reset-corrected. Apply this function only to
# CSV input and to raw `state` series.
```

Gap handling: if `ts[i+1] - ts[i]` exceeds 1.5× the nominal resolution, the interval is a
**gap**. Gaps are *not* interpolated for energy; they are emitted as `NaN` and excluded
from all sums, with their duration reported. Interpolating a 6-hour outage invents a load
profile and quietly changes the answer. Prices, by contrast, are forward-filled (a price
is a step function that genuinely persists).

## 6.2 Simulation grid selection and resampling

```python
def choose_grid(series_frames, window):
    energy_series = [s for s in series_frames if s.kind == "energy"]
    resolutions = [s.resolution_s for s in energy_series
                   if s.covers(window)]

    # Coarsest wins. Downsampling energy (summing deltas) is exact.
    # Upsampling would require assuming a within-interval profile: forbidden.
    return max(resolutions)

def resample_energy(frame, target_s):
    assert target_s >= frame.resolution_s, "never upsample energy"
    if target_s == frame.resolution_s:
        return frame
    return frame.resample(target_s).sum()        # exact  [vectorisable]

def resample_price(frame, target_s):
    if target_s >= frame.resolution_s:
        return frame.resample(target_s).mean()   # energy-unweighted; see note
    return frame.reindex(target_index).ffill()   # step function: safe to upsample
```

> **Note on price downsampling.** Averaging 4×15-minute prices into an hourly price is
> only exact if consumption within the hour is uniform. It is not. Where 15-minute prices
> exist but energy is hourly, the correct move is to keep the *hourly* grid but flag that
> price granularity has been lost — the simulator cannot exploit intra-hour spreads it
> cannot observe in the energy data. Record this in `diagnostics`. The magnitude of the
> resulting pricing error is bounded in
> [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch).

In practice the coarsest resolution will almost always be hourly, because hourly is what
survives: Home Assistant's long-term statistics are hourly and never purged, while
5-minute short-term statistics default to about ten days' retention, and the P1 port
carries no history at all
([background E1.5](18-dutch-electricity-background.md#e15-the-p1-port-and-data-resolution)).
Design for hourly as the normal case and treat finer grids as the exception.

One grid is chosen for the **whole window**. Mixing 5-minute and hourly within a single
run would make the battery's behaviour resolution-dependent mid-run and the results
internally incomparable. How much the chosen grid costs in accuracy is measured by
[§7.1](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly)
and [§6.13](14-diagnostics.md#613-resolution-bias-diagnostic).

## 6.3 Household load reconstruction

A Dutch smart meter measures only what crosses the grid connection
([background E1.1](18-dutch-electricity-background.md#e11-the-single-most-important-fact)).
Everything generated and consumed behind the meter is invisible to it. Household
consumption must therefore be reconstructed from the meter plus whatever independent
behind-the-meter sources exist.

Energy balance at the AC bus over one interval — every term a non-negative magnitude, and
each of the behind-the-meter terms present only if that equipment exists:

```
pv + import + battery_discharge  =  load + export + battery_charge
```

therefore

```python
def reconstruct_load(imp, exp, pv=None, batt_chg=None, batt_dis=None):
    """[vectorisable] Returns the battery-free, standby-free household load."""
    load = imp - exp
    if pv is not None:                       # no PV: load is the meter alone
        load = load + pv
    if batt_chg is not None:                 # strip an existing battery
        load = load + batt_dis - batt_chg

    negative = load < 0
    if negative.any():
        record_warning(NEGATIVE_LOAD, count=negative.sum(),
                       pct=100 * negative.mean())
        load = maximum(load, 0)              # clamp, flag, do not silently absorb
        flags[negative] |= CLAMPED_NEGATIVE

    return load, flags
```

**Without PV the reconstruction is nearly trivial** — `load = import − export` — and its
accuracy is correspondingly better, because the dominant error source in the PV case is
the disagreement between two independently-clocked, independently-scaled sensors. A no-PV
household has one source of truth. This is worth stating in the UI: the caveats that
qualify a PV household's headline figure largely do not apply.

Negative reconstructed load is always a data problem, never physics, but **what it
indicates differs sharply between the two cases** and the UI must say the right thing:

- **With PV.** Likely causes, in order of frequency: the PV sensor measures only part of
  the array or sits behind a sub-meter; a clock offset between the P1 meter and the
  inverter integration; sign convention inverted on an export sensor; or an existing
  battery whose sensors were not mapped.
- **Without PV**, negative load means `export > import` over the interval — the meter
  recorded net export from a household that has declared it has no generator. Two of the
  causes above are excluded by construction, which makes the remaining ones much more
  likely: undeclared PV (the household has solar and answered the panel ② question wrong,
  or a housemate's array is on the same connection), an undeclared battery discharging to
  the grid, or an inverted export sensor. Anything beyond a handful of intervals should be
  treated as a probable misconfiguration and put to the user as such, not clamped quietly.
  This is check 6b in
  [§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order).

In both cases the UI must say what happened rather than presenting a clamped series as
clean.

If `house_load` is supplied directly, use it, and report
`max|load_supplied − load_reconstructed|` as a consistency check.

Two related failure modes are handled elsewhere: a clock offset is detected in
[§6.17](14-diagnostics.md#617-timestamp-misalignment-detection) — by a method that needs a
PV signal, so a different one applies without PV — and a battery or PV array whose sensors
were never mapped in
[§6.15](13-configuration-epochs.md#615-configuration-epochs). This function also assumes
**AC-side** battery measurements — see
[§7.2](15-data-quality-and-limits.md#72-known-modelling-limitations--state-these-in-the-ui-not-just-here)
item 2 for what goes wrong otherwise.

## 6.4 Tariff register identification and zone assignment

Two related but distinct problems.

**(a) Which register is dal?** The near-universal convention is T1 = normaal and T2 = dal,
but it is a convention rather than a guarantee and inverted installations exist
([background E1.3](18-dutch-electricity-background.md#e13-t1-and-t2--do-not-assume-which-is-which)).
Detect it from the data rather than trusting the labels:

```python
def detect_dal_register(import_t1, import_t2, index_local):
    """Whichever register accrues predominantly at night is the dal register."""
    night = (index_local.hour >= 23) | (index_local.hour < 7)
    share_t1 = import_t1[night].sum() / max(import_t1.sum(), EPS)
    share_t2 = import_t2[night].sum() / max(import_t2.sum(), EPS)
    if abs(share_t1 - share_t2) < 0.2:
        return UNCERTAIN            # ask the user
    return T2 if share_t2 > share_t1 else T1
```

**Single-tariff contracts: a permanently empty second register is valid data.** The
registers track the *tariff* clock, not the physical clock. A household on a single-tariff
contract may accumulate everything in T1 regardless of time of day, leaving T2 at zero for
the entire window. This must not be treated as a missing series, a stalled sensor or a gap:

```python
if import_t2 is not None and import_t2.max() - import_t2.min() < EPS:
    single_tariff = True          # valid; not a data fault
    # Do not run detect_dal_register: with no T2 accrual it returns UNCERTAIN
    # and would send the user to a question that has no answer.
    # Price the whole window from the normaal rate; suppress the §6.4(b)
    # mismatch check, which is meaningless with one register.
```

Note this is distinct from the meter simply having one register, in which case T2 is
absent rather than flat — see the `grid_import` alias in
[§4.1](05-data-formats.md#series-names). Both end in the same place; only the diagnostic
wording differs.

**(b) Which zone applies to a *simulated* interval?** The baseline can be priced from the
registers directly — that is what the supplier actually bills. But once a battery changes
the flows, simulated import must be assigned to a zone by clock rule:

```python
def tariff_zone(index_local, cfg):
    dal = ((index_local.hour >= cfg.dal_start_hour) |
           (index_local.hour <  cfg.dal_end_hour)  |
           (index_local.dayofweek >= 5))            # Sat/Sun
    return where(dal, DAL, NORMAAL)
```

Default window: dal from 23:00 to 07:00 plus weekends. **This varies by grid operator**
(21:00 in some areas), so it is user-configurable, and the app validates the rule against
the observed registers:

```python
mismatch = sum(import_t2[zone == NORMAAL]) + sum(import_t1[zone == DAL])
mismatch_pct = 100 * mismatch / total_import
# > 5% means the configured window is wrong — surface it in panel ①.
```

This check costs almost nothing and catches a whole class of silent mispricing under
fixed/variable contracts. The resulting `tariff_zone` array is what
[§6.5](10-pricing.md#65-price-curves) indexes for fixed and variable contracts.
