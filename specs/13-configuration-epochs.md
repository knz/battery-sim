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

# --- module constants (epoch-detection heuristics) --------------------------
# These are heuristic sensitivities with no user meaning; none is exposed in
# config.toml. Their thresholds are untested against ground truth — see X11.
REF_QUANTILE           = 0.95   # a robust "typical good day" production level
PV_PRESENT_MIN_KWH        = 0.1    # daily ref below this: treat PV as absent
PV_LIVE_WINDOW_DAYS       = 7      # rolling window for the "PV is producing" test
PV_LIVE_MIN_PERIODS       = 4      # min days in that window before it reports
PV_LIVE_FRACTION          = 0.10   # fraction of ref above which PV counts as live
PV_PEAK_SMOOTH_DAYS       = 30     # rolling window for capacity-change peak smoothing
BATTERY_ACTIVE_FRACTION   = 0.05   # daily throughput fraction of ref: battery active
UNDECLARED_PV_EXPORT_FRACTION = 0.01  # daytime export fraction of import: undeclared PV
UNDECLARED_PV_DAY_START   = 9      # daytime window for the undeclared-PV export test
UNDECLARED_PV_DAY_END     = 17     #   (hours; "midday" as a modelling choice)
UNDECLARED_BATT_WINDOW    = "14D"  # rolling window for night-import / self-consumption
SELF_CONSUMPTION_STEP     = 0.15   # min absolute self-consumption step: hidden battery
EPOCH_BOUNDARY_TOL        = "7D"   # a changepoint this close to an epoch edge is explained
FLAT_TOP_NIGHT_FRACTION   = 0.3    # night-import flat-topped fraction: grid-charging battery
                                   #   (no stated derivation — untested, see X11)

def detect_epochs(series, index_local):
    """Segment the window into intervals of constant physical configuration."""
    events = []

    if series.solar is not None:
        # --- PV commissioning --------------------------------------------
        # A sensor can exist and read zero for months before the panels go
        # live, so "first non-null" is the wrong test. Use sustained daily
        # production.
        daily = series.solar.resample("1D").sum()
        ref   = daily.quantile(REF_QUANTILE)
        if ref > PV_PRESENT_MIN_KWH:
            live = daily.rolling(PV_LIVE_WINDOW_DAYS,
                                 min_periods=PV_LIVE_MIN_PERIODS).mean() > PV_LIVE_FRACTION * ref
            if not live.iloc[0] and live.any():
                events.append(("pv_commissioned", live.idxmax()))

        # --- PV capacity change (panels added) ----------------------------
        # Compare rolling 30-day peak hourly output. A sustained step > 20%
        # that is not explained by season indicates added capacity.
        peak = series.solar.resample("1D").max().rolling(PV_PEAK_SMOOTH_DAYS).median()
        for d in changepoints(peak, min_rel_step=cfg.pv_capacity_min_rel_step,
                               min_segment_days=cfg.epoch_min_segment_days):
            events.append(("pv_capacity_changed", d))

    # --- Battery commissioning / removal ---------------------------------
    if series.batt_charge is not None:
        thr = (series.batt_charge + series.batt_discharge).resample("1D").sum()
        active = thr > BATTERY_ACTIVE_FRACTION * max(thr.quantile(REF_QUANTILE), DIV_GUARD_EPS)
        events += transitions(active, "battery_commissioned", "battery_removed")

    return build_epochs(events, index_local)
```

PV capacity-change detection is the weakest of these heuristics and ships **disabled** by
default (`pv_capacity_change_detection = off`, see
[appendix-a-defaults.md](appendix-a-defaults.md) and
[open question §8.13](17-open-questions.md)).

**Without PV both PV branches are skipped**, not run against a zero array — the guard is
on the series being present, so a household that declared no PV can produce only battery
events. A no-PV household with no battery has exactly one epoch spanning the window, which
is the common case and needs no timeline strip. This does not mean PV commissioning is
undetectable for such a household: it means a household that *did* commission PV mid-window
and answered "no PV" has told the app something false, which the next section addresses.

## Undeclared PV

The mirror of the undeclared-battery case below, and the reason the app asks about PV
explicitly rather than inferring it from an unmapped sensor. A household that has solar but
did not map the inverter — or that has an array on the same connection they did not think
to mention — produces a reconstruction of `load = import − export` that is wrong by exactly
the self-consumed generation, all day, every sunny day.

The signature is unambiguous and cheap to test:

```python
def detect_undeclared_pv(frame, cfg):
    """Only meaningful when the household declared it has no PV."""
    if cfg.has_pv:
        return

    # A household with no generator cannot export. Any sustained daytime
    # export is generation the app has not been told about.
    day     = ((frame.index_local.hour >= UNDECLARED_PV_DAY_START) &
               (frame.index_local.hour <  UNDECLARED_PV_DAY_END))
    exp_day = frame.export_obs[day].sum()
    if exp_day > UNDECLARED_PV_EXPORT_FRACTION * max(frame.import_obs.sum(), DIV_GUARD_EPS):
        warn(POSSIBLE_UNDECLARED_PV,
             detail="sustained daytime export from a household declaring no PV")
```

The daytime restriction separates this from an undeclared battery arbitraging to the grid,
which has no reason to prefer midday. Where both signatures fire, report both and let the
user say which it is. As with every heuristic here, this is put to the user as a question —
"we see export around midday; do you have solar panels?" — and never applied by changing
`has_pv` automatically. It is check 6b in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order).

## Undeclared batteries

**The dangerous case is an undeclared battery**: the unit was installed but its sensors
were never added to Home Assistant, or were added weeks later. The reconstruction in
[§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) then silently attributes
the battery's charging to household load, and every downstream number is wrong with no
error raised. Heuristic detection:

```python
def detect_undeclared_battery(frame, epochs, cfg):
    """Flag unexplained step changes consistent with hidden storage."""
    night = rolling_night_import(frame, window=UNDECLARED_BATT_WINDOW)

    if cfg.has_pv:
        # Needs a PV denominator; unavailable without solar.
        sc = rolling_self_consumption(frame, window=UNDECLARED_BATT_WINDOW)
        for d in changepoints(sc, min_abs_step=SELF_CONSUMPTION_STEP):
            if not epoch_boundary_near(d, epochs, tol=EPOCH_BOUNDARY_TOL):
                warn(POSSIBLE_UNDECLARED_BATTERY, date=d,
                     detail="self-consumption rose sharply with no PV or battery event")

    # Grid-charging storage shows as flat-topped night import at constant power.
    # Available in both cases, and the only available signal without PV.
    if flat_top_fraction(night) > FLAT_TOP_NIGHT_FRACTION:
        warn(POSSIBLE_UNDECLARED_BATTERY, detail="constant-power night import blocks")
```

Without PV only the second signal is available, so detection is weaker — but it is also the
signal that matters more there, since a battery installed in a household with no solar is
almost certainly grid-charging and will show the flat-topped night blocks.

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
