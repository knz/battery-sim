# CSV import — Step 2: the pure wide-CSV parser

Companion to [20260805-csv-import-implementation-brief.md](20260805-csv-import-implementation-brief.md)
(the durable spec) and [20260805-csv-import.md](20260805-csv-import.md) (the decision record).
This file records only what Step 2 decided and built.

## Task specification

Build `app/domain/csv_wide.py`: a pure parser for the wide CSV format of
`docs/specs/05-data-formats.md` §4.2a, plus unit tests. No I/O, no clock, no filesystem — the
module takes text and returns data. Scope is Step 2 only: no storage layer, no routes, no
`CsvSource`, no JS. Add the DST-ambiguity bit to `QualityFlags`.

The required behaviour, the four decisions (D-TZ, D-DST, D-KIND, D-PRICE) and the test matrix
are all in the brief's "Step 2" section; they are not restated here.

## High-level decisions

**Two entry points, one shared parse.** The upload dialog needs only a summary (columns, row
count, resolution, first/last timestamp); a slot binding needs one column as a `SeriesFrame`.
Both need the same header + timestamp parse, so the module exposes `parse_wide_csv(text, tz)`
returning a `WideCsv` value object holding the UTC index and the raw per-column string cells,
and two thin functions over it: `summarise(wide)` and `column_frame(wide, column, name, unit)`.
Rationale: the routes layer parses once at upload to validate and summarise; the source layer
re-parses the stored file at load time and asks for one column. Keeping the cell strings
unparsed in `WideCsv` means the file-level checks (§4.2a: header, <2 columns, no data rows, bad
timestamp) are separated from the column-level checks (non-numeric, monotonic register) exactly
as the spec separates them — the first reject the file at upload, the second reject only a
binding on selection.

**Errors are one exception type carrying a machine code.** `CsvFormatError` with `.code` and a
message that names what was expected, what was found, and the 1-based row number as the user
sees it in a spreadsheet. Routes map it to a 400; the drawer shows the message. Distinct
exception classes per failure would multiply handlers for no gain, since every caller treats
them the same way (report and let the user retry).

**Warnings use `energy_frame`'s shape.** `list[dict]` with a `"code"` key
(`app/domain/ingest.py:145`), so the existing warning plumbing needs no new shape.

## Open-item decisions (the brief's "Open items" 1, 2, 4)

**1. Nonexistent March timestamps → reject the file.** Under `Europe/Amsterdam`, 02:00–03:00 on
the spring-forward day does not exist. Such a timestamp cannot be a real local reading, so it
signals the file is not in the zone the user declared (most often: it is really UTC, or already
shifted). Rejecting names the row and the likely cause. The alternatives were shifting forward
by the gap (invents a reading at a time the meter never recorded, and does it silently) and
dropping the row (loses data with no explanation). Detection uses
`zoneinfo`'s `fold` semantics indirectly: a local time is nonexistent iff converting to UTC and
back does not round-trip to the same wall clock.

**2. Monotonicity threshold.** A column is rejected as a cumulative register only when *all* of:
(a) it has at least `MONOTONIC_MIN_SAMPLES = 12` finite samples — below that "never decreases"
carries no information; (b) it never decreases, beyond `MONOTONIC_NOISE = 1e-9` of float dust;
**and** (c) its first and last finite values differ by more than `MONOTONIC_MIN_RISE = 1e-6`,
i.e. it actually *rises*. Condition (c) is what separates a real register from the degenerate
cases the brief names: a flat-zero column (an unused register, or a solar column for a night-only
file) and an all-constant column are non-decreasing but have zero rise, so they are **accepted as
ordinary per-interval data** — all zeros is a perfectly good per-interval series meaning "nothing
happened". Both tolerances are unit-free by design; at these magnitudes the kWh-vs-Wh factor of a
thousand is irrelevant, so the check runs on the file's own numbers before unit conversion.

Residual risk in **both** directions, measured rather than assumed (a reviewer ran these):

- *False positives are real, not theoretical.* Monotone partial-day solar is rejected — 5-minute
  PV dawn→noon (72 samples), 15-minute dawn→solar noon (28 samples), and a 13-sample 5-minute
  dawn ramp all return `cumulative_column`. A full day passes only because the afternoon decline
  breaks monotonicity, so the *window* decides, not the data. Accepted for this increment because
  the failure is loud, panel-local and recoverable, whereas the error it prevents (a register read
  as per-interval amounts) is silent and produces a plausible wrong answer. Better mitigations —
  comparing the column total against the window length, or letting the user override on
  rejection — need UI that Step 6 owns.
- *False negatives exist too.* A register spanning a meter reset (rises, drops to near zero,
  rises again) is not monotonic, so it is accepted and silently produces nonsense.
  `ingest.cumulative_to_delta` handles that case on the HA path; this path cannot, having decided
  not to difference anything (D-KIND).

Both are documented at the constants in `csv_wide.py` and pinned by tests.

**4. Gap representation for empty cells.** NaN value + `QualityFlags.GAP_FILLED`, matching
`cumulative_to_delta` (`ingest.py:160-161`), so both ingest paths agree. Whitespace-only cells
and the case-insensitive literals `nan`/`na`/`n/a`/`null`/`-` are treated the same way (§4.2
already says "Empty or `NaN` treated as a gap").

**Infinities are rejected, not mapped to gaps** (`code="non_finite_value"`). `float()` accepts
`inf` and overflows `1e400` to it, and NaN is the only non-finite value the pipeline handles:
`reconcile._resample_sum` neutralises NaN via `np.nan_to_num(..., nan=0.0)` and leaves an infinity
intact, so one such cell poisons every total downstream. Mapping to NaN would be arithmetically
safe but would report a *present, corrupt* reading as an absent one.

**A row 1 whose first cell parses as a timestamp is rejected as a missing header**
(`code="missing_header"`). Previously such a file parsed with its first reading eaten as the
header and its values as column names — silently one row short. Harness fixture 22 requires "no
header row" to be an upload failure, so without this the fixture was unimplementable at Step 8.

Also decided: **duplicate timestamps are not an error.** After the October fold-resolution two
rows can legitimately share a UTC instant; `infer_resolution_s` already ignores zero spacings.
Rows are sorted by UTC instant (stable, so original order breaks ties) rather than requiring the
file to be chronological.

## Files modified

- `app/domain/frames.py` — added `QualityFlags.DST_AMBIGUOUS = 1 << 5` and documented it.
- `app/domain/csv_wide.py` — **new.** The parser.
- `tests/test_csv_wide.py` — **new.** The Step 2 matrix.
- `changelog/20260805-csv-import-implementation-brief.md` — Step 2 `Status:` line.

## Current status

Step 2 complete: `uv run pytest tests/test_csv_wide.py tests/test_ingest.py` passes. Steps 3
(routes) and 4 (`CsvSource`) can now consume the API; see the brief's notes for what they need.
