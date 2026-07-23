# 4.1–4.2 CSV input formats

> **Purpose:** the two accepted CSV shapes, the series vocabulary, and what `kind` means.
> **Audience:** backend, integrators, and anyone writing an exporter.
> **Read with:** [06-home-assistant-ingestion.md](06-home-assistant-ingestion.md) for the
> other ingestion path, and [09-ingest-algorithms.md](09-ingest-algorithms.md) for what
> happens to these values after parsing.

## 4.1 Canonical CSV — long format (preferred)

Long format is canonical because series legitimately arrive at **different native
resolutions** (hourly meter data, 15-minute prices, 5-minute recent HA data). A wide format
would force a common grid at ingestion time, which is precisely the wrong place to make that
decision; the grid is chosen later, in
[§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling). Each series'
native resolution is inferred from the spacing of its own rows, retained, and reported back
to the user per series in panel ①
([§2.2](02-ux-wireframes.md#granularity-per-series)) — it is not collapsed into one figure
for the file.

```csv
timestamp,series,value,unit,kind
2026-01-01T00:00:00+01:00,grid_import_t1,14203.412,kWh,cumulative
2026-01-01T00:00:00+01:00,grid_import_t2,9821.005,kWh,cumulative
2026-01-01T00:00:00+01:00,solar_production,7734.220,kWh,cumulative
2026-01-01T00:00:00+01:00,price_spot,0.0412,EUR/kWh,price
2026-01-01T01:00:00+01:00,grid_import_t1,14203.911,kWh,cumulative
```

### Column rules

| Column | Type | Rules |
|---|---|---|
| `timestamp` | ISO 8601 | **Offset or `Z` is mandatory.** Naive timestamps are rejected — during the October DST transition a naive local timestamp is genuinely ambiguous and silently corrupts an hour of data every year. |
| `series` | enum | See below. Unknown values rejected with the list of valid names. |
| `value` | float | `.` decimal separator. Empty or `NaN` treated as a gap, not as zero. |
| `unit` | enum | `kWh`, `Wh`, `MWh`, `EUR/kWh`, `EURcent/kWh`, `EUR/MWh`. Converted on ingest. |
| `kind` | enum | `cumulative`, `delta`, `price`. |

### Series names

| Series | Required | Kind | Notes |
|---|---|---|---|
| `grid_import_t1` | yes¹ | cumulative/delta | Normaal or dal — see [§6.4](09-ingest-algorithms.md#64-tariff-registers--availability-identification-and-use) |
| `grid_import_t2` | expected⁴ | cumulative/delta | |
| `grid_export_t1` | yes¹ | cumulative/delta | |
| `grid_export_t2` | expected⁴ | cumulative/delta | |
| `solar_production` | conditional² | cumulative/delta | AC output of the PV inverter. Required when the household declares PV, absent otherwise |
| `battery_charge` | no | cumulative/delta | **AC-side.** See [§7.2](15-data-quality-and-limits.md#72-known-modelling-limitations--state-these-in-the-ui-not-just-here) item 2 |
| `battery_discharge` | no | cumulative/delta | **AC-side.** |
| `price_spot` | yes³ | price | Bare EPEX, excl. markup, tax and VAT |
| `price_spot_min` | no | price | Intra-interval minimum. Enables [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) bracketing; cost simulation only |
| `price_spot_max` | no | price | Intra-interval maximum. Enables [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) bracketing; cost simulation only |
| `power_grid` | no | power | Signed W, import positive. Enables [§6.17](14-diagnostics.md#617-timestamp-misalignment-detection) checks |
| `house_load` | no | cumulative/delta | If supplied, overrides reconstruction ([§6.3](09-ingest-algorithms.md#63-household-load-reconstruction)) and enables a consistency check |

¹ `grid_import`/`grid_export` are accepted as aliases for the `_t1` variants where only a
single register was exported.

² Required exactly when the household declares solar PV
([§2.3](02-ux-wireframes.md#23-panel--parameter-configuration-expanded), `cfg.has_pv`).
A household without PV omits it, and the simulator treats production as zero throughout.
Supplying the series while declaring no PV, or declaring PV without supplying it, is a
configuration error and is caught by check 4 in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order) — the
absence of a solar series is never inferred to mean "no PV", because the far more common
cause is a user who has PV and forgot to map the inverter.

³ Required in both cost modes. The spot price drives the charge and discharge bands, which
decide which kWh the battery moves, so it is needed even when nothing is converted to
euros — see [§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model).

⁴ Dutch meters are required to measure the normaal and dal registers separately, so both
should be present. They are marked *expected* rather than *required* because the app runs
without them: a window with only T1 still yields correct energy results, and correct cost
results if the household is billed a single rate. A missing or permanently flat second
register is reported as a probable installation or mapping problem rather than accepted
silently — see [§6.4](09-ingest-algorithms.md#64-tariff-registers--availability-identification-and-use).

### Semantics of `kind`

- `cumulative` — monotonically increasing meter register. The value at time *t* is the
  reading *at* *t*. Deltas are derived by differencing
  ([§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas)).
- `delta` — energy consumed **during the interval starting at** `timestamp`. The interval
  length is inferred from the spacing to the next row of the same series.
- `price` — the price **valid from** `timestamp` until the next row of that series.

Mixing `cumulative` and `delta` across different series is allowed. Mixing them *within*
one series is rejected.

## 4.2 Wide format (convenience)

Accepted when every column shares one timestamp grid. Column headers are series names;
a `kind` is inferred per column (monotonic non-decreasing → `cumulative`, else `delta`)
with the inference reported back to the user for confirmation.

Because there is one timestamp column, every series in a wide file has the same native
resolution by construction. That is a property of the file rather than of the data, and it
is why long format is preferred: a household whose prices are quarter-hourly and whose meter
is hourly cannot express both in one wide file without either discarding the finer prices or
fabricating meter readings.

```csv
timestamp,grid_import_t1,grid_export_t1,solar_production,price_spot
2026-01-01T00:00:00+01:00,14203.412,2201.100,7734.220,0.0412
```
