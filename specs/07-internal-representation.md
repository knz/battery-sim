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
- `spot_min` / `spot_max` drive the price bracket in
  [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) and
  are `None` when the source has no sub-interval price information.
- `epoch_id` lets metrics be grouped per configuration epoch without re-running the
  simulation — see [§6.15](13-configuration-epochs.md#615-configuration-epochs).

## 4.5 Result object

```jsonc
{
  "run_id": 47,
  "generated_at": "2026-07-22T09:14:02Z",
  "window": { "start": "2025-07-22T00:00:00Z", "end": "2026-07-21T23:00:00Z",
              "intervals": 8760, "dt_hours": 1.0, "resolution": "hour" },
  "config_hash": "sha256:9f2c…",

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

  "benchmarks": {
    "no_battery_eur": 0.0,
    "policy_eur": 331.10,
    "perfect_foresight_eur": 478.30,
    "capture_ratio": 0.692
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
    "resolution_bias_pct": 8.4,
    "resolution_bias_basis": "9 days at 5-minute vs hourly",
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
| `energy`, `ratios`, `battery` | [§6.11](12-metrics-and-benchmarks.md#611-metrics) |
| `cost.waterfall` | [§6.10](10-pricing.md#610-cost-accounting) |
| `benchmarks.perfect_foresight_eur` | [§6.12](12-metrics-and-benchmarks.md#612-perfect-foresight-benchmark) |
| `epochs`, `epoch_used`, `spans_epoch_boundary` | [§6.15](13-configuration-epochs.md#615-configuration-epochs) |
| `price_bracket` | [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) |
| `topology` | [§2.5](03-topology-selector.md) |
| `diagnostics` | [14-diagnostics.md](14-diagnostics.md) and [§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order) |

**Shape of the object without PV.** Every key above is still present — consumers never
need to test for existence, only for `null`. What changes:

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

The `base_*` columns are run A and the `batt_*` columns are run C of the four runs in
[§6.9](11-policies-and-battery.md#69-main-simulation-loop).
