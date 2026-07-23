# 6.15 Configuration epochs

> **Purpose:** detecting that the physical installation changed part-way through the
> window, and making the analysis aware of it rather than averaging across it.
> **Audience:** backend and frontend — this feature reaches into panel ①, the range
> selector and the result object.
> **Read with:** [09-ingest-algorithms.md](09-ingest-algorithms.md) §6.3, whose
> reconstruction silently breaks in the undeclared-battery case described here, and
> [14-diagnostics.md](14-diagnostics.md) for the other ingest-time checks.

PV and batteries get installed mid-window. Averaging across a commissioning date produces
a figure that describes a household that never existed.

```python
EPOCH_EVENTS = ["pv_commissioned", "pv_capacity_changed",
                "battery_commissioned", "battery_removed"]

def detect_epochs(series, index_local):
    """Segment the window into intervals of constant physical configuration."""
    events = []

    # --- PV commissioning ------------------------------------------------
    # A sensor can exist and read zero for months before the panels go live,
    # so "first non-null" is the wrong test. Use sustained daily production.
    daily = series.solar.resample("1D").sum()
    ref   = daily.quantile(0.95)
    if ref > 0.1:
        live = daily.rolling(7, min_periods=4).mean() > 0.10 * ref
        if not live.iloc[0] and live.any():
            events.append(("pv_commissioned", live.idxmax()))

    # --- PV capacity change (panels added) --------------------------------
    # Compare rolling 30-day peak hourly output. A sustained step > 20% that
    # is not explained by season indicates added capacity.
    peak = series.solar.resample("1D").max().rolling(30).median()
    for d in changepoints(peak, min_rel_step=0.20, min_segment_days=45):
        events.append(("pv_capacity_changed", d))

    # --- Battery commissioning / removal ---------------------------------
    if series.batt_charge is not None:
        thr = (series.batt_charge + series.batt_discharge).resample("1D").sum()
        active = thr > 0.05 * max(thr.quantile(0.95), EPS)
        events += transitions(active, "battery_commissioned", "battery_removed")

    return build_epochs(events, index_local)
```

PV capacity-change detection is the weakest of these heuristics and ships **disabled** by
default (`pv_capacity_change_detection = off`, see
[appendix-a-defaults.md](appendix-a-defaults.md) and
[open question §8.13](17-open-questions.md)).

## Undeclared batteries

**The dangerous case is an undeclared battery**: the unit was installed but its sensors
were never added to Home Assistant, or were added weeks later. The reconstruction in
[§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) then silently attributes
the battery's charging to household load, and every downstream number is wrong with no
error raised. Heuristic detection:

```python
def detect_undeclared_battery(frame, epochs):
    """Flag unexplained step changes consistent with hidden storage."""
    sc    = rolling_self_consumption(frame, window="14D")
    night = rolling_night_import(frame, window="14D")

    for d in changepoints(sc, min_abs_step=0.15):
        if not epoch_boundary_near(d, epochs, tol="7D"):
            warn(POSSIBLE_UNDECLARED_BATTERY, date=d,
                 detail="self-consumption rose sharply with no PV or battery event")

    # Grid-charging storage shows as flat-topped night import at constant power.
    if flat_top_fraction(night) > 0.3:
        warn(POSSIBLE_UNDECLARED_BATTERY, detail="constant-power night import blocks")
```

Both are heuristics and both are presented as questions to the user, never as findings.
Detected boundaries are **always user-confirmable and overridable** — the household knows
when the installer came, and a date entered by hand beats any changepoint algorithm.

## Effects on the rest of the application

1. Panel ① renders an **epoch timeline strip** above the coverage summary
   ([§2.2](02-ux-wireframes.md#22-panel--data-input-expanded)).
2. The range selector marks any predefined range that crosses a boundary, and offers a
   one-click *"restrict to current configuration"*.
3. If a run spans a boundary it proceeds, but: annualisation is disabled, the result
   carries `spans_epoch_boundary: true`, and per-epoch sub-totals are reported alongside
   the aggregate so the user can see the discontinuity rather than infer it.
4. `SimulationFrame.epoch_id`
   ([§4.4](07-internal-representation.md#44-internal-normalised-representation)) lets
   metrics be grouped without re-running.
5. The battery state is **not** reset at a boundary. It is one continuous simulation; only
   the reporting is segmented. Confirmation of this choice is
   [open question §8.11](17-open-questions.md).

Epoch handling is checks 14 and 15 in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order), and
fixture 9 in [16-validation-harness.md](16-validation-harness.md). A related unresolved
case — a battery installed partway through the window whose sensors do not cover the whole
period — is [open question §8.6](17-open-questions.md).
