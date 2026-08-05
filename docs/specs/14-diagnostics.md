# Diagnostics — §7.1, §6.13, §6.16, §6.17

> **Purpose:** the measurements that tell the user how much to trust the headline
> figure — how much information the recording resolution destroyed, how much that changes
> the answer, how much pricing error the settlement mismatch introduces, and whether the
> sensors' clocks agree.
> **Audience:** backend (all four are pure functions over the frame) and frontend (all
> four surface in panel ① or the caveats box in panel ③).
> **Read with:** [09-ingest-algorithms.md](09-ingest-algorithms.md) §6.2, which creates
> the resolution loss these measure, and
> [15-data-quality-and-limits.md](15-data-quality-and-limits.md) §7.3 for where each sits
> in the check order.

These reference each other continuously, so the distinctions are worth holding on to. Four
are specified in this file; the granularity-loss finding belongs to
[§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling), where the
resampling that produces it is defined, and is listed here so the family can be compared in
one place.

| Diagnostic | Measures | Availability |
|---|---|---|
| §7.1 overlap | How much information the recording resolution destroyed | Always, full window |
| §6.13 resolution bias | How much that loss changes the answer (*dispatch* error) | Only where 5-minute data exists; always in kWh, additionally in euros when costs are modelled |
| §6.2 granularity loss | That a price series was averaged onto a coarser grid at all — a *dispatch* concern | Always, both cost modes, when a price series is downsampled by a factor ≥ 2 |
| §6.16 price bracket | *Pricing* error from settling per 15 min but recording hourly | Cost simulation only, quarter-hourly settlement, and at least one interval whose native prices differ |
| §6.17 misalignment | Whether two sensors' clocks agree | Needs PV + export, or power + energy |

§6.13 and §6.16 measure independent errors and both should be reported.

The §6.2 granularity finding and the §6.16 bracket are easy to confuse, since both arise
from quarter-hourly prices against hourly data. They are two halves of one mismatch. §6.2
reports that the battery *dispatched* on an averaged price and so could not act on
within-hour swings, which is true whether or not euros were computed. §6.16 bounds what the
averaging did to the euro figure, and exists only when there is one. The first is a fact
about the data, the second a bound on a result.

**Without PV, only §6.17 changes.** The overlap diagnostic, the resolution-bias run, the
granularity finding and the price bracket are all computed from grid flows and prices and
are unaffected by the absence of solar — overlap in particular remains the primary
resolution gate. §6.17's
primary method needs a PV signal and is unavailable; see that section.

**Without cost simulation, only §6.16 disappears.** It bounds a *pricing* error, and with
no prices applied there is no such error to bound; no bracket is computed. The others
survive **with identical values**, because resolution damage, granularity loss and clock
offsets are properties of the data rather than of the cost model. §6.13 in particular measures dispatch
error against the kWh saving in both modes; enabling cost simulation adds a euro-basis
percentage beside it and leaves the kWh one untouched.

---

## 7.1 The overlap diagnostic — measure resolution damage directly

There is a much better resolution diagnostic than §6.13, available on the **full window**
without needing any 5-minute data:

```python
overlap_kwh = minimum(import_obs, export_obs).sum()
overlap_pct = 100 * overlap_kwh / import_obs.sum()
```

In any interval where the meter recorded **both** import and export, the flow direction
reversed *within* the interval. That energy is invisible to the simulator: the
reconstructed load nets it out, so the simulated baseline shows less import than actually
occurred, and no battery in the simulation can recover it.

**This measure is clean, and the reason matters.** Dutch smart meters net internally
across phases: they sum L1, L2 and L3 at each measurement instant and record only the net,
so they never register import and export at the same instant, only one or the other. A
1,200 W export on L1 against a 1,200 W draw on L2 registers as nothing at all. This
behaviour is a property of the meter rather than of the salderingsregeling, and is
unchanged by the latter's abolition in 2027 —
[background E1.4](18-dutch-electricity-background.md#e14-internal-phase-netting--the-meter-nets-across-l1-l2-l3)
sets it out from the metering side. So overlap within
an interval can only have arisen from the flow reversing *in time*, never from one phase
exporting while another imports. `overlap_kwh` is therefore an uncontaminated measure of
temporal resolution loss. On a meter without phase netting the same statistic would
conflate two effects and would not be usable this way.

`overlap_kwh` is therefore a direct, exact measure of how much information the recording
resolution destroyed. Use it as the primary gate:

| `overlap_pct` | Treatment |
|---|---|
| < `overlap_warn_pct` | Fine. Report quietly. |
| `overlap_warn_pct`–`overlap_prominent_pct` | Warn. Headline savings are an upper bound. |
| > `overlap_prominent_pct` | Prominent warning. Recommend re-running over the 5-minute window instead. |

**In a household with no PV, `overlap_kwh` should be essentially zero**, because there is
nothing behind the meter that can push power outward within an interval. A nonzero value
there is not a resolution finding — it is evidence of undeclared generation or storage, and
should be routed to the undeclared-PV and undeclared-battery checks in
[§6.15](13-configuration-epochs.md#undeclared-pv) rather than reported as resolution
damage. The gate table below applies as written only when the household has declared PV.

Consequently `SimulationFrame` must retain `import_obs`/`export_obs` — they are not used
in the simulation itself, only in validation. Keep both. See
[§4.4](07-internal-representation.md#44-internal-normalised-representation).

**Which baseline for the savings percentage?** Use the *simulated* baseline (run A), so
that both scenarios see identical information. Report the observed import alongside it,
with the difference labelled as resolution loss. Using observed import as the denominator
while computing the battery case from reconstructed data would mix two information sets
and produce a number that is wrong in a direction nobody can reason about.

---

## 6.13 Resolution-bias diagnostic

Complements the overlap diagnostic in §7.1 above. Overlap measures how much information
the recording resolution destroyed; this measures how much that changes the answer.
Report both — §7.1 covers the whole window and is always available, §6.13 is more
direct but only available where 5-minute data exists.

Hourly buckets cannot represent a house that imports at 12:05 and exports at 12:40. They
show only the net, which makes the household look more self-balancing than it was and
**systematically overstates** what a battery would have added. The magnitude is household-
specific (5–20% is typical), so it must be measured, not assumed.

```python
# --- module constants (resolution-bias diagnostic) --------------------------
FINE_GRID_S          = 300     # 5-minute: the fine comparison basis
COARSE_GRID_S        = 3600    # hourly: the coarse comparison basis
BIAS_MIN_WINDOW_DAYS = 3       # below this the fine window is too short to trust
BIAS_FLOOR_KWH       = 5.0     # kWh stability floor for the ratio (see note below)
BIAS_FLOOR_EUR       = 1.0     # €   stability floor — a separate magnitude, not a unit-converted BIAS_FLOOR_KWH

def resolution_bias(dataset, cfg):
    fine_window = dataset.window_with_resolution(FINE_GRID_S)   # trailing ~10 days
    if fine_window is None or fine_window.days < BIAS_MIN_WINDOW_DAYS:
        return None

    r_fine   = run_all(dataset.frame(fine_window, grid_s=FINE_GRID_S),   cfg)
    r_coarse = run_all(dataset.frame(fine_window, grid_s=COARSE_GRID_S), cfg)

    def bias(fine, coarse, floor):
        # Below the floor the ratio is numerically unstable and carries no
        # information; report nothing rather than a large meaningless percentage.
        return 100 * (coarse - fine) / fine if abs(fine) >= floor else None

    # The kWh basis is computed always. This diagnostic measures dispatch error,
    # dispatch does not depend on the cost model, and so neither does this number.
    out = {
      "bias_pct": bias(r_fine.saved_kwh, r_coarse.saved_kwh, BIAS_FLOOR_KWH),
      "basis":    f"{fine_window.days} days at 5-minute vs hourly",
      "bias_pct_eur": None,
    }

    # With a cost model, the same resolution error also displaces euros, by a
    # different percentage: the intervals it distorts are not equally priced.
    # Reported alongside, never instead of, the kWh figure.
    if cfg.simulate_cost:
        out["bias_pct_eur"] = bias(r_fine.saved_eur, r_coarse.saved_eur, BIAS_FLOOR_EUR)

    return out if out["bias_pct"] is not None else None
```

The `BIAS_FLOOR_KWH` (5 kWh) and `BIAS_FLOOR_EUR` (€1) floors are not the same number in
different units. Each is the level below
which the ratio becomes numerically unstable in that quantity — both roughly "less than a
day's worth of effect over a ten-day window".

Computing the kWh figure unconditionally is what keeps `diagnostics.resolution_bias_pct`
identical whether or not the user asked for euros. Selecting the basis from
`cfg.simulate_cost` instead would make an energy diagnostic move for a pricing reason, and
would have to be excluded from the invariance guarantee in
[§4.5](07-internal-representation.md#shape-of-the-object-without-cost-simulation).

The trailing 5-minute window it needs is fetched deliberately for this purpose — see
[§4.3](06-home-assistant-ingestion.md).

It measures *dispatch* error (the battery makes different decisions at different
resolutions). The price bracket in §6.16 measures *pricing* error. They are independent
and both should be reported.

Reported as an advisory, **never applied as an automatic correction**: the trailing ten
days are not a representative sample of the year, and silently scaling the headline number
by a factor derived from one seasonal window would be worse than showing both.

---

## 6.16 Price bracketing under settlement/resolution mismatch

Since 1 October 2025 EPEX settles per 15 minutes. Where the supplier passes that through
but the available energy data is hourly, the simulator sees an hourly average price and
cannot know how the household's consumption was distributed within the hour.

**The min and max are derived, not asked for.** When the spot series is natively finer than
the simulation grid, the resampling in
[§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling) already visits
every native price point that falls in an interval; the cheapest and dearest of them are
recorded alongside the mean as `spot_min` / `spot_max`
([§4.4](07-internal-representation.md#44-internal-normalised-representation)). Where an
interval received a single price point — an hourly price on an hourly grid, or a held
value — min, max and mean coincide and the bracket is a point. No slot is asked of the
user, and the quantity does not vary by data source.

**What is computed.** One dispatch, re-billed at two further price vectors. The flows are
those of the ordinary run; only the price vector changes, so what is being bounded is the
*pricing* error and not what the battery would have done differently. The central saving is
the one the results screen already shows, taken from the main run rather than recomputed; the
favourable and unfavourable saving are evaluated beside it by choosing, **per interval**, whichever of
`spot_min` / `spot_max` moves the saving in the intended direction — on the sign of that
interval's own flow difference between the battery and no-battery runs, with imports and
exports taking opposite ends because the saving subtracts the export term. A window-uniform
choice — billing the whole window at `spot_min`, then at `spot_max` — is the right pair for
a single *bill* but not for a *difference* of bills, and on windows that mix grid-charging
intervals with import-cutting ones the two ends cancel against each other.

**Reported as a width, not as an interval.** The result surfaced to the user is half the
range between the favourable and unfavourable saving: how far the saving shown on the
results screen could shift, phrased as a caveat beside the §6.2 granularity finding. The
endpoints stay internal. The reason is that the width can exceed the saving itself, in
which case a "± €Y" reading invites the conclusion that the battery might lose money — a
much stronger claim than a worst-case bound on the pricing supports. The caveat also states
the share of priced intervals that carry a spread at all, since a window straddling
2025-10-01 is part hourly and part not.

It is a **worst case** over where inside each interval the energy sat, and the copy says so.
A typical error would be narrower, because errors across many hours partially cancel — but
that claim needs an independence assumption household load does not satisfy (load has
intra-hour structure and battery charging is deliberately timed), so the narrower figure is
not offered. It is also **not** a bound on what a 15-minute-aware controller could achieve:
such a controller would dispatch differently. Pricing error and dispatch error are separate;
§6.13 covers the second.

**Four suppression conditions**, each yielding no bracket at all rather than a zero width:
cost simulation off (there is no euro figure to qualify); `supplier_settlement = HOURLY`,
where the hourly mean is exactly what the household pays and a bracket would manufacture
uncertainty that does not exist; no priced interval anywhere in the window, so there is
nothing to bracket; and no interval carrying a spread, which is the natively hourly case —
there the intra-hour variation is unobservable rather than absent, and reporting "±€0" would
assert it was absent. Whether hourly is the right default is resolved in
[§8.12](17-open-questions.md): the app asks.

A fifth condition suppresses the caveat on **display** rather than the bracket itself: euro
figures print to whole euros, so a width of half a euro or less would render as "€ 0" — a
sentence claiming a worst case of nothing.

`saved_low ≤ saved_central ≤ saved_high` must hold wherever a bracket applies. Fixture 10 in
[16-validation-harness.md](16-validation-harness.md).

---

## 6.17 Timestamp misalignment detection

A clock offset between the P1 meter integration and the solar inverter integration is
common (minutes to a full hour, the latter usually a timezone bug) and corrupts the
reconstruction in [§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) in a
way that looks like noise rather than an error.

**This is a PV-household problem.** It arises from combining two independently-clocked
sensors; a household without PV reconstructs load from the meter alone, so there is no
second clock to disagree with and this entire class of error does not exist. The primary
method below is unavailable there — it correlates PV against export — and the diagnostic
reports `time_offset_s: null` rather than `0`, which would claim a measurement that was
never made. The corroborating method still runs if the user mapped a grid power sensor
alongside the energy meter, where it checks that sensor against the meter.

**Min/max alone cannot detect an offset** — shifting a series in time does not change its
hourly extrema in any recoverable way. Two things do work:

```python
# Confidence (z-score of the best lag against the lag-score distribution) at or
# above which a detected offset is worth surfacing to the user. Heuristic.
TIME_OFFSET_CONFIDENCE_MIN = 3.0

def detect_time_offset(pv, export_obs, max_lag_intervals):   # = cfg.time_offset_max_lag
    """
    Primary method: normalised cross-correlation. PV production and grid export
    are strongly coupled in a PV household; the lag maximising correlation is
    the offset between the two sensors' clocks.
    """
    a = zscore(detrend_daily(pv))
    b = zscore(detrend_daily(export_obs))
    scores = [pearson(a, shift(b, lag))
              for lag in range(-max_lag_intervals, max_lag_intervals + 1)]
    best   = argmax(scores)
    confidence = (scores[best] - median(scores)) / (std(scores) + STD_GUARD_EPS)
    return lag_at(best), confidence


def power_energy_consistency(power_mean_w, energy_sum_kwh, dt_h):
    """
    Corroborating method, available when the user mapped BOTH a power sensor
    (state_class measurement -> has mean) and an energy meter for the same
    quantity. Over one interval these must agree:

        mean_power_W / 1000 * dt_h  ==  energy_sum_kWh

    A constant proportional error means a unit or scaling mistake. An error
    that oscillates with the daily cycle means a time offset — the mean power
    is being attributed to the wrong hour.
    """
    implied  = power_mean_w / 1000.0 * dt_h
    residual = (implied - energy_sum_kwh) / maximum(energy_sum_kwh, DIV_GUARD_EPS)
    return dict(mean_pct=100 * residual.mean(),
                diurnal_amplitude_pct=100 * daily_fourier_amplitude(residual))
```

A detected offset is **reported and offered as a correction**, never applied silently:
"Solar production appears to lag the meter by 1 hour (confidence 0.94). Shift it?"
Applying it automatically would make a data problem invisible, and the user may have a
better explanation than the algorithm does.

The third signal is §7.1 above: `overlap_pct` inflates under misalignment, because a
shifted PV series creates apparent import and export in the same interval. If overlap is
high *and* cross-correlation finds a confident non-zero lag, misalignment is the likely
cause rather than genuine sub-interval variation.

Recovery of a known injected lag to within one interval, at confidence above
`TIME_OFFSET_CONFIDENCE_MIN`, is
fixture 11 in [16-validation-harness.md](16-validation-harness.md).
