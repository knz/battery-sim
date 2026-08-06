# 4.1–4.2 CSV input formats

> **Purpose:** the series vocabulary, the file format each series is uploaded in, and what
> `kind` means.
> **Audience:** backend, integrators, and anyone writing an exporter.
> **Read with:** [02-ux-wireframes.md](02-ux-wireframes.md#the-csv-source)
> for the upload UI these formats are validated against,
> [06-home-assistant-ingestion.md](06-home-assistant-ingestion.md) for the other ingestion
> path, and [09-ingest-algorithms.md](09-ingest-algorithms.md) for what happens to these
> values after parsing.

## 4.1 The series vocabulary

These names identify the series internally — in `SeriesFrame.name`
([§4.4](07-internal-representation.md#44-internal-normalised-representation)), in
`series_meta` ([§5.1](08-architecture.md#51-layers)), and in the result object's `series`
block. On the Home Assistant path they name the rows of the mapping table. On the CSV path
they name the **slots a file's columns are bound to**: the user declares which series they are
providing by choosing, per slot, which file and column feeds it
([§4.2a](#42a-the-wide-multi-series-file-format)). An uploaded file is never required to contain
its own series name, and a column header is never interpreted as one.

| Series | Required | Kind | Notes |
|---|---|---|---|
| `grid_import_t1` | yes¹ | cumulative/delta | Normaal or dal — see [§6.4](09-ingest-algorithms.md#64-tariff-registers--availability-identification-and-use) |
| `grid_import_t2` | expected⁴ | cumulative/delta | |
| `grid_export_t1` | yes¹ | cumulative/delta | |
| `grid_export_t2` | expected⁴ | cumulative/delta | |
| `solar_production` | conditional² | cumulative/delta | AC output of the PV inverter. Required when the household declares PV, absent otherwise |
| `battery_charge` | no⁵ | cumulative/delta | **AC-side.** See [§7.2](15-data-quality-and-limits.md#72-known-modelling-limitations--state-these-in-the-ui-not-just-here) item 2 |
| `battery_discharge` | no⁵ | cumulative/delta | **AC-side.** |
| `price_spot` | yes³ | price | Bare EPEX, excl. markup, tax and VAT. Where its native spacing is finer than the simulation grid, [§6.16](14-diagnostics.md#616-price-bracketing-under-settlementresolution-mismatch)'s bracket is derived from it |
| `power_grid` | no | power | Signed W, import positive. Enables [§6.17](14-diagnostics.md#617-timestamp-misalignment-detection) checks |
| `house_load` | no | cumulative/delta | If supplied, overrides reconstruction ([§6.3](09-ingest-algorithms.md#63-household-load-reconstruction)) and enables a consistency check |

¹ A household whose meter exports a single import register and a single export register
fills the `_t1` slots and leaves `_t2` empty.

² Required exactly when the household declares solar PV in the setup band
([§2.1](02-ux-wireframes.md#21-overall-layout), `cfg.has_pv`). The slot is present in the data
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

⁵ Never required. The two existing-battery slots are *offered* in the data step only when the
household declares an existing battery in the setup band
([§2.1](02-ux-wireframes.md#21-overall-layout), `cfg.has_battery`); with the answer off they are
absent from the roster, with it on they appear as optional. They exist solely so
[§6.3](09-ingest-algorithms.md#63-household-load-reconstruction) can strip a battery the
household already owns from the reconstructed load. They say nothing about the battery being
**simulated**: panel ② configures that one, and the simulation assumes it replaces any
existing battery rather than building on its state. Unlike `solar_production` (footnote 2)
there is no consistency check against the declaration, because neither direction is an error —
a household with a battery may legitimately not have collected its sensors.

## 4.2 The per-series file format

> **Two CSV shapes exist.** This section specifies the **narrow** one — one file, one series,
> self-describing units and kind. [§4.2a](#42a-the-wide-multi-series-file-format) specifies the
> **wide** one, which is what the upload dialog in
> [§2.2](02-ux-wireframes.md#the-csv-source) actually accepts today. The narrow format is not
> implemented; it is retained because it is the shape an exporter written *for* this app should
> produce, and because its timestamp rule is the stricter and better one.

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
([§2.2](02-ux-wireframes.md#the-csv-source)). It is a recoverable,
panel-local condition: the other slots are unaffected and the session does not enter an
error state. This is what makes "the export I downloaded was the wrong one" an ordinary
event rather than a restart.

## 4.2a The wide, multi-series file format

This is the format the upload dialog accepts
([§2.2](02-ux-wireframes.md#the-csv-source)). It exists because real exports are wide: a
supplier's download or a Home Assistant dump carries a timestamp column followed by one column
per measurement, and splitting that into one file per series is manual work the app can spare
the user. **One uploaded file can therefore feed many slots**, each binding one column.

```csv
Tijdstip,Verbruik_T1,Verbruik_T2,Teruglevering_T1,Zon
01-01-2025 00:00:00,0.412,0.000,0.000,0.0
01-01-2025 01:00:00,0.388,0.000,0.000,0.0
01-01-2025 02:00:00,0.401,0.000,0.000,0.0
```

### Layout rules

| Position | Rules |
|---|---|
| Row 1 | **Required.** Holds the column names. Names are shown to the user in the column picker and are otherwise **never interpreted** — a column called `Verbruik_T1` is not thereby the `grid_import_t1` series. |
| Column 1 | The timestamp, `DD-MM-YYYY HH:MM:SS`, hours on a 24-hour clock. No offset (see below). |
| Columns 2…N | Values. `.` decimal separator, fractional supported. An empty cell is a **gap, not a zero**. At least one value column is required. |

### Timestamps carry no offset — the zone is answered once, at upload

Unlike [§4.2](#42-the-per-series-file-format), this format has no UTC offset in the data. The
upload dialog asks, per file, whether the timestamps are **Europe/Amsterdam local time** or
**UTC**, and the file is converted to UTC at upload time. Nothing downstream of the upload
ever sees a naive timestamp.

Under Europe/Amsterdam the hour repeated at the October transition is ambiguous. It resolves to
the **first** (CEST) occurrence, and the affected samples are flagged for the data-quality
report ([§7.3](15-data-quality-and-limits.md#73-data-quality-checks-in-execution-order)).
Deliberately *not* resolved by row order — see
[§2.2](02-ux-wireframes.md#the-upload-dialog) for why that alternative is worse than it looks.

This is a real weakening of §4.2's rule, accepted because the zone is stated explicitly by the
user rather than guessed, the conversion happens once at a known point, and the residual loss is
one flagged hour a year rather than a silent annual corruption.

### Units and kind are not in the file

Both move to the drawer, per slot ([§2.2](02-ux-wireframes.md#the-csv-source)):

- **Unit** is a radio beside the column picker: `kWh` (default) or `Wh`. The same file may
  legitimately hold columns in different units, which is why this is per binding and not per
  file. Energy slots only — price slots do not offer CSV in this increment, so none of §4.2's
  price units apply here.
- **Kind** does not exist. Every value column is a **per-interval amount** for the interval
  starting at its timestamp — the `delta` semantics of §4.2, and the same shape as
  `SeriesFrame.values` ([§4.4](07-internal-representation.md#44-internal-normalised-representation)).

**Cumulative meter registers are warned about, not differenced and not refused.** A column whose
values never decrease is **flagged on selection** with an explanation, and the user may proceed
anyway. Nothing is ever differenced here, which preserves §4.2's principle that a register
misread as per-interval amounts (or the reverse) produces a plausible and completely wrong
answer: the app does not guess at the ambiguity, it reports it and lets the user resolve it.

This started as a refusal, on the argument that a loud panel-local failure beats a silent wrong
number. That is sound about a genuine register and wrong about the detector, which cannot
distinguish one: monotonicity is a property of the *window*, not of the data's kind. Partial-day
data rises monotonically throughout — morning-only solar, or any window ending near solar noon —
so refusing cost a user with valid data their whole binding and offered no override. Flagging
costs a false positive one line of small print.

The cost of the trade is real and is accepted deliberately: a user who proceeds with a genuine
register gets a confidently wrong simulation, and the warning is the only signal they will get.
In practice the magnitudes differ by orders of magnitude — a register read as an hourly amount
yields thousands of kWh in an hour — so the error is usually self-evident in the result. The
suspect column is also named in §7.3's data-quality box, so the reason survives the run rather
than being a warning that was dismissed and forgotten.

A Dutch P1 export of cumulative registers — a common shape for this app's target household, and
what §4.1's table calls "cumulative/delta" — therefore still cannot be *correctly* used by this
format, and the flag is what says so. Differencing it is a natural later increment, and the
machinery already exists
([§6.1](09-ingest-algorithms.md#61-cumulative-meter-register--interval-deltas)). A better
discriminator than monotonicity would compare the column's total against the window length; that
is unbuilt.

### Resolution

Each column's native resolution is inferred from the spacing of the timestamp column, exactly as
in §4.2, and every column in one file necessarily shares it. A file whose spacing is irregular
is accepted with `resolution_s = None`; reconciliation onto the simulation grid is
[§6.2](09-ingest-algorithms.md#62-simulation-grid-selection-and-resampling)'s concern as usual.

### Validation and failure

File-level checks run **at upload** and reject the whole file: missing header row, fewer than
two columns, no data rows, or a first column that does not parse. Column-level checks run **on
selection** and reject only that binding: a non-numeric column, or a monotonic one per the rule
above. Either way the condition is panel-local and recoverable — the other slots and any other
uploaded file are untouched, and the session does not enter an error state
([§3.2](04-state-machine.md#32-events)).

### One format now, several later

Each series accepts exactly one format, the one specified above. Suppliers do not agree on
export shapes, so a later version is likely to accept several candidate formats per series
and try each in turn. Keep the per-slot validator behind an interface that admits more than
one format for a series; do not build a format registry or candidate-detection machinery
before there is a second format to hold.
