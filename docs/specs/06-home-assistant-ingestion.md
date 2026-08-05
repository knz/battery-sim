# 4.3 Home Assistant ingestion

> **Purpose:** which HA API to use and why, where the fetch runs (the browser, not the
> backend), the fetch strategy, and which statistics columns actually exist for which sensors.
> **Audience:** frontend and backend.
> **Read with:** [05-data-formats.md](05-data-formats.md) for the series vocabulary these
> statistics are mapped onto, [08-architecture.md](08-architecture.md) §5.1 for where the
> pieces live, and
> [14-diagnostics.md](14-diagnostics.md) for the diagnostics that depend on the statistics
> columns described here.

## The fetch runs in the browser

The Home Assistant fetch is performed by the **user's browser**, not by the application
backend, and the fetched rows are then streamed to the backend to be normalised and
persisted. This is a deliberate inversion of the obvious "backend calls HA" design, and the
reason is where the two machines sit:

- A user's Home Assistant is typically reachable only from their own network — a
  `homeassistant.local` address, a LAN IP, often behind a self-signed certificate. The
  browser, running on the user's machine, can reach it. A hosted backend cannot. Building the
  fetch in the browser is what lets the same application be self-hosted today and
  centrally-hosted later without the data path changing.
- It keeps the **long-lived access token in the browser**. The token is a full-privilege
  credential ([§7.5](15-data-quality-and-limits.md#75-operational-notes)); the browser sends
  it only to the user's own Home Assistant, and it never reaches the application backend at
  all. There is no server-side token store to encrypt, leak, or subpoena.
- The browser handling the connection also means the browser handles the **TLS decision**: a
  self-signed LAN certificate is something the user's browser already knows how to prompt
  about and trust. The backend never makes a TLS connection to Home Assistant.

The backend's role is to receive already-fetched rows, normalise them
([§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas)), and persist
the resulting `SeriesFrame`s ([§4.4](07-internal-representation.md#44-internal-normalised-representation)).
It performs no HA I/O. This keeps the numerics in the pure domain layer and the "no
client-side computation" rule intact ([§5.1](08-architecture.md#51-diagram)): the browser is
a fetch-and-forward pipe, not a place where deltas or diagnostics are computed.

## The spot-price slot has preset sources, loaded by the backend

Home Assistant is not the only source the spot-price slot can be filled from. The slot also
offers **preset historical datasets — NL day-ahead spot prices from Energy-Charts and from
ENTSO-E** — and, unlike everything else in this file, those sources are loaded by the
**backend**, not the browser. This is the one deliberate exception to "the fetch runs in the
browser", and the
exception is justified by the same reasoning that put the HA fetch in the browser in the first
place: the Energy-Charts price API is a **public cloud endpoint** the backend can reach
directly, whereas a user's Home Assistant is LAN-only and can be reached only from the browser.
There is no LAN, no user token, and no self-signed certificate in the way, so nothing forces
this fetch into the browser and the backend can serve it more simply. The source abstraction
that carries this distinction is [§5.1](08-architecture.md#51-diagram): Home Assistant is a
`browser_fetch` source, the two preset price sources are `backend_load` sources.

How the backend serves the Energy-Charts source:

- **Committed on disk, bridged live.** The repository ships NL day-ahead prices from 2023 up to
  a recent tail as committed CSVs (`app/data/spot_prices/NL-YYYY.csv`,
  [§5.1](08-architecture.md#51-diagram)). At load time the source reads the committed points
  for the requested window and, when the window extends past the last committed interval,
  bridges the gap by calling the public API (`api.energy-charts.info/price?bzn=NL&start=…&end=…`)
  for just those trailing days. On-disk data is authoritative where the two overlap: the
  committed CSVs are the reviewable source of truth, and the bridge only extends them forward.
- **Units.** The API returns prices in **EUR/MWh**; the price kind the series vocabulary uses is
  **EUR/kWh** ([§4.1](05-data-formats.md#41-the-series-vocabulary)), so every value is divided
  by 1000 on the way in — both when the committed files are seeded and when the live tail is
  bridged.
- **Mixed native resolution.** The NL series is **hourly for older years and 15-minute** once
  the market moved to quarter-hourly (around 2025-09-30). The source preserves whatever spacing
  each interval was recorded at and does **not** resample. A window straddling that change
  therefore carries two native resolutions; reconciling them onto one simulation grid is the
  job of the grid selector
  ([§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling)), exactly as it
  is for the two-resolution HA case below, and not of this source.
- **Same normaliser as the HA price path.** The merged points are fed through the same price
  normaliser the HA price series uses, so the resulting `SeriesFrame` — its shape, resolution
  inference, and price kind — matches the HA path. This source decides only *where the points
  come from*, not how a price frame is built.

### The ENTSO-E source: the same series from an independent origin

The second preset source carries the same quantity — NL day-ahead spot prices — from the
**ENTSO-E transparency platform** rather than Energy-Charts. Having two independent origins for
one series means a run can be repeated against either, and the two compared; on the overlapping
years they have been checked to agree on every interval.

- **Purely on-disk, no bridge.** It is backed by raw monthly ENTSO-E exports, a static corpus
  with no live endpoint behind it, so — unlike Energy-Charts — nothing bridges to `now`. A
  window past the last extracted interval simply yields the rows that exist. Extending coverage
  means adding raw dumps and re-running `scripts/extract_entsoe_prices.py`. Consequently this
  source makes **no outbound request at all** at fetch time.
- **Earlier coverage.** The extract starts mid-2022, where the Energy-Charts dataset starts in
  2023. That is why both are offered rather than one replacing the other.
- **Per-interval resolution recorded.** The committed extract
  (`app/data/spot_prices_entsoe/NL-YYYY.csv`) carries a third column giving each interval's own
  native length in seconds (3600 or 900), because the hourly and quarter-hourly regimes coexist
  within the 2025 file. Nothing is resampled on the way in. Note that the frame built from these
  rows still carries a single inferred `resolution_s`, so the per-interval truth is currently
  preserved *at rest* rather than propagated into the frame; consuming it properly is the grid
  selector's job ([§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling)).

The one outbound request either preset source makes — and only the Energy-Charts one makes it,
the ENTSO-E source being purely on-disk — carries a bidding zone (`NL`) and a date range, with
no user or energy data attached. It fires only at **fetch time** — when a fetch reifies a
configuration in which that source is staged for the spot-price slot
([§2.2](02-ux-wireframes.md), §3.5), and only then if the requested window extends past the
committed tail. Selecting either source in the drawer stages it but loads nothing; no request
fires on selection. That egress is described in
[§7.5](15-data-quality-and-limits.md#75-operational-notes) alongside the HA requests; it is the
backend's only one.

There is no separate slot for the intra-interval price minimum and maximum, from this source
or any other:
[§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)'s bracket
is derived from whatever spot series is loaded, on its own native spacing.

## Which HA API, and why

Use the **WebSocket API**, endpoint `recorder/statistics_during_period`, not the REST
history endpoint. Rationale:

- It returns the `sum` column of long-term statistics, which is already **corrected for
  meter resets** by HA's own `total_increasing` handling. Re-deriving this from raw states
  is a well-known source of spurious multi-thousand-kWh spikes.
- Long-term statistics are hourly and **never purged**; `states` and
  `statistics_short_term` default to ~10 days retention. For any window beyond ~10 days
  the REST history endpoint has nothing to offer and is dramatically heavier.

```
WS   wss://<user-ha>/api/websocket        → auth with long-lived access token (in browser)
     {type: "recorder/list_statistic_ids", statistic_type: "sum" | "mean"}
     {type: "recorder/statistics_during_period",
      start_time, end_time, statistic_ids: [...],
      period: "5minute" | "hour" | "day", types: ["sum"] | ["mean"]}
```

`list_statistic_ids` populates the mapping dropdowns (energy `sum` ids for the energy slots,
`mean` ids for the price/power slots). The user binds each series slot
([§4.1](05-data-formats.md#41-the-series-vocabulary)) to one statistic id, and **Fetch
history** runs the statistics calls.

Fetch strategy: request `period: "hour"` for the full window, then additionally request
`period: "5minute"` for the trailing `ha_fine_window_days` (default 10, matching HA's
short-term retention above). Both are sent to the backend; the simulation grid selector
([§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling)) decides which
gets used. The 5-minute copy exists to power the resolution-bias diagnostic
([§6.13](14-diagnostics.md#613-resolution-bias-diagnostic)) even when the main run is hourly.

This is the one case where a single series has two native resolutions over different parts
of the window. It stays **one series** in the granularity table and in the result object's
`series` block: the hourly spacing with its full coverage, and the 5-minute spacing with the
sub-window it covers, reported as `fine_resolution_s` and `fine_coverage`
([§4.5](07-internal-representation.md#45-result-object)). Splitting it into two rows would
double the table for a fact that applies uniformly to every energy series fetched this way.

**The two native resolutions must never be differenced across each other.** The hourly copy
and the 5-minute copy overlap in time, and the 5-minute copy's cumulative register restarts
at a lower value than the hourly copy's tail. Concatenating them into one register and
differencing produces a large spurious negative step — read as a meter reset or an ambiguous
decrease — exactly at the overlap. Each resolution is differenced only within itself: the
hourly copy becomes the series' `SeriesFrame`, and the 5-minute copy contributes only its
resolution and coverage. The browser labels every batch of rows it forwards with its
`period` so the backend keeps them apart; this is asserted by an ingest-path regression test
(`test_two_resolutions_are_not_differenced_together`).

Chunk requests to ≤ `ha_chunk_days` (default 90) per call to avoid oversized WebSocket
frames on large instances. Chunk boundaries are contiguous and the backend differences the
reassembled per-resolution register, so a chunk edge is not a series edge.

## Browser → backend hand-off

The browser streams the fetched rows to the backend over a **WebSocket** (`WS
/data/ingest/ws`). WebSocket, not a streamed HTTP body: it is supported by every browser
without the HTTP/2 request-streaming dependency, and it gives per-chunk progress back to the
UI. The protocol is a `header` (the requested window, plus the setup-band answers this fetch
commits — see below), then per mapped series a `series` declaration followed by one or more
`rows` batches (each labelled with its `period`), then a
`done`. The backend accumulates per series, builds `SeriesFrame`s on `done`, persists them
([§5.1](08-architecture.md#51-diagram), [§3.5](04-state-machine.md#35-persistence-points)),
and replies with the dataset id and the panel-① granularity report, or an `error` that maps
to `LOAD_FAILED` ([§3.2](04-state-machine.md#32-events)). The payload stays bounded because
the 5-minute copy is capped to the trailing `ha_fine_window_days`; a two-year hourly window
plus a ten-day fine window is on the order of tens of thousands of rows per series, low tens
of megabytes in total.

**The `header` also carries the setup-band answers**, `has_pv` and `has_battery`
([§2.1](02-ux-wireframes.md#21-overall-layout)). The fetch is what commits the whole data
configuration, and these two answers are part of it — they decide which slots the roster
offered in the first place, so persisting them anywhere else would let the stored answers
disagree with the dataset they produced. Both fields are **optional**: a client that omits one
leaves the stored answer unchanged, so an older browser cannot silently reset the user's
configuration.

They are persisted **after** the dataset is written and the source generation bumped, and
deliberately outside the all-or-nothing guarantee that covers the frames. A failed fetch must
leave the answers alone — nothing was loaded for them to describe — while a configuration that
cannot be written must not discard a dataset that already was. The residual risk is a stored
dataset whose answers did not persist; it is self-correcting, since the next fetch writes both
again.

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
  of the underlying 15-minute prices. Only the **mean** is requested and only the mean is
  ingested: it is the price the simulation runs on, since the charge and discharge bands
  compare against it in both cost modes.
  [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)'s
  bracket does **not** come from this statistic's own min and max. It is derived from the
  spot series' native spacing during resampling, so that the quantity has one definition
  rather than varying by whether the series arrived from HA or from a preset source — and
  an HA row at hourly resolution against an hourly grid yields no spread either way.
- **Power sensors**, if the user has them, retain hourly min/max/mean power. These enable
  the consistency and misalignment checks in
  [§6.17](14-diagnostics.md#617-timestamp-misalignment-detection) and reveal inverter
  clipping.
- **Battery SoC sensors** (%) retain min/max/mean, which gives a cheap sanity check
  against a simulated SoC trace when the user already owns a battery.

Request `price_spot` with `mean` only and energy sensors with `sum` only. The wire format
carries one value per price row accordingly. A power slot, if one is ever built, would need
`min` and `max` for the §6.17 checks above; nothing requests them today.

**Units are not reliably in the statistics metadata.** On instances observed in practice,
`list_statistic_ids` and `get_statistics_metadata` return `unit_of_measurement: null` for
recorder- and integration-provided sensors. The unit therefore cannot be read from the
statistics API alone. Read it from the entity's live state
(`GET /api/states/<entity_id>` → `attributes.unit_of_measurement`) as a fallback, and
surface it for the user to confirm rather than guessing — a register read as `Wh` when it is
`kWh` is off by a factor of a thousand and otherwise plausible. The unit lookup, like the
statistics fetch, runs in the browser.

## Reset handling

Because the `sum` column is already reset-corrected by HA, the reset logic in
[§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas) rarely fires on
statistics fetched here. It is still applied — the backend differences the `sum` register
itself so the reset and gap semantics match the CSV path exactly — but on already-corrected
data it is close to a no-op. The logic in [§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas)
is applied to CSV input and to raw `state` series as before.

## Security

The long-lived access token is a full-privilege credential. It **stays in the browser**
(held in the browser's local storage) and is sent only to the Home Assistant instance the
user entered; it never reaches the application backend, so there is no server-side token to
store or encrypt. The backend binds to loopback by default. See
[§7.5](15-data-quality-and-limits.md#75-operational-notes) and
[§5.4](08-architecture.md#54-configuration).
