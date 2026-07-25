# 4.1–4.2 CSV input formats

> **Purpose:** the series vocabulary, the file format each series is uploaded in, and what
> `kind` means.
> **Audience:** backend, integrators, and anyone writing an exporter.
> **Read with:** [02-ux-wireframes.md](02-ux-wireframes.md#csv-variant-of-the-source-sub-panel)
> for the upload UI these formats are validated against,
> [06-home-assistant-ingestion.md](06-home-assistant-ingestion.md) for the other ingestion
> path, and [09-ingest-algorithms.md](09-ingest-algorithms.md) for what happens to these
> values after parsing.

## 4.1 The series vocabulary

These names identify the series internally — in `SeriesFrame.name`
([§4.4](07-internal-representation.md#44-internal-normalised-representation)), in
`series_meta` ([§5.1](08-architecture.md#51-layers)), and in the result object's `series`
block. On the Home Assistant path they name the rows of the mapping table. On the CSV path
they name the **upload slots**: the user declares which series they are providing by
choosing which slot to put the file in, and an uploaded file is never required to contain
its own series name.

| Series | Required | Kind | Notes |
|---|---|---|---|
| `grid_import_t1` | yes¹ | cumulative/delta | Normaal or dal — see [§6.4](09-ingest-algorithms.md#64-tariff-registers--availability-identification-and-use) |
| `grid_import_t2` | expected⁴ | cumulative/delta | |
| `grid_export_t1` | yes¹ | cumulative/delta | |
| `grid_export_t2` | expected⁴ | cumulative/delta | |
| `solar_production` | conditional² | cumulative/delta | AC output of the PV inverter. Required when the household declares PV, absent otherwise |
| `battery_charge` | no⁶ | cumulative/delta | **AC-side.** See [§7.2](15-data-quality-and-limits.md#72-known-modelling-limitations--state-these-in-the-ui-not-just-here) item 2 |
| `battery_discharge` | no⁶ | cumulative/delta | **AC-side.** |
| `price_spot` | yes³ | price | Bare EPEX, excl. markup, tax and VAT |
| `price_spot_min` | no⁵ | price | Intra-interval minimum. Enables [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) bracketing; cost simulation only |
| `price_spot_max` | no⁵ | price | Intra-interval maximum. Enables [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch) bracketing; cost simulation only |
| `power_grid` | no | power | Signed W, import positive. Enables [§6.17](14-diagnostics.md#617-timestamp-misalignment-detection) checks |
| `house_load` | no | cumulative/delta | If supplied, overrides reconstruction ([§6.3](09-ingest-algorithms.md#63-household-load-reconstruction)) and enables a consistency check |

¹ A household whose meter exports a single import register and a single export register
fills the `_t1` slots and leaves `_t2` empty.

² Required exactly when the household declares solar PV in the setup band
([§2.1](02-ux-wireframes.md#the-setup-band), `cfg.has_pv`). The slot is present in the data
step only under that declaration ([§2.2](02-ux-wireframes.md#22-panel--data-input-expanded)).
A household without PV omits it, and the simulator treats production as zero throughout.
Supplying the series while declaring no PV, or declaring PV without supplying it, is a
configuration error and is caught by check 4 in
[§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order) — the
absence of a solar series is never inferred to mean "no PV", because the far more common
cause is a user who has PV and did not collect the file for it.

³ Required in both cost modes. The spot price drives the charge and discharge bands, which
decide which kWh the battery moves, so it is needed even when nothing is converted to
euros — see [§1.4](01-product-brief.md#a-price-series-is-not-a-cost-model).

⁴ Dutch meters are required to measure the normaal and dal registers separately, so both
should be present. They are marked *expected* rather than *required* because the app runs
without them: a window with only T1 still yields correct energy results, and correct cost
results if the household is billed a single rate. A missing or permanently flat second
register is reported as a probable installation or export problem rather than accepted
silently — see [§6.4](09-ingest-algorithms.md#64-tariff-registers--availability-identification-and-use).

⁵ Never required. The min/max slots are *offered* in the data step only when the household
enables cost simulation in the setup band ([§2.1](02-ux-wireframes.md#the-setup-band),
`cfg.simulate_cost`), since the bracketing they feed qualifies a euro figure and has no
meaning in an energy-only run. With cost simulation off the slots are absent from the data
step; with it on they appear as optional. Supplying them is always optional even then.

⁶ Never required. The two existing-battery slots are *offered* in the data step only when the
household declares an existing battery in the setup band
([§2.1](02-ux-wireframes.md#the-setup-band), `cfg.has_battery`); with the answer off they are
absent from the roster, with it on they appear as optional. They exist solely so
[§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) can strip a battery the
household already owns from the reconstructed load. They say nothing about the battery being
**simulated**: panel ② configures that one, and the simulation assumes it replaces any
existing battery rather than building on its state. Unlike `solar_production` (footnote 2)
there is no consistency check against the declaration, because neither direction is an error —
a household with a battery may legitimately not have collected its sensors.

## 4.2 The per-series file format

One file carries one series. The file names its columns, not its series:

```csv
timestamp,value,unit,kind
2026-01-01T00:00:00+01:00,14203.412,kWh,cumulative
2026-01-01T01:00:00+01:00,14203.911,kWh,cumulative
2026-01-01T02:00:00+01:00,14204.503,kWh,cumulative
```

### Column rules

| Column | Type | Rules |
|---|---|---|
| `timestamp` | ISO 8601 | **Offset or `Z` is mandatory.** Naive timestamps are rejected — during the October DST transition a naive local timestamp is genuinely ambiguous and silently corrupts an hour of data every year. |
| `value` | float | `.` decimal separator. Empty or `NaN` treated as a gap, not as zero. |
| `unit` | enum | `kWh`, `Wh`, `MWh`, `EUR/kWh`, `EURcent/kWh`, `EUR/MWh`, `W`. Converted on ingest. Must be dimensionally consistent with the slot: an energy slot rejects `EUR/kWh`. |
| `kind` | enum | `cumulative`, `delta`, `price`. Constant within the file; a file that mixes them is rejected. |

`unit` and `kind` may each be given once as a header comment (`# unit: kWh`) instead of as
a column, since a single-series export commonly states them once rather than on every row.
Where either is absent altogether the file is rejected with the two acceptable ways to
supply it, rather than guessed — a `cumulative` register misread as `delta` produces a
plausible and completely wrong answer.

Each series' native resolution is inferred from the spacing of its own rows, retained, and
reported back to the user per series in panel ①
([§2.2](02-ux-wireframes.md#granularity-per-series)). Series legitimately arrive at
**different native resolutions** — hourly meter data, 15-minute prices, 5-minute recent
Home Assistant data — and one file per series is what lets each keep its own. The single
grid they are all reconciled onto is chosen later, in
[§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling), which is the
right place for that decision.

### Semantics of `kind`

- `cumulative` — monotonically increasing meter register. The value at time *t* is the
  reading *at* *t*. Deltas are derived by differencing
  ([§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas)).
- `delta` — energy consumed **during the interval starting at** `timestamp`. The interval
  length is inferred from the spacing to the next row.
- `price` — the price **valid from** `timestamp` until the next row.

Different series may use different kinds; a meter register arriving as `cumulative`
alongside a solar export arriving as `delta` is ordinary and fine.

### Validation and failure

A file is validated against the format expected for the slot it was uploaded into. Failure
is reported on that slot — what was expected, what was found, and where — and the user
supplies a different file for the same slot
([§2.2](02-ux-wireframes.md#csv-variant-of-the-source-sub-panel)). It is a recoverable,
panel-local condition: the other slots are unaffected and the session does not enter an
error state. This is what makes "the export I downloaded was the wrong one" an ordinary
event rather than a restart.

### One format now, several later

Each series accepts exactly one format, the one specified above. Suppliers do not agree on
export shapes, so a later version is likely to accept several candidate formats per series
and try each in turn. Keep the per-slot validator behind an interface that admits more than
one format for a series; do not build a format registry or candidate-detection machinery
before there is a second format to hold.
