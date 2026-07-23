# 4.3 Home Assistant ingestion

> **Purpose:** which HA API to use and why, the fetch strategy, and which statistics
> columns actually exist for which sensors.
> **Audience:** backend.
> **Read with:** [05-data-formats.md](05-data-formats.md) for the series vocabulary these
> statistics are mapped onto, and
> [14-diagnostics.md](14-diagnostics.md) for the diagnostics that depend on the min/max
> columns described here.

Use the **WebSocket API**, endpoint `recorder/statistics_during_period`, not the REST
history endpoint. Rationale:

- It returns the `sum` column of long-term statistics, which is already **corrected for
  meter resets** by HA's own `total_increasing` handling. Re-deriving this from raw states
  is a well-known source of spurious multi-thousand-kWh spikes.
- Long-term statistics are hourly and **never purged**; `states` and
  `statistics_short_term` default to ~10 days retention. For any window beyond ~10 days
  the REST history endpoint has nothing to offer and is dramatically heavier.

```
GET  /api/                              → connectivity + version check
WS   /api/websocket                     → auth with long-lived access token
     {type: "recorder/list_statistic_ids", statistic_type: "sum"}
     {type: "recorder/statistics_during_period",
      start_time, end_time, statistic_ids: [...],
      period: "5minute" | "hour" | "day"}
```

Fetch strategy: request `period: "hour"` for the full window, then additionally request
`period: "5minute"` for the trailing `ha_fine_window_days` (default 10, matching HA's
short-term retention above). Store both; the simulation grid selector
([§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling)) decides
which gets used. The 5-minute copy exists to power the resolution-bias diagnostic
([§6.13](14-diagnostics.md#613-resolution-bias-diagnostic)) even when the main run is
hourly.

This is the one case where a single series has two native resolutions over different parts
of the window. It stays **one series** in the granularity table and in the result object's
`series` block: the hourly spacing with its full coverage, and the 5-minute spacing with the
sub-window it covers, reported as `fine_resolution_s` and `fine_coverage`
([§4.5](07-internal-representation.md#45-result-object)). Splitting it into two rows would
double the table for a fact that applies uniformly to every energy series fetched this way.

Chunk requests to ≤ `ha_chunk_days` (default 90) per call to avoid oversized WebSocket
frames on large instances.

## Which statistics columns actually exist — this is not uniform

HA computes different aggregates depending on the sensor's `state_class`:

| `state_class` | Columns stored | Typical sensors |
|---|---|---|
| `total` / `total_increasing` | `sum`, `state`, `last_reset` | Grid import/export, solar production (if any), battery charge/discharge |
| `measurement` | `mean`, `min`, `max` | Spot price, power (W), voltage, SoC (%) |

The consequence is important and slightly counter-intuitive: **the energy meters have no
min/max/mean.** An hourly row for `sensor.grid_import` carries only the hourly total.
There is no intra-hour information to recover from it.

Where min/max/mean *are* available and useful:

- **Spot price sensors** are `measurement`, so an hourly row retains the min, max and mean
  of the underlying 15-minute prices. The mean is the price the simulation runs on and is
  fetched always, since the charge and discharge bands compare against it in both cost
  modes. The min and max support the bracketing in
  [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch),
  which is a cost diagnostic; they are fetched regardless, because they cost nothing extra
  in the same request and the user may enable cost simulation later without a refetch.
- **Power sensors**, if the user has them, retain hourly min/max/mean power. These enable
  the consistency and misalignment checks in
  [§6.17](14-diagnostics.md#617-timestamp-misalignment-detection) and reveal inverter
  clipping.
- **Battery SoC sensors** (%) retain min/max/mean, which gives a cheap sanity check
  against a simulated SoC trace when the user already owns a battery.

Request `price_spot` and any power sensors with all of `mean`, `min`, `max`; request
energy sensors with `sum` only.

## Reset handling

Because the `sum` column is already reset-corrected by HA, the reset logic in
[§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas) is applied
only to CSV input and to raw `state` series — not to statistics fetched here.

## Security

The long-lived access token is a full-privilege credential. It is encrypted at rest, never
logged, and the server binds to loopback by default. See
[§7.5](15-data-quality-and-limits.md#75-operational-notes) and
[§5.4](08-architecture.md#54-configuration).
