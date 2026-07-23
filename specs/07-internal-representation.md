# 4.4–4.6 Internal representation and outputs

> **Purpose:** the two in-memory frame types, the result JSON the UI renders, and the
> per-interval CSV that makes every headline figure traceable.
> **Audience:** backend, and frontend for §4.5.
> **Read with:** [09-ingest-algorithms.md](09-ingest-algorithms.md) (produces
> `SimulationFrame`), [11-policies-and-battery.md](11-policies-and-battery.md) (consumes
> it), and [12-metrics-and-benchmarks.md](12-metrics-and-benchmarks.md) (fills most of
> the result object).

## 4.4 Internal normalised representation

After ingest, every series becomes a `SeriesFrame`:

```python
SeriesFrame:
    name:            str
    kind:            Literal["energy", "price"]
    resolution_s:    int | None       # None if irregular
    index:           DatetimeIndex    # UTC, interval START, left-closed
    values:          np.ndarray       # energy: kWh in interval; price: EUR/kWh valid from
    quality:         QualityFlags     # per-interval bitfield
```

`QualityFlags` bits: `OK`, `GAP_FILLED`, `RESET_CORRECTED`, `INTERPOLATED`,
`RESAMPLED_DOWN`, `CLAMPED_NEGATIVE`.

`resolution_s` is the series' **native** resolution — the spacing at which it was recorded,
before any reconciliation with the simulation grid. It is the source of the per-series
granularity table in panel ①
([§2.2](02-ux-wireframes.md#22-panel--data-input-expanded)) and of the `series` block in
§4.5, and it is persisted per series in `series_meta`
([§5.1](08-architecture.md#51-layers)). `None` means the spacing is irregular; that series
is reported as `irregular` and what the grid selector should do with it is
[open question §8.20](17-open-questions.md).

The simulation consumes a single `SimulationFrame` — all series on one uniform grid:

```python
SimulationFrame:
    index:      DatetimeIndex      # UTC, uniform, interval start
    dt_hours:   float
    pv:         ndarray            # kWh
    load:       ndarray            # kWh, battery-free, standby-free
    spot:       ndarray            # EUR/kWh, bare (mean within interval)
    spot_min:   ndarray | None     # EUR/kWh, intra-interval min (§6.16)
    spot_max:   ndarray | None     # EUR/kWh, intra-interval max (§6.16)
    epoch_id:   ndarray[uint8]     # configuration epoch index (§6.15)
    import_obs: ndarray            # kWh, as measured (for validation only)
    export_obs: ndarray            # kWh, as measured (for validation only)
    tariff_zone: ndarray[uint8]    # 0 = normaal, 1 = dal
    quality:    ndarray[uint16]
```

Notes on the fields that are not simulation inputs:

- `pv` **is always present and always an array.** When the household has no PV it is
  all-zero, filled once at frame construction. It is deliberately not `None` and not
  optional: every consumer downstream — the policies, the battery step, the metrics, the
  DP — is already correct on an all-zero array, and making the field nullable would push a
  `has_pv` branch into each of them for no gain. Whether the household declared PV is
  carried separately, on the config object, for the requirements and diagnostics that
  genuinely differ.
- `import_obs` / `export_obs` are never used by the battery model. They exist solely for
  the overlap diagnostic in
  [§7.1](14-diagnostics.md#71-the-overlap-diagnostic--measure-resolution-damage-directly),
  which requires both. Keep them.
- `spot` **is always present**, in both cost modes. It is the dispatch signal the charge
  and discharge bands compare against, not only a cost input
  ([§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model)). Unlike `pv`, it has no
  neutral value: an all-zero `spot` would not mean "no prices", it would mean "prices are
  zero everywhere", and every band comparison would silently take a definite and wrong
  branch. There is therefore no energy-only mode in which this field is absent.
- `spot_min` / `spot_max` drive the price bracket in
  [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) and
  are `None` when the source has no sub-interval price information, or when cost simulation
  is off and the bracket will not be computed.
- `epoch_id` lets metrics be grouped per configuration epoch without re-running the
  simulation — see [§6.15](13-configuration-epochs.md#615-configuration-epochs).

## 4.5 Result object

```jsonc
{
  "run_id": 47,
  "generated_at": "2026-07-22T09:14:02Z",
  // `resolution` and `dt_hours` describe the SIMULATION GRID — the single spacing
  // every series was reconciled onto. Per-series native resolutions are in
  // `series` below (§6.2).
  "window": { "start": "2025-07-22T00:00:00Z", "end": "2026-07-21T23:00:00Z",
              "intervals": 8760, "dt_hours": 1.0, "resolution": "hour" },
  "config_hash": "sha256:9f2c…",

  // One entry per ingested series, in mapping order. Describes the input data,
  // so it is identical under both toggles — see the two shape sections below.
  "series": [
    { "name": "grid_import_t1", "kind": "energy",
      "native_resolution_s": 3600,
      "coverage": { "start": "2025-07-22T00:00:00Z", "end": "2026-07-21T23:00:00Z" },
      // A finer copy of the same series over part of the window, when one was
      // fetched (§4.3). Null when there is none.
      "fine_resolution_s": 300,
      "fine_coverage": { "start": "2026-07-12T00:00:00Z", "end": "2026-07-21T23:00:00Z" },
      "reconciliation": "exact" },
    { "name": "price_spot", "kind": "price",
      "native_resolution_s": 900,
      "coverage": { "start": "2025-07-22T00:00:00Z", "end": "2026-07-21T23:00:00Z" },
      "fine_resolution_s": null, "fine_coverage": null,
      "reconciliation": "averaged" }
  ],
  // false ⇒ cost, benchmarks.cost and price_bracket are null; everything
  // else below is identical either way. See "Shape of the object without
  // cost simulation".
  "simulate_cost": true,

  "energy": {
    "baseline":  { "import_kwh": 4129.4, "export_kwh": 3180.2 },
    "battery":   { "import_kwh": 2717.1, "export_kwh": 1742.0 },
    "saved_kwh": 1412.3, "saved_pct": 34.2,
    "pv_kwh": 5210.0, "load_kwh": 6120.4,
    "charge_ac_kwh": 2664.0, "discharge_ac_kwh": 2410.0,
    "conversion_loss_kwh": 254.0, "standby_kwh": 262.8,
    "curtailed_kwh": 0.0
  },

  "cost": {
    "currency": "EUR",
    "baseline_eur": 1153.20,
    "battery_eur":  822.10,
    "saved_eur":    331.10,
    "saved_pct":    28.7,
    "waterfall": [
      { "label": "avoided_grid_import",       "eur":  402.10 },
      { "label": "added_grid_import_charging","eur":  -62.00 },
      { "label": "avoided_terugleverkosten",  "eur":   96.40 },
      { "label": "lost_feedin_compensation",  "eur": -141.30 },
      { "label": "arbitrage_export_revenue",  "eur":   36.00 },
      { "label": "standby_consumption",       "eur":  -62.00 },
      { "label": "feedin_floor_topup",        "eur":    0.00 },
      { "label": "degradation",               "eur":    0.00, "enabled": false }
    ]
  },

  "battery": {
    "equivalent_full_cycles": 241.0,
    "cycles_per_day": 0.66,
    "throughput_kwh": 2410.0,
    "soc_start_kwh": 5.0, "soc_end_kwh": 4.2,
    "soc_delta_value_eur": -0.19,
    "intervals_at_max_soc": 1204, "intervals_at_min_soc": 2988
  },

  // self_consumption_* are null when the household has no PV (§6.11).
  "ratios": {
    "self_consumption_baseline": 0.58, "self_consumption_battery": 0.81,
    "self_sufficiency_baseline": 0.31, "self_sufficiency_battery": 0.52
  },

  // One benchmark per headline figure, each from a DP optimised for its own
  // quantity (§6.12). `energy` is always present; `cost` is null without cost
  // simulation. The two are never derived from one another: the cost-optimal
  // dispatch avoids less import than the import-optimal one.
  "benchmarks": {
    "energy": {
      "no_battery_saved_kwh": 0.0,
      "policy_saved_kwh": 1412.3,
      "perfect_foresight_saved_kwh": 1988.0,
      "capture_ratio": 0.710
    },
    "cost": {
      "no_battery_eur": 0.0,
      "policy_eur": 331.10,
      "perfect_foresight_eur": 478.30,
      "capture_ratio": 0.692
    }
  },

  "epochs": [
    { "id": 0, "start": "2025-07-22", "end": "2025-09-14",
      "has_pv": false, "has_battery": false, "detected": true, "confirmed_by_user": true },
    { "id": 1, "start": "2025-09-15", "end": "2026-07-21",
      "has_pv": true,  "has_battery": false, "detected": true, "confirmed_by_user": true }
  ],
  "epoch_used": 1,
  "spans_epoch_boundary": false,

  "price_bracket": {
    "applicable": true,
    "settlement": "quarter_hourly",
    "saved_eur_low": 298.40, "saved_eur_central": 331.10, "saved_eur_high": 366.80,
    "intra_hour_spread_mean_eur_kwh": 0.021
  },

  "topology": {
    "has_pv": true,
    "pv_coupling": "dc_hybrid",       // null when has_pv is false
    "battery_phases": "three_phase",
    "approximated": false
  },

  "diagnostics": {
    "overlap_kwh": 61.2, "overlap_pct": 1.5,
    "time_offset_s": 0, "time_offset_confidence": 0.94,
    "power_energy_residual_pct": 0.8,
    // Always measured against the kWh saving, so it does not move with the
    // cost toggle. The euro-basis figure beside it is an addition (§6.13).
    "resolution_bias_pct": 8.4,
    "resolution_bias_pct_eur": 9.1,
    "resolution_bias_basis": "9 days at 5-minute vs hourly",
    // Set when a price series was averaged down onto a coarser grid by a factor
    // of 2 or more (§6.2, check 3b). Reported in both cost modes: the spot
    // series is a dispatch signal either way.
    "price_granularity_lost": true,
    "price_native_resolution_s": 900,
    "negative_load_intervals": 41, "negative_load_pct": 0.41,
    "gaps_filled_hours": 4.2,
    "counter_resets": 2,
    "tariff_zone_mismatch_pct": 2.1,
    "annualisation_allowed": true,
    "feedin_floor_partial_periods": 2,
    "feedin_floor_shorter_than_period": false
  },

  "monthly": [ { "month": "2025-08", "saved_kwh": 88.2, "saved_eur": 21.4,
                 "cycles": 18.1 } ],

  "warnings": [
    { "code": "RESOLUTION_BIAS_HIGH", "severity": "warn",
      "message": "Hourly simulation overstates savings by ~8.4%." }
  ]
}
```

Where each block comes from:

| Block | Defined in |
|---|---|
| `window`, `series` | [§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling) |
| `energy`, `ratios`, `battery` | [§6.11](12-metrics-and-benchmarks.md#611-metrics) |
| `cost.waterfall` | [§6.10](10-pricing.md#610-cost-accounting) |
| `benchmarks.energy`, `benchmarks.cost` | [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark) |
| `epochs`, `epoch_used`, `spans_epoch_boundary` | [§6.15](13-configuration-epochs.md#615-configuration-epochs) |
| `price_bracket` | [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) |
| `topology` | [§2.5](03-topology-selector.md) |
| `diagnostics` | [14-diagnostics.md](14-diagnostics.md) and [§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order) |

### Shape of the object without cost simulation

**Cost simulation is a strictly additive layer.** Every field of `window`, `series`,
`energy`, `ratios`, `battery`, `benchmarks.energy`, `epochs`, `topology` and `diagnostics`
that is not in the null list immediately below is **bit-identical between a run with
`simulate_cost = false` and the same run with it `true`**, down to the per-interval SoC
trace. Enabling the toggle
fills in the listed entries and changes nothing else: no field switches units, no field
switches basis, and no figure already on screen moves. This is the central invariant of the
optional-cost design and is pinned by fixture 18 in
[16-validation-harness.md](16-validation-harness.md).

What is `null` with `simulate_cost = false`, and populated when it is `true`:

- `cost` — `null` **wholesale**. Not an object of null fields, and in particular not a
  `waterfall` array of eight null-valued entries, which would invite a template to render
  eight empty rows.
- `benchmarks.cost` — `null` wholesale, for the same reason. `benchmarks.energy` is present
  in both modes and carries the same numbers in both, because the DP behind it minimises
  grid import regardless of what else is being computed
  ([§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark)). If the DP could
  not run at all, both blocks are `null`.
- `price_bracket` — `null`. Bracketing exists to bound a *pricing* error.
- `battery.soc_delta_value_eur` — `null`. Residual SoC is still reported in kWh as
  `soc_end_kwh − soc_start_kwh`; only its valuation is unavailable.
- `monthly[].saved_eur` — `null`. `saved_kwh` and `cycles` are unaffected.
- `diagnostics.resolution_bias_pct_eur` — `null`. The kWh-basis
  `diagnostics.resolution_bias_pct` beside it is computed in both modes and is one of the
  invariant fields above ([§6.13](14-diagnostics.md#613-resolution-bias-diagnostic)).
- `diagnostics.feedin_floor_partial_periods` and
  `diagnostics.feedin_floor_shorter_than_period` — `null`, since no floor was assessed.

`series` and `window` are **not** on that list and never will be. They describe the input
data and the grid it was reconciled onto, neither of which the cost model touches. In
particular `diagnostics.price_granularity_lost` and `price_native_resolution_s` are
populated in both modes: they report that intra-interval price movement was averaged away
before dispatch, which is true whether or not euros were computed
([§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling)). The
cost-only companion is `price_bracket`, which bounds the *pricing* error rather than
reporting the *dispatch* one, and that is `null` here.

Nulling whole blocks rather than every leaf is a deliberate departure from the
key-for-key rule below. The rule exists so consumers test for `null` instead of for
existence; testing `result.cost === null` satisfies it just as well as testing
`result.cost.saved_eur === null`, and it does so at the granularity at which the UI
actually branches — the whole cost section is rendered or it is not.

**Shape of the object without PV.** Every key above is still present — consumers never
need to test for existence, only for `null`. `series` and `window` are unaffected: `has_pv`
changes which series are *required*, not what a supplied series' native resolution is, and
a series that was never mapped is simply absent from the array rather than present with
null fields. What changes:

- `topology.has_pv` is `false` and `topology.pv_coupling` is `null`.
- `ratios.self_consumption_baseline` and `ratios.self_consumption_battery` are `null`.
- `energy.pv_kwh` is `0.0`, and `energy.curtailed_kwh` is `0.0` unless arbitrage export hit
  the connection limit.
- `cost.waterfall` keeps all its lines. `lost_feedin_compensation` and
  `avoided_terugleverkosten` will be `0.00` for most no-PV runs but are not special-cased,
  and the closure identity in fixture 4 must still hold.
- `diagnostics` fields that depend on a PV signal are `null` rather than `0`:
  `time_offset_s` and `time_offset_confidence` when cross-correlation could not be run
  ([§6.17](14-diagnostics.md#617-timestamp-misalignment-detection)), and
  `negative_load_pct` remains meaningful but carries a different interpretation
  ([§6.3](09-ingest-algorithms.md#63-household-load-reconstruction)).
- `epochs[].has_pv` is `false` throughout, and no `pv_commissioned` event can be detected
  ([§6.15](13-configuration-epochs.md#615-configuration-epochs)).

A `null` here means "not computable for this household", which is distinct from a zero
measurement, and the UI must render the distinction rather than collapsing both to `0`.

## 4.6 Per-interval CSV export

Every headline figure must be traceable. The export contains one row per simulation
interval:

```csv
timestamp_utc,timestamp_local,dt_h,pv_kwh,load_kwh,spot_eur_kwh,
p_import_eur_kwh,p_export_net_eur_kwh,tariff_zone,
base_import_kwh,base_export_kwh,
charge_ac_kwh,charge_from_pv_kwh,charge_from_grid_kwh,
discharge_ac_kwh,discharge_to_home_kwh,discharge_to_grid_kwh,
soc_kwh,batt_import_kwh,batt_export_kwh,
base_cost_eur,batt_cost_eur,quality_flags
```

The `base_*` columns are run A and the `batt_*` columns are run C of the runs in
[§6.9](11-policies-and-battery.md#69-main-simulation-loop).

**Without cost simulation the cost columns are dropped from the file entirely** —
`p_import_eur_kwh`, `p_export_net_eur_kwh`, `base_cost_eur` and `batt_cost_eur` are absent
from both the header and the rows. `spot_eur_kwh` and `tariff_zone` remain: the first is a
simulation input in both modes, the second is a property of the data.

This is the opposite convention to the result JSON above, and the difference is
intentional. A JSON consumer indexes by key and benefits from a stable shape, so absent
values are `null`. A CSV is read by a spreadsheet or a human, its header is
self-describing, and a column of blank cells is worse than an absent column — it looks like
data that failed to compute rather than data that was never asked for.
