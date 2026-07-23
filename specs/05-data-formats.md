# 4.1–4.2 CSV input formats

> **Purpose:** the two accepted CSV shapes, the series vocabulary, and what `kind` means.
> **Audience:** backend, integrators, and anyone writing an exporter.
> **Read with:** [06-home-assistant-ingestion.md](06-home-assistant-ingestion.md) for the
> other ingestion path, and [09-ingest-algorithms.md](09-ingest-algorithms.md) for what
> happens to these values after parsing.

## 4.1 Canonical CSV — long format (preferred)

Long format is canonical because series legitimately arrive at **different resolutions**
(hourly meter data, 15-minute prices, 5-minute recent HA data). A wide format would force
a common grid at ingestion time, which is precisely the wrong place to make that decision;
the grid is chosen later, in [§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling).

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
| `grid_import_t1` | yes¹ | cumulative/delta | Normaal or dal — see [§6.4](09-ingest-algorithms.md#64-tariff-register-identification-and-zone-assignment) |
| `grid_import_t2` | no | cumulative/delta | Omit if the meter has a single register |
| `grid_export_t1` | yes¹ | cumulative/delta | |
| `grid_export_t2` | no | cumulative/delta | |
| `solar_production` | yes | cumulative/delta | AC output of the PV inverter |
| `battery_charge` | no | cumulative/delta | **AC-side.** See [§7.2](15-data-quality-and-limits.md#72-known-modelling-limitations--state-these-in-the-ui-not-just-here) item 2 |
| `battery_discharge` | no | cumulative/delta | **AC-side.** |
| `price_spot` | conditional | price | Required for dynamic pricing. Bare EPEX, excl. markup, tax and VAT |
| `price_spot_min` | no | price | Intra-interval minimum. Enables [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) bracketing |
| `price_spot_max` | no | price | Intra-interval maximum. Enables [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) bracketing |
| `power_grid` | no | power | Signed W, import positive. Enables [§6.17](14-diagnostics.md#617-timestamp-misalignment-detection) checks |
| `house_load` | no | cumulative/delta | If supplied, overrides reconstruction ([§6.3](09-ingest-algorithms.md#63-household-load-reconstruction)) and enables a consistency check |

¹ `grid_import`/`grid_export` are accepted as aliases for the `_t1` variants when the
meter is not split.

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

```csv
timestamp,grid_import_t1,grid_export_t1,solar_production,price_spot
2026-01-01T00:00:00+01:00,14203.412,2201.100,7734.220,0.0412
```
