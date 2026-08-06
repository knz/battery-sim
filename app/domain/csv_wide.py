"""The wide multi-series CSV format → SeriesFrame (specs §4.2a, §7.3 checks 1 and 2).

Pure: text in, data out. No filesystem, no clock, no HTTP — the upload route writes the bytes
and the source adapter reads them back; this module only interprets them. That split is what lets
the same parse run twice on different sides of persistence (once at upload to validate and
summarise for the dialog, once at load to build one slot's frame) with no shared state.

## The format

    Tijdstip,Verbruik_T1,Verbruik_T2,Teruglevering_T1,Zon
    01-01-2025 00:00:00,0.412,0.000,0.000,0.0
    01-01-2025 01:00:00,0.388,0.000,0.000,0.0

Row 1 is required and holds column names, which are **shown to the user and never interpreted** —
a column called `Verbruik_T1` is not thereby the `grid_import_t1` series. Column 1 is a naive
timestamp `DD-MM-YYYY HH:MM:SS` on a 24-hour clock. Columns 2..N are values whose decimal
separator may be `.` or `,`, decided **per cell** (see below); an empty cell is a **gap, not a
zero**. Neither unit nor kind appears in the file:
unit is a per-binding radio (kWh default, or Wh) and kind does not exist — every value column is
a per-interval amount for the interval starting at its timestamp.

## The decimal separator is a per-CELL property (D-DELIM-SCOPE)

Not per file, and not per column. That is not a generalisation for its own sake — it is what the
data required. The example that forced it (`voorbeeld.csv`, 96 rows, header
`DatumTijd,Import,Export,Opwek`) mixes both conventions row by row **inside a single column**:

    25-08-2024 10:00:00,0.08,0.07,0
    25-08-2024 10:15:00,"1,9",0,0
    ...
    25-08-2024 11:00:00,0.13,0.93,"0,55"

Every dot-decimal cell is unquoted and every comma-decimal cell is quoted — the exporter quoted
exactly those cells it comma-formatted. A per-file rule cannot read this file at all, and a
per-column rule cannot either, because `Import` holds both `0.08` and `"1,9"` four rows apart.
So each cell is decided on its own characters, with no state carried between cells.

What makes that cheap is the reject-if-both rule: a cell containing one separator is
unambiguous, so there is no thousands-separator inference, no ordering dependency and no
file-wide accumulator. A cell containing both (`1.234,56`, `1,234.56`) is refused rather than
guessed — the two readings differ by a factor of a thousand, and this format does not accept a
thousands separator at all. `_decimal_normalised` is the whole implementation.

This does **not** loosen the row-length guard, and the two are deliberately not connected. Per-
cell reading only ever helps a comma cell that arrived as ONE field, which in practice means a
quoted one. A bare `0,412` is split by the tokenizer into two fields before this module ever
looks at a cell, so it is still rejected by the length check in `parse_wide_csv` — reading it
would be wrong by a factor of a thousand. Accepting `"1,9"` therefore never licenses accepting
`1,9`, and a paired regression test pins both halves together.

## Two-stage parsing, mirroring where the user acts

§4.2a separates file-level checks from column-level ones because the user acts twice, in two
places, and a failure must be reported where it happened:

  * **File level, at upload** (`parse_wide_csv`): no header, fewer than two columns, no data
    rows, a first column that does not parse. These reject the whole file.
  * **Column level, on selection** (`column_frame`): a non-numeric column rejects only that one
    binding; the file and every other slot keep working. A column that looks like a cumulative
    register does NOT reject — it warns and proceeds (see below).

So `parse_wide_csv` returns a `WideCsv` holding the resolved UTC index plus the value columns
**still as strings**. Nothing about column 3 can invalidate an upload whose column 2 the user
wanted. `summarise` reads the dialog's summary off that object; `column_frame` promotes one
column to a `SeriesFrame`.

## The timezone is applied here, once (D-TZ)

The format carries no offset, so the dialog asks per file: `Europe/Amsterdam` or `UTC`, and this
module converts to UTC immediately. Nothing downstream ever sees a naive timestamp. The label
says "Amsterdam" and not "the Netherlands" because the Caribbean Netherlands are on AST with no
DST. Under `UTC` the conversion is the identity and no DST question arises.

Under `Europe/Amsterdam` the two transition days need explicit answers, and the spec gives only
one of them:

  * **October (the repeated hour) — resolve to the first, CEST, occurrence and flag it**
    (§4.2a, §7.3 check 1). `QualityFlags.DST_AMBIGUOUS` is raised on those samples so the
    data-quality box can name the day. Deliberately *not* resolved by row order (first of a pair
    = CEST, second = CET): that recovers the hour exactly for a well-formed chronological export,
    but a file with a gap across the boundary — one row of the pair missing, which is precisely
    the file most likely to have collection problems — would then be silently misdated with no
    flag at all. A rule that is always right about being unsure beats one that is usually right
    and never says so.

    The cost of that rule on a full-day October file, stated so nobody rediscovers it as a bug:
    both rows of the pair resolve to the same UTC instant, so the index carries a **duplicate
    entry** at 00:00 UTC and **no row at all** for 01:00 UTC. `reconcile._resample_sum` sums with
    `np.add.at`, so total energy over the window is conserved, but that one hour reads double and
    the next reads zero. And only the two 02:00 rows carry `DST_AMBIGUOUS` — the zeroed 01:00
    interval does not exist to be flagged — so the quality box names half the affected intervals.
    This follows §4.2a as written and is deliberately not worked around here; fixing it means
    changing the spec's resolution rule, not the parser.

  * **March (the nonexistent hour) — reject the file.** DECIDED HERE; the spec is silent (the
    implementation brief's open item 1). A local time inside the spring-forward gap never
    happened, so a meter cannot have recorded a reading at it. Its presence means the file is not
    in the zone the user declared — most often it is really UTC, or was already shifted — and
    that misdeclaration affects every row, not just the offending one. Rejecting names the row
    and the likely cause. The alternatives are worse: shifting the row forward by the gap invents
    a reading at a wall-clock time the meter never saw, and dropping it discards data silently.
    A user whose file legitimately contains those timestamps declares UTC instead.

## Cumulative registers are WARNED about, not differenced and not refused (D-KIND)

§4.2a: a column whose values never decrease reads as a meter register, and this format does not
accept registers. It is never differenced — `ingest.cumulative_to_delta` exists for the HA path
and is deliberately not called here — because a register misread as per-interval amounts (or the
reverse) produces a plausible and completely wrong answer.

But it is no longer REFUSED either. `column_frame` emits a `CSV_CUMULATIVE_COLUMN` warning and
returns the frame, and the drawer shows small print beside the column picker; the user can
proceed. That is a decision by the user of this app, taken with the cost stated: proceeding with
a genuine register yields a confidently wrong simulation with no other signal.

The reason it is the better trade is the false positive documented at MONOTONIC_MIN_SAMPLES
below. The detector cannot distinguish a register from a monotonically rising per-interval
column, and partial-day solar is exactly that shape — morning-only PV, or a window ending at
solar noon, is ordinary valid data and was refused. Refusing cost the user their data with no
way to override; warning costs them a line of small print. The threshold is unchanged and the
false positive is unchanged; only what happens next is.

See `_looks_cumulative` for the threshold and why the degenerate non-decreasing cases (an
all-zero unused register, an all-constant column, a very short file) are not flagged at all.

Main items:
    TIMESTAMP_FORMAT, AMSTERDAM_TZ, UTC_TZ    the format string and the two declarable zones.
    UNIT_FACTORS                              kWh (identity) and Wh (÷1000).
    MONOTONIC_MIN_SAMPLES/_MIN_RISE/_NOISE    the register-DETECTION threshold (open item 2),
                                              with its measured residual risk both ways. What it
                                              triggers is a warning, not a rejection.
    GAP_TOKENS                                cell spellings that mean "gap, not zero".
    _decimal_normalised(text, column, row)    one cell's `.`/`,` decision; rejects a cell holding
                                              both (D-DELIM-SCOPE).
    CsvFormatError                            one error type, carrying a machine-readable `code`.
    WideCsv                                   parsed file: columns, UTC index, string cells,
                                              resolution, and the DST-ambiguity mask.
    WideCsvSummary                             what the upload dialog displays.
    parse_wide_csv(text, tz)                  file-level parse (§4.2a upload checks).
    summarise(wide)                           WideCsv → WideCsvSummary.
    column_frame(wide, column, name, unit)    column-level parse → (SeriesFrame, warnings).
    parse_and_summarise(text, tz)             convenience for the upload route.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

from app.domain.frames import QUALITY_DTYPE, QualityFlags, SeriesFrame
from app.domain.ingest import infer_resolution_s

# --- format constants (specs §4.2a) ---------------------------------------------------------

# `DD-MM-YYYY HH:MM:SS`, 24-hour clock, no offset. Parsed with `strptime`, which is strict about
# separators and refuses a 24-hour value above 23 — the two mistakes worth catching. Day-first is
# the Dutch convention and the reason the format cannot be guessed: `01-02-2025` is a valid date
# under either reading, so an ISO-tolerant parser would silently transpose day and month for
# eleven days in twelve.
TIMESTAMP_FORMAT = "%d-%m-%Y %H:%M:%S"

# The two zones the upload dialog offers (D-TZ). Both are stdlib `zoneinfo` keys; Python's floor
# for this project is 3.12 (pyproject.toml), so no backport is needed. `TZ_KEYS` is what a route
# validates a submitted form value against, so an unknown zone never reaches the parser.
AMSTERDAM_TZ = "Europe/Amsterdam"
UTC_TZ = "UTC"
TZ_KEYS: tuple[str, ...] = (AMSTERDAM_TZ, UTC_TZ)

# Per-binding unit (§4.2a "Units and kind are not in the file"). Energy slots only, so the whole
# vocabulary is the two energy units the drawer's radio offers; §4.2's MWh and price units do not
# apply on this path (D-PRICE). The factor converts the file's number to kWh, which is what
# `SeriesFrame.values` holds for an energy series.
UNIT_FACTORS: dict[str, float] = {"kWh": 1.0, "Wh": 0.001}

# Cell spellings that mean "no reading here" rather than "zero" (§4.2a: an empty cell is a gap,
# not a zero; §4.2 adds `NaN` to the same rule). Compared case-folded after stripping whitespace.
# `-` is included because spreadsheet exports use it for a blank; a lone minus sign is not a
# number under any reading, so nothing numeric is lost by claiming the spelling.
GAP_TOKENS: frozenset[str] = frozenset({"", "nan", "na", "n/a", "null", "none", "-"})


def _decimal_normalised(text: str, column: str, row: int) -> str:
    """One stripped, non-gap cell → the same text with `,` read as a decimal point.

    The decimal separator is a property of the **cell**, not of the file and not of the column
    (D-DELIM-SCOPE; see the module docstring for the observed export that forces this). So this
    decides on the cell's own two characters and carries no state between calls:

      * neither `,` nor `.` — unchanged;
      * `.` only — unchanged, byte for byte. This is the pre-existing path and must stay exactly
        what `float()` saw before, so no already-working file can change value;
      * `,` only — every `,` becomes `.`;
      * both — **rejected** here, before `float()` is tried. A cell holding both is almost always
        a thousands separator (`1.234,56` or `1,234.56`), where either reading is a factor of a
        thousand away from the other. Rejecting explicitly, rather than letting `float()` fail
        with the generic `non_numeric_value`, is what lets the message name the actual problem.

    Only the two characters are examined; the rest is left to `float()`. So `1,234,567` is not
    special-cased and falls through to `non_numeric_value` — there is no "multiple commas" code,
    because "not a number" already says it. `1,5e3` becomes `1.5e3` = 1500.0 as a consequence of
    the substitution; it is accepted rather than fought, not promised as a feature. (`float()`
    also accepts `1_000` per PEP 515. That quirk pre-dates this function and is untouched by it.)

    `column` and `row` are only there to build the error message.
    """
    has_comma = "," in text
    if not has_comma:
        return text
    if "." in text:
        raise CsvFormatError(
            "mixed_decimal_separator",
            f"Column {column!r}: {text!r} on row {row} contains both a dot and a comma, so it "
            f"is unclear which one is the decimal separator. Each value must use one or the "
            f"other — 1234.56 or 1234,56 — and no thousands separator.",
            row=row,
        )
    return text.replace(",", ".")

# --- register detection threshold (implementation brief, open item 2) -----------------------
#
# "Never decreases" alone is not a usable test for "is a cumulative register", because three
# ordinary per-interval columns satisfy it:
#
#   1. A column that is flat zero — an unused meter register, or a solar column over a window
#      with no daylight. Non-decreasing, and completely ordinary per-interval data whose correct
#      reading is "nothing happened in any interval".
#   2. Any all-constant column, for the same reason.
#   3. A very short column. With two rows, "non-decreasing" is a coin flip: half of all
#      two-sample per-interval columns would be rejected as registers.
#
# So the test is a conjunction of three conditions, and a column must fail to be a register:
#
#   * at least MONOTONIC_MIN_SAMPLES finite samples, so the ordering carries information. At 12
#     samples, the chance that genuinely unordered per-interval data happens to arrive sorted is
#     1/12! ≈ 2e-9 — small enough to accept, and 12 is half a day of hourly data, so no
#     plausible real upload is too short to be checked.
#   * no decrease beyond MONOTONIC_NOISE. That tolerance is float dust only (1e-9), NOT the
#     0.01 kWh of `ingest.RESET_TOLERANCE_KWH`: that constant exists to decide whether a
#     *register* dipped, where the answer changes the value; here a genuine 0.005 kWh decrease is
#     decisive evidence the column is not a register, and treating it as noise would throw away
#     exactly the signal being tested for.
#   * a total rise above MONOTONIC_MIN_RISE. This is what separates cases 1 and 2 above from a
#     real register: a register accumulates, while a flat or constant column rises by exactly
#     nothing. The threshold is a hair above zero rather than a meaningful energy, because the
#     distinction being drawn is "rises at all".
#
# Both tolerances are deliberately unit-free (no `_KWH` suffix): the check runs on the file's own
# numbers, and at 1e-9/1e-6 the kWh-vs-Wh factor of a thousand is far below any real reading
# either way, so converting first would buy nothing but a false precision in the name.
#
# ## Residual risk, in both directions — measured, not assumed
#
# **False positives (ordinary data flagged) are real, not theoretical.** Any column that rises
# monotonically across the whole file is flagged, and partial-day solar does exactly that:
# 5-minute PV from dawn to noon (72 samples), 15-minute PV from dawn to solar noon (28 samples),
# and even a 13-sample 5-minute dawn ramp are all flagged. A *full* day is not, only because the
# afternoon decline breaks monotonicity — so the shape of the window, not the shape of the data,
# decides. A user who uploads a morning-only export, or slices a window ending at midday, will be
# told their PV column looks like a meter register. That is wrong and it will happen.
#
# That false positive is why the flag is a WARNING and not a rejection. It used to reject, on the
# argument that a loud panel-local failure beats a plausible wrong answer — which is sound about
# registers and wrong about the false positive, where a loud failure blocks correct data and the
# user has no override. So the consequence moved: `column_frame` warns, the drawer prints one line
# beside the column picker, and the user decides. The cost of that trade, stated because it is
# real and was accepted knowingly: a user who proceeds with a genuine register gets a confidently
# wrong simulation and the small print is the only signal they will ever get. Better mitigations
# are still unbuilt — comparing the column's total against the window length would separate the two
# cases far more reliably than monotonicity does.
#
# **False negatives (registers not flagged) also exist.** A register spanning a meter reset — the
# sequence rises, drops to near zero, rises again — is not monotonic, so it is accepted as
# per-interval data with no warning at all and silently produces nonsense.
# `ingest.cumulative_to_delta` handles exactly
# that case on the HA path; this path cannot, because it has already decided not to difference
# anything (D-KIND). A reset inside an uploaded wide CSV is therefore undetected here.
MONOTONIC_MIN_SAMPLES = 12
MONOTONIC_NOISE = 1e-9
MONOTONIC_MIN_RISE = 1e-6


class CsvFormatError(ValueError):
    """A wide-CSV file or column was rejected (§4.2a "Validation and failure").

    One exception type for every rejection, carrying a machine-readable `code` alongside the
    human message, because every caller does the same thing with it: report it where the user
    acted and let them retry. A class per failure mode would multiply handlers for no gain.

    Messages follow §4.2a's rule — what was expected, what was found, and *where*. `row` is the
    1-based line number **as a spreadsheet shows it** (the header is row 1), which is the only
    numbering the user can act on; it is None for whole-file and column-level failures that have
    no single offending row.
    """

    def __init__(self, code: str, message: str, *, row: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.row = row


@dataclass(frozen=True)
class WideCsv:
    """A parsed wide CSV: timestamps resolved to UTC, values still as text.

        columns        the value-column names from row 1, in file order (column 1, the
                       timestamp, is not among them). Display-only; never interpreted.
        timestamp_name row 1's first cell, kept so the dialog can echo what it treated as the
                       timestamp column.
        index          np.datetime64[s], UTC interval starts, ascending. One entry per data row.
        cells          column name → the row-aligned raw strings for that column.
        resolution_s   modal spacing, or None if irregular (`infer_resolution_s`).
        tz             the zone the user declared, as passed in.
        ambiguous      bool mask, row-aligned: True where a local timestamp fell in the repeated
                       October hour and was resolved to its CEST occurrence (D-DST). All False
                       for a UTC-declared file.
        line_numbers   row-aligned original file line of each row (header = line 1), carried
                       through the sort so a column-level rejection can name a line the user can
                       actually find.

    Values stay as strings deliberately: a non-numeric or cumulative column must reject only its
    own binding, not the upload (§4.2a), so no value is interpreted until a column is chosen.
    """

    columns: tuple[str, ...]
    timestamp_name: str
    index: np.ndarray
    cells: dict[str, list[str]]
    resolution_s: int | None
    tz: str
    ambiguous: np.ndarray
    line_numbers: tuple[int, ...]

    @property
    def rows(self) -> int:
        return len(self.index)


@dataclass(frozen=True)
class WideCsvSummary:
    """What the upload dialog and the drawer's file selector display about a stored file.

    Deliberately JSON-shaped scalars only (no numpy, no naive datetimes): this crosses the
    HTTP boundary to the dialog and is the shape the `uploads` row persists (step 1 of the
    implementation brief). `first_ts`/`last_ts` are tz-aware UTC and None for... nothing, in
    practice, since a file with no data rows is rejected before a summary exists — but the
    Optional is kept so the type does not lie about an empty index.
    """

    columns: tuple[str, ...]
    timestamp_name: str
    rows: int
    resolution_s: int | None
    first_ts: datetime | None
    last_ts: datetime | None
    tz: str
    ambiguous_rows: int


# --- timestamp resolution -------------------------------------------------------------------

def _resolve_local(naive: datetime, zone: ZoneInfo, row: int) -> tuple[datetime, bool]:
    """One naive local timestamp → (tz-aware UTC datetime, was_ambiguous).

    `fold=0` selects the *first* occurrence of a repeated wall clock, which is CEST at the
    October transition — exactly D-DST's rule. So the plain attachment already resolves the
    ambiguity correctly; what remains is to *detect* the two transition cases, since a flag
    (October) and a rejection (March) hang on them.

    Both are detected by round-tripping through UTC, which needs no transition table:

      * **Nonexistent** (March): with `fold=0`, a wall clock inside the gap converts to a UTC
        instant whose own local rendering is a *different* wall clock — the offset that applied
        before the jump was used for a time that only exists after it. A real local time always
        renders back to itself. Rejected (see the module docstring for why).
      * **Ambiguous** (October): the wall clock exists under both offsets, so `fold=1` yields a
        different UTC instant than `fold=0`. For every unambiguous time the two folds agree.
    """
    aware = naive.replace(tzinfo=zone)
    as_utc = aware.astimezone(timezone.utc)

    # Nonexistent: the instant we computed does not carry the wall clock we were given.
    if as_utc.astimezone(zone).replace(tzinfo=None) != naive:
        raise CsvFormatError(
            "nonexistent_local_time",
            f"Row {row}: the time {naive.strftime(TIMESTAMP_FORMAT)} does not exist in "
            f"Europe/Amsterdam — the clock jumps forward over it on that date, so no meter "
            f"could have recorded a reading then. If these timestamps are already UTC, choose "
            f"UTC instead of Amsterdam local time.",
            row=row,
        )

    # Ambiguous: both offsets are valid for this wall clock. `fold=0` (CEST) is what we keep.
    other = naive.replace(tzinfo=zone, fold=1).astimezone(timezone.utc)
    return as_utc, other != as_utc


def _parse_timestamp(raw: str, tz: str, row: int) -> tuple[np.datetime64, bool]:
    """One timestamp cell → (UTC datetime64[s], was_ambiguous). Raises on anything unparseable."""
    text = raw.strip()
    if not text:
        raise CsvFormatError(
            "empty_timestamp",
            f"Row {row}: the timestamp column is empty. Every data row needs a timestamp in "
            f"the form DD-MM-YYYY HH:MM:SS, for example 01-01-2025 00:00:00.",
            row=row,
        )
    try:
        naive = datetime.strptime(text, TIMESTAMP_FORMAT)
    except ValueError:
        raise CsvFormatError(
            "bad_timestamp",
            f"Row {row}: could not read {text!r} as a timestamp. Expected DD-MM-YYYY HH:MM:SS "
            f"on a 24-hour clock, for example 01-01-2025 00:00:00.",
            row=row,
        ) from None

    if tz == UTC_TZ:
        # Declared UTC: attach and be done. No transition, so nothing to flag (D-DST).
        aware, ambiguous = naive.replace(tzinfo=timezone.utc), False
    else:
        aware, ambiguous = _resolve_local(naive, ZoneInfo(tz), row)

    # Whole seconds throughout: the format has no sub-second field, so no precision is lost.
    return np.datetime64(int(aware.timestamp()), "s"), ambiguous


# --- file-level parse (§4.2a checks at upload) ----------------------------------------------

def parse_wide_csv(text: str, tz: str) -> WideCsv:
    """Parse a whole wide CSV, applying the declared zone. Raises `CsvFormatError`.

    Performs exactly the file-level checks §4.2a puts at upload: a header row must be present,
    there must be at least two columns (one timestamp plus one value), there must be at least one
    data row, and every timestamp must parse under `tz`. Value cells are carried through
    untouched — see the module docstring on why column checks are deferred.

    `tz` must be one of `TZ_KEYS`; anything else is a programming error in the caller (a route
    validates the submitted form value), so it is rejected here as a plain rejection rather than
    silently defaulting to one of the two.

    Rows are sorted by resolved UTC instant with a **stable** sort, so the October pair — two
    rows that legitimately share a UTC instant after fold resolution — keeps its file order.
    Sorting rather than requiring chronological input costs nothing and accepts the descending
    exports some suppliers produce.
    """
    if tz not in TZ_KEYS:
        raise CsvFormatError(
            "bad_timezone",
            f"Unknown timezone {tz!r}. Expected one of: {', '.join(TZ_KEYS)}.",
        )

    # `csv.reader` handles quoted names with embedded commas or semicolons, which supplier
    # exports do produce in header rows. Newline handling is left to `io.StringIO`'s universal
    # newlines so CRLF files (the Windows-exported common case) need no pre-processing.
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        header = []
    # A UTF-8 BOM survives decoding as U+FEFF glued to the first header cell; strip it so the
    # timestamp column name displays correctly.
    if header:
        header[0] = header[0].lstrip("﻿")

    if not header or not any(cell.strip() for cell in header):
        raise CsvFormatError(
            "missing_header",
            "The file has no header row. Row 1 must name the columns: a timestamp column "
            "followed by one column per measurement.",
        )
    # A row 1 whose first cell is itself a valid timestamp is data, not a header (§4.2a: row 1 is
    # required; harness fixture 22 requires "no header row" to be rejected at upload). Without
    # this the first reading is silently eaten as the header, its values become column names, and
    # the file parses to one row fewer than it has — wrong, and wrong quietly, which is worse than
    # any rejection. Only the timestamp column is tested: a header cell that parses as
    # `DD-MM-YYYY HH:MM:SS` is not a plausible column name, whereas a value column legitimately
    # called "0.4" is merely odd.
    if _is_timestamp(header[0]):
        raise CsvFormatError(
            "missing_header",
            f"Row 1 looks like data, not column names: its first cell "
            f"{header[0].strip()!r} is a timestamp. Row 1 must name the columns — a timestamp "
            f"column followed by one column per measurement — so add a header row.",
            row=1,
        )
    if len(header) < 2:
        raise CsvFormatError(
            "too_few_columns",
            f"The file has only {len(header)} column. Expected at least two: a timestamp "
            f"column followed by at least one value column.",
        )

    timestamp_name = header[0].strip()
    columns = _value_column_names(header)

    stamps: list[np.datetime64] = []
    ambiguous: list[bool] = []
    lines: list[int] = []
    # Accumulated positionally, one list per value column, and only zipped to names at the end.
    # Appending into a dict keyed by name would make any future duplicate-name bug corrupt data
    # silently (two appends into one list, then truncated back to length by the sort re-slice, so
    # not even `SeriesFrame.__post_init__`'s length check would fire). Position cannot collide.
    by_position: list[list[str]] = [[] for _ in columns]

    # `row_no` is what a spreadsheet shows: the header is row 1, so the first data row is 2.
    for row_no, record in enumerate(reader, start=2):
        if not record or all(not cell.strip() for cell in record):
            # A trailing or interspersed blank line is formatting, not data. Skipped silently —
            # every exporter produces a trailing newline and it is not a user error.
            continue
        if len(record) != len(header):
            # Both directions are errors, and the *long* direction matters more than it looks: a
            # file written with decimal commas splits `0,412` into two cells, so every row is one
            # cell too long. Ignoring the surplus would read that file as a column of integers —
            # plausible and wrong by a factor of a thousand. Rejecting names the mismatch instead.
            raise CsvFormatError(
                "row_length_mismatch",
                f"Row {row_no} has {len(record)} values but the header names {len(header)} "
                f"columns. Every row must carry exactly one cell per column; leave a cell empty "
                f"to mark a gap. A row with too many cells usually means a value uses a comma as "
                f"the decimal separator without being quoted, so it was split into two cells. "
                f"Either quote such values, or choose a different field separator.",
                row=row_no,
            )

        ts, amb = _parse_timestamp(record[0], tz, row_no)
        stamps.append(ts)
        ambiguous.append(amb)
        lines.append(row_no)
        for position, column_cells in enumerate(by_position):
            column_cells.append(record[position + 1])

    if not stamps:
        raise CsvFormatError(
            "no_data_rows",
            "The file has a header row but no data rows. At least one row of readings is "
            "required.",
        )

    index = np.array(stamps, dtype="datetime64[s]")
    amb_mask = np.array(ambiguous, dtype=bool)

    # Stable sort: equal instants (the October pair) keep file order. `kind="stable"` is required
    # — the default quicksort would reorder them arbitrarily.
    order = np.argsort(index, kind="stable")
    index = index[order]
    amb_mask = amb_mask[order]
    # The original file line travels with its row through the sort, so a column-level rejection
    # can still name the line the user can find in a spreadsheet (§4.2a: say *where*).
    line_numbers = tuple(lines[i] for i in order)
    cells = {
        name: [column_cells[i] for i in order]
        for name, column_cells in zip(columns, by_position)
    }

    return WideCsv(
        columns=columns,
        timestamp_name=timestamp_name,
        index=index,
        cells=cells,
        resolution_s=infer_resolution_s(index),
        tz=tz,
        ambiguous=amb_mask,
        line_numbers=line_numbers,
    )


def _is_timestamp(cell: str) -> bool:
    """True if `cell` parses as this format's timestamp — used to detect a missing header row."""
    try:
        datetime.strptime(cell.strip(), TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True


def _value_column_names(header: list[str]) -> tuple[str, ...]:
    """Header row → the value-column names, made unique and non-empty.

    Names are display-only, but they are also the **binding key**: a slot stores
    `(upload_id, column, unit)`, so two columns sharing a name would make a binding ambiguous
    about which one it meant. Real exports do produce repeated and empty headers (a trailing
    comma, or two sensors with the same friendly name), so rather than reject the file — the
    names carry no meaning worth defending — duplicates get a `" (2)"` suffix and an empty name
    becomes `"Column N"`, using the 1-based file position so the user can find it.

    The suffix is applied in a loop against the set of names **already issued**, not against a
    per-basename counter. A counter is not enough, because a generated name can collide with a
    literal one later in the same header: `A, A (2), A` would derive `"A (2)"` for column 4 by
    counting, which is the name column 3 already holds literally. That produced two identical
    keys — the precise failure this function exists to prevent — and, since the caller keys the
    cell lists by name, silently merged two columns' data into one interleaved list and dropped
    the third. Checking each candidate against `issued` and incrementing until it is free cannot
    collide, whatever the header contains.
    """
    names: list[str] = []
    issued: set[str] = set()
    for position, cell in enumerate(header[1:], start=2):
        base = cell.strip() or f"Column {position}"
        name = base
        suffix = 1
        while name in issued:
            suffix += 1
            name = f"{base} ({suffix})"
        issued.add(name)
        names.append(name)
    return tuple(names)


def summarise(wide: WideCsv) -> WideCsvSummary:
    """The upload dialog's view of a parsed file (column names, coverage, resolution).

    Separate from `parse_wide_csv` so the summary can also be rebuilt from a stored file without
    the caller knowing which fields the dialog happens to need.
    """
    first = _to_utc_datetime(wide.index[0]) if wide.rows else None
    last = _to_utc_datetime(wide.index[-1]) if wide.rows else None
    return WideCsvSummary(
        columns=wide.columns,
        timestamp_name=wide.timestamp_name,
        rows=wide.rows,
        resolution_s=wide.resolution_s,
        first_ts=first,
        last_ts=last,
        tz=wide.tz,
        ambiguous_rows=int(wide.ambiguous.sum()),
    )


def parse_and_summarise(text: str, tz: str) -> tuple[WideCsv, WideCsvSummary]:
    """Parse and summarise in one call — what the upload route wants (step 3 of the brief)."""
    wide = parse_wide_csv(text, tz)
    return wide, summarise(wide)


def _to_utc_datetime(ts64: np.datetime64) -> datetime:
    """datetime64[s] (UTC by construction here) → tz-aware UTC datetime."""
    return ts64.astype("datetime64[us]").astype(datetime).replace(tzinfo=timezone.utc)


# --- column-level parse (§4.2a checks on selection) -----------------------------------------

def parse_column_values(wide: WideCsv, column: str) -> np.ndarray:
    """One column's cells → float64 with NaN for gaps. Raises on a non-numeric cell.

    Empty and gap-token cells become NaN (open item 4 of the brief): a gap, **not** a zero. NaN
    is what the rest of the pipeline already means by "no reading" — `cumulative_to_delta` emits
    exactly this for a spacing gap (`ingest.py`) — so both ingest paths agree and every sum
    excludes the interval rather than counting it as nothing happening.

    The decimal separator is read per cell by `_decimal_normalised`: `.` or `,`, and a cell
    holding both is rejected. The **timestamp column needs no exemption and must not be given
    one**: `parse_wide_csv` sends `record[0]` to `_parse_timestamp` and stores only `record[1:]`
    in `wide.cells`, so a timestamp never reaches this function. Adding an exemption here would
    be dead code that implies a coupling that does not exist.

    Infinities are **rejected**, not treated as gaps. `float()` accepts `inf`, `-infinity` and
    anything that overflows (`1e400`), and NaN is the only non-finite value the pipeline handles:
    `reconcile._resample_sum` neutralises NaN with `np.nan_to_num(..., nan=0.0)` and leaves an
    infinity intact, so one such cell would poison every total it touches. Mapping it to a gap
    instead would be safe arithmetically but wrong as a claim — an infinity is a *present and
    corrupt* reading, not an absent one, and reporting it as a gap tells the user their export has
    a hole where it actually has broken data. Rejecting says what happened.
    """
    raw = wide.cells.get(column)
    if raw is None:
        raise CsvFormatError(
            "unknown_column",
            f"The file has no column named {column!r}. Its columns are: "
            f"{', '.join(wide.columns)}.",
        )

    out = np.empty(len(raw), dtype=np.float64)
    for i, cell in enumerate(raw):
        text = cell.strip()
        if text.casefold() in GAP_TOKENS:
            out[i] = np.nan
            continue
        # Per-cell decimal separator, AFTER the gap check (so `-`, a gap token, is never
        # reinterpreted) and BEFORE `float()`. A substitution can neither create nor remove an
        # infinity, so the `np.isinf` check below is unaffected by it.
        normalised = _decimal_normalised(text, column, wide.line_numbers[i])
        try:
            value = float(normalised)
        except ValueError:
            raise CsvFormatError(
                "non_numeric_value",
                f"Column {column!r}: {text!r} on row {wide.line_numbers[i]} is not a number. "
                f"A value may use a dot or a comma as the decimal separator — 0.412 or 0,412 — "
                f"but not both in the same value. Leave a cell empty to mark a gap.",
                row=wide.line_numbers[i],
            ) from None
        if np.isinf(value):
            raise CsvFormatError(
                "non_finite_value",
                f"Column {column!r}: {text!r} on row {wide.line_numbers[i]} is not a finite "
                f"number. Every reading must be an ordinary number; leave a cell empty to mark "
                f"a gap.",
                row=wide.line_numbers[i],
            )
        out[i] = value
    return out


def _looks_cumulative(values: np.ndarray) -> bool:
    """True if this column reads as a cumulative meter register (D-KIND, §4.2a).

    The three-part threshold is derived and justified at MONOTONIC_MIN_SAMPLES above: enough
    finite samples for the ordering to mean anything, no decrease beyond float dust, and an
    actual overall rise — the last being what keeps a flat-zero or all-constant column (both
    non-decreasing, both ordinary per-interval data) out of the register bucket.

    Gaps are skipped rather than breaking the chain: a NaN in the middle of a register does not
    make it a per-interval series, and comparing consecutive *finite* readings is the same test
    the register would pass with the gap absent.

    Read the residual-risk note at those constants before trusting this either way: monotone
    partial-day PV is flagged, and a register spanning a meter reset is not. This is a SUSPICION,
    which is why its consequence is `column_frame`'s `CSV_CUMULATIVE_COLUMN` warning rather than a
    rejection — the function name says "looks", and the caller must not read more into it.

    Public-ish despite the underscore: `app/main.py`'s upload route calls it once per value column
    so the verdict can be persisted with the `uploads` row and reach the drawer's column picker on
    a later page load. Nothing outside this module and that route uses it.
    """
    finite = values[np.isfinite(values)]
    if len(finite) < MONOTONIC_MIN_SAMPLES:
        return False
    if float(finite[-1] - finite[0]) <= MONOTONIC_MIN_RISE:
        return False
    return bool(np.all(np.diff(finite) >= -MONOTONIC_NOISE))


def column_frame(
    wide: WideCsv, column: str, series_name: str, unit: str
) -> tuple[SeriesFrame, list[dict]]:
    """One bound column → (energy `SeriesFrame`, warnings). Raises `CsvFormatError`.

    `series_name` is the slot the binding targets (a §4.1 vocabulary name); the column's own name
    is **never** used for it — §4.2a is explicit that headers are shown and not interpreted.
    `unit` is the per-binding radio value, one of `UNIT_FACTORS`.

    Runs §4.2a's two column-level checks, and they have DIFFERENT consequences:

      * the values must be numeric — a non-numeric or infinite cell REJECTS this binding
        (`parse_column_values`);
      * a column that looks like a cumulative register only WARNS (`CSV_CUMULATIVE_COLUMN`) and the
        frame is returned anyway. It used to reject; the module docstring's "Cumulative registers"
        section records why that changed and what it costs. Nothing here is differenced either way
        (D-KIND), because every value column already *is* the per-interval amount for the interval
        starting at its timestamp, which is `SeriesFrame.values`' own definition for an energy
        series — so proceeding on a genuine register reads its running total as an hourly amount,
        and the warning is the only thing that says so.

    Quality bits raised here: `GAP_FILLED` where the cell was empty, and `DST_AMBIGUOUS` on the
    rows the October fold resolution touched. There is deliberately no quality bit for the
    cumulative suspicion: quality flags are per-SAMPLE facts and this is a claim about the whole
    column, so it would have to be set on every row to mean anything and would then be indistinguishable
    from a per-sample problem in §7.3's box. Warnings mirror `ingest.energy_frame`'s `list[dict]`
    shape so the existing plumbing carries them unchanged.
    """
    if unit not in UNIT_FACTORS:
        raise CsvFormatError(
            "bad_unit",
            f"Unknown unit {unit!r}. Expected one of: {', '.join(UNIT_FACTORS)}.",
        )

    values = parse_column_values(wide, column)

    # Tested BEFORE the unit conversion, so the verdict cannot depend on the unit the binding
    # happens to declare. Both thresholds are unit-free by design (see MONOTONIC_NOISE), so the
    # answer would be the same either way at any realistic magnitude — but "the same column reads
    # as a register in kWh and not in Wh" is not a property worth leaving reachable.
    cumulative = _looks_cumulative(values)

    values = values * UNIT_FACTORS[unit]

    quality = np.zeros(len(values), dtype=QUALITY_DTYPE)
    gaps = ~np.isfinite(values)
    quality[gaps] |= QUALITY_DTYPE(QualityFlags.GAP_FILLED)
    quality[wide.ambiguous] |= QUALITY_DTYPE(QualityFlags.DST_AMBIGUOUS)

    warnings: list[dict] = []
    if cumulative:
        # First in the list because it is the one warning that says the NUMBERS may be wrong rather
        # than incomplete. Same `{"code", "column", ...}` shape as the two below so the existing
        # plumbing carries it; no `count`, because it is a claim about the column as a whole and any
        # number here would invite being read as "this many suspect rows".
        warnings.append({"code": "CSV_CUMULATIVE_COLUMN", "column": column})
    gap_count = int(gaps.sum())
    if gap_count:
        warnings.append({"code": "CSV_GAP_CELLS", "column": column, "count": gap_count})
    amb_count = int(wide.ambiguous.sum())
    if amb_count:
        # Named by day, which is what §7.3's data-quality box reports. The dates come off the
        # resolved UTC index; at the October transition the Amsterdam day and the UTC day
        # coincide (the transition is at 03:00 local, 01:00 UTC), so no local rendering is needed.
        days = sorted({str(ts)[:10] for ts in wide.index[wide.ambiguous]})
        warnings.append(
            {
                "code": "CSV_DST_AMBIGUOUS_HOUR",
                "column": column,
                "count": amb_count,
                "days": days,
            }
        )

    frame = SeriesFrame(
        name=series_name,
        kind="energy",
        resolution_s=wide.resolution_s,
        index=wide.index,
        values=values,
        quality=quality,
    )
    return frame, warnings
