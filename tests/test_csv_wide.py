"""Unit tests for the wide-CSV parser (specs §4.2a, §7.3 checks 1 and 2).

Text in, frames out — no I/O, no data dir, no routes. These pin the whole Step 2 matrix from
changelog/20260805-csv-import-implementation-brief.md: both declarable zones, the October
repeated hour, a March nonexistent time, Wh and kWh, empty cells, a cumulative column, a flat
column, irregular spacing, a malformed header, a bad timestamp, and a non-numeric value.

    uv run pytest tests/test_csv_wide.py
"""

from datetime import datetime, timezone

import numpy as np
import pytest

from app.domain import csv_wide
from app.domain.csv_wide import AMSTERDAM_TZ, UTC_TZ, CsvFormatError
from app.domain.frames import QualityFlags


def _csv(header, *rows):
    """Build a CSV body from a header tuple and (timestamp, *values) row tuples."""
    lines = [",".join(header)]
    lines += [",".join(str(cell) for cell in row) for row in rows]
    return "\n".join(lines) + "\n"


def _hourly(day, hours, values, *, header=("Tijdstip", "Verbruik")):
    """An hourly file over `day` (DD-MM-YYYY) at the given hours with the given values."""
    rows = [(f"{day} {h:02d}:00:00", v) for h, v in zip(hours, values)]
    return _csv(header, *rows)


SIMPLE = _csv(
    ("Tijdstip", "Verbruik_T1", "Verbruik_T2", "Zon"),
    ("01-01-2025 00:00:00", 0.412, 0.000, 0.0),
    ("01-01-2025 01:00:00", 0.388, 0.000, 0.0),
    ("01-01-2025 02:00:00", 0.401, 0.000, 0.0),
)


# --- header and shape (file-level checks, §4.2a "Validation and failure") --------------------

def test_header_names_are_read_in_order_and_not_interpreted():
    wide = csv_wide.parse_wide_csv(SIMPLE, UTC_TZ)
    assert wide.timestamp_name == "Tijdstip"
    assert wide.columns == ("Verbruik_T1", "Verbruik_T2", "Zon")
    assert wide.rows == 3


def test_empty_file_is_rejected_as_missing_header():
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv("", UTC_TZ)
    assert exc.value.code == "missing_header"


def test_single_column_file_is_rejected():
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv("Tijdstip\n01-01-2025 00:00:00\n", UTC_TZ)
    assert exc.value.code == "too_few_columns"
    # §4.2a: the message must say what was expected and what was found.
    assert "at least two" in str(exc.value)


def test_header_only_file_is_rejected_for_having_no_data_rows():
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv("Tijdstip,Verbruik\n", UTC_TZ)
    assert exc.value.code == "no_data_rows"


def test_short_data_row_is_rejected_naming_the_row():
    text = "Tijdstip,A,B\n01-01-2025 00:00:00,1.0\n"
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv(text, UTC_TZ)
    assert exc.value.code == "row_length_mismatch"
    assert exc.value.row == 2


def test_a_row_with_too_many_cells_is_rejected_not_silently_truncated():
    # Unquoted decimal commas produce exactly this shape; reading it would be wrong by 1000x.
    text = "Tijdstip,A\n01-01-2025 00:00:00,0,412\n"
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv(text, UTC_TZ)
    assert exc.value.code == "row_length_mismatch"
    assert "decimal separator" in str(exc.value)


def test_trailing_blank_lines_are_not_data_rows():
    wide = csv_wide.parse_wide_csv(SIMPLE + "\n\n", UTC_TZ)
    assert wide.rows == 3


def test_bom_is_stripped_from_the_timestamp_column_name():
    wide = csv_wide.parse_wide_csv("﻿" + SIMPLE, UTC_TZ)
    assert wide.timestamp_name == "Tijdstip"


def test_duplicate_and_empty_column_names_are_made_unique():
    # Real exports do this; names are display-only but are also the binding key, so they must
    # be distinguishable.
    text = _csv(("Tijdstip", "A", "A", ""), ("01-01-2025 00:00:00", 1.0, 2.0, 3.0))
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    assert wide.columns == ("A", "A (2)", "Column 4")


def test_a_literal_suffix_shaped_name_does_not_collide_with_a_generated_one():
    # The regression that matters: column 3 already *holds* the name the counter would generate
    # for column 4. Naive counting produced two identical keys, merged their cells into one
    # interleaved list and lost a column's data outright — silently, because the sort re-slice
    # truncated the overfilled list back to the right length.
    text = _csv(
        ("Tijdstip", "A", "A (2)", "A"),
        ("01-01-2025 00:00:00", 1, 2, 3),
        ("01-01-2025 01:00:00", 4, 5, 6),
        ("01-01-2025 02:00:00", 7, 8, 9),
    )
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    assert len(set(wide.columns)) == len(wide.columns) == 3
    assert wide.columns == ("A", "A (2)", "A (3)")
    # Every column keeps its own cells, in row order, with nothing interleaved or dropped.
    assert csv_wide.parse_column_values(wide, "A").tolist() == [1.0, 4.0, 7.0]
    assert csv_wide.parse_column_values(wide, "A (2)").tolist() == [2.0, 5.0, 8.0]
    assert csv_wide.parse_column_values(wide, "A (3)").tolist() == [3.0, 6.0, 9.0]
    for name in wide.columns:
        assert len(wide.cells[name]) == wide.rows


def test_three_identical_column_names_all_stay_distinct():
    text = _csv(("Tijdstip", "A", "A", "A"), ("01-01-2025 00:00:00", 1, 2, 3))
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    assert wide.columns == ("A", "A (2)", "A (3)")


def test_a_headerless_file_is_rejected_rather_than_eating_its_first_row():
    # Harness fixture 22 requires "no header row" to fail at upload. Previously this parsed with
    # timestamp_name='01-01-2025 00:00:00', columns=('0.4',) and one row instead of two.
    text = "01-01-2025 00:00:00,0.4\n01-01-2025 01:00:00,0.5\n"
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv(text, UTC_TZ)
    assert exc.value.code == "missing_header"
    assert exc.value.row == 1


def test_a_header_whose_first_cell_is_not_a_timestamp_is_still_a_header():
    # The detection must not be over-eager: an odd column name is not a missing header.
    text = _csv(("Tijdstip", "0.4"), ("01-01-2025 00:00:00", 1.0))
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    assert wide.columns == ("0.4",)


def test_crlf_line_endings_are_handled():
    # Windows-exported files are the common case; no pre-processing should be needed.
    text = SIMPLE.replace("\n", "\r\n")
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    assert wide.rows == 3
    assert wide.columns == ("Verbruik_T1", "Verbruik_T2", "Zon")
    assert csv_wide.parse_column_values(wide, "Verbruik_T1").tolist() == [0.412, 0.388, 0.401]


def test_unknown_timezone_is_rejected():
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv(SIMPLE, "Europe/Berlin")
    assert exc.value.code == "bad_timezone"


# --- timestamps (§4.2a; D-TZ) ----------------------------------------------------------------

def test_utc_timestamps_are_taken_as_given():
    wide = csv_wide.parse_wide_csv(SIMPLE, UTC_TZ)
    assert str(wide.index[0]) == "2025-01-01T00:00:00"
    assert not wide.ambiguous.any()


def test_amsterdam_winter_timestamps_shift_by_one_hour():
    wide = csv_wide.parse_wide_csv(SIMPLE, AMSTERDAM_TZ)
    # January is CET (UTC+1), so 00:00 local is 23:00 UTC the previous day.
    assert str(wide.index[0]) == "2024-12-31T23:00:00"
    assert not wide.ambiguous.any()


def test_amsterdam_summer_timestamps_shift_by_two_hours():
    text = _hourly("01-07-2025", [12], [1.0])
    wide = csv_wide.parse_wide_csv(text, AMSTERDAM_TZ)
    assert str(wide.index[0]) == "2025-07-01T10:00:00"


def test_same_file_in_the_two_zones_differs_by_the_offset():
    # Harness fixture 22a: the declared zone is applied once, at upload.
    utc = csv_wide.parse_wide_csv(SIMPLE, UTC_TZ)
    ams = csv_wide.parse_wide_csv(SIMPLE, AMSTERDAM_TZ)
    delta = (utc.index - ams.index).astype("timedelta64[s]").astype(int)
    assert list(delta) == [3600, 3600, 3600]


def test_bad_timestamp_is_rejected_naming_the_row_and_its_content():
    text = _hourly("01-01-2025", [0], [1.0]).replace(
        "01-01-2025 00:00:00", "2025-01-01T00:00:00"
    )
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv(text, UTC_TZ)
    assert exc.value.code == "bad_timestamp"
    assert exc.value.row == 2
    assert "2025-01-01T00:00:00" in str(exc.value)
    assert "DD-MM-YYYY" in str(exc.value)


def test_24_hour_clock_is_enforced():
    text = _csv(("Tijdstip", "A"), ("01-01-2025 25:00:00", 1.0))
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv(text, UTC_TZ)
    assert exc.value.code == "bad_timestamp"


def test_empty_timestamp_cell_is_rejected():
    text = "Tijdstip,A\n,1.0\n"
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv(text, UTC_TZ)
    assert exc.value.code == "empty_timestamp"


def test_rows_are_sorted_by_instant():
    text = _csv(
        ("Tijdstip", "A"),
        ("01-01-2025 02:00:00", 3.0),
        ("01-01-2025 00:00:00", 1.0),
        ("01-01-2025 01:00:00", 2.0),
    )
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    assert str(wide.index[0]) == "2025-01-01T00:00:00"
    assert csv_wide.parse_column_values(wide, "A").tolist() == [1.0, 2.0, 3.0]


# --- the October repeated hour (D-DST) -------------------------------------------------------

# 26-10-2025 is the Dutch autumn transition: 03:00 CEST becomes 02:00 CET, so 02:00–02:59 local
# occurs twice. A chronological export writes the pair as two identical wall clocks.
OCTOBER = _csv(
    ("Tijdstip", "A"),
    ("26-10-2025 01:00:00", 1.0),
    ("26-10-2025 02:00:00", 2.0),   # first occurrence, CEST (UTC+2) → 00:00 UTC
    ("26-10-2025 02:00:00", 3.0),   # second occurrence, CET (UTC+1) → resolved to CEST too
    ("26-10-2025 03:00:00", 4.0),
)


def test_october_repeated_hour_resolves_to_the_first_cest_occurrence():
    wide = csv_wide.parse_wide_csv(OCTOBER, AMSTERDAM_TZ)
    stamps = [str(ts) for ts in wide.index]
    # 01:00 CEST → 23:00 UTC; both 02:00 rows → 00:00 UTC (the CEST reading); 03:00 CET → 02:00.
    assert stamps == [
        "2025-10-25T23:00:00",
        "2025-10-26T00:00:00",
        "2025-10-26T00:00:00",
        "2025-10-26T02:00:00",
    ]


def test_october_ambiguous_rows_are_flagged_and_the_others_are_not():
    wide = csv_wide.parse_wide_csv(OCTOBER, AMSTERDAM_TZ)
    assert wide.ambiguous.tolist() == [False, True, True, False]

    frame, warnings = csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    flagged = [bool(int(q) & QualityFlags.DST_AMBIGUOUS) for q in frame.quality]
    assert flagged == [False, True, True, False]

    dst = [w for w in warnings if w["code"] == "CSV_DST_AMBIGUOUS_HOUR"]
    assert len(dst) == 1
    assert dst[0]["count"] == 2
    # §7.3's box names the affected day.
    assert dst[0]["days"] == ["2025-10-26"]


def test_stable_sort_keeps_the_october_pair_in_file_order():
    wide = csv_wide.parse_wide_csv(OCTOBER, AMSTERDAM_TZ)
    assert csv_wide.parse_column_values(wide, "A").tolist() == [1.0, 2.0, 3.0, 4.0]


def test_a_full_day_october_file_doubles_one_utc_hour_and_leaves_the_next_empty():
    # DOCUMENTED CONSEQUENCE of D-DST's fold rule, pinned so it is not rediscovered as a bug.
    # 25 local hours collapse onto 24 UTC instants: 00:00 UTC appears twice and 01:00 UTC is
    # absent. reconcile._resample_sum uses np.add.at, so the window total is conserved, but that
    # hour reads double and 01:00 reads zero. Fixing this means changing the spec, not the parser.
    hours = [0, 1, 2, 2] + list(range(3, 24))
    values = [1.0] * len(hours)
    rows = [(f"26-10-2025 {h:02d}:00:00", v) for h, v in zip(hours, values)]
    wide = csv_wide.parse_wide_csv(_csv(("Tijdstip", "A"), *rows), AMSTERDAM_TZ)

    assert wide.rows == 25
    stamps = [str(t) for t in wide.index]
    assert stamps.count("2025-10-26T00:00:00") == 2
    assert "2025-10-26T01:00:00" not in stamps
    # The modal spacing is still hourly despite the zero-length step between the pair.
    assert wide.resolution_s == 3600

    frame, warnings = csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    flagged = int(np.count_nonzero(frame.quality & QualityFlags.DST_AMBIGUOUS))
    # Only the two 02:00 rows are flagged; the interval that ends up reading zero does not exist
    # to be flagged, so the quality box under-reports the damage by half.
    assert flagged == 2
    dst = [w for w in warnings if w["code"] == "CSV_DST_AMBIGUOUS_HOUR"][0]
    assert dst["count"] == 2


def test_a_15_minute_october_file_flags_all_four_repeated_quarters():
    quarters = [0, 15, 30, 45]
    rows = [("26-10-2025 01:45:00", 0.1)]
    rows += [(f"26-10-2025 02:{q:02d}:00", 0.2) for q in quarters]   # first pass, CEST
    rows += [(f"26-10-2025 02:{q:02d}:00", 0.3) for q in quarters]   # second pass, CET
    rows += [("26-10-2025 03:00:00", 0.4)]
    wide = csv_wide.parse_wide_csv(_csv(("Tijdstip", "A"), *rows), AMSTERDAM_TZ)

    assert wide.resolution_s == 900
    assert int(wide.ambiguous.sum()) == 8
    frame, warnings = csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    assert int(np.count_nonzero(frame.quality & QualityFlags.DST_AMBIGUOUS)) == 8
    dst = [w for w in warnings if w["code"] == "CSV_DST_AMBIGUOUS_HOUR"][0]
    assert dst["count"] == 8 and dst["days"] == ["2025-10-26"]


def test_utc_file_over_the_same_date_raises_no_ambiguity_flag():
    # Harness fixture 22a: a UTC-declared file spanning the transition date is unambiguous.
    wide = csv_wide.parse_wide_csv(OCTOBER, UTC_TZ)
    assert not wide.ambiguous.any()
    _, warnings = csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    assert [w["code"] for w in warnings] == []


# --- the March nonexistent hour (open item 1: reject) ---------------------------------------

def test_nonexistent_march_local_time_is_rejected_under_amsterdam():
    # 30-03-2025: 02:00 CET jumps straight to 03:00 CEST, so 02:30 local never happened.
    text = _csv(
        ("Tijdstip", "A"),
        ("30-03-2025 01:00:00", 1.0),
        ("30-03-2025 02:30:00", 2.0),
    )
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv(text, AMSTERDAM_TZ)
    assert exc.value.code == "nonexistent_local_time"
    assert exc.value.row == 3
    # The message must offer the likely fix: the file is probably really UTC.
    assert "UTC" in str(exc.value)


@pytest.mark.parametrize("clock", ["02:00:00", "02:30:00", "02:59:59"])
def test_every_instant_in_the_march_gap_is_rejected(clock):
    # The whole hour is nonexistent, boundaries included: 02:00:00 is the first instant that does
    # not happen and 02:59:59 the last.
    text = _csv(("Tijdstip", "A"), (f"30-03-2025 {clock}", 1.0))
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.parse_wide_csv(text, AMSTERDAM_TZ)
    assert exc.value.code == "nonexistent_local_time"


@pytest.mark.parametrize(
    "clock,expected",
    [("01:59:59", "2025-03-30T00:59:59"), ("03:00:00", "2025-03-30T01:00:00")],
)
def test_the_instants_bracketing_the_march_gap_are_accepted(clock, expected):
    # One second either side of the gap must still parse — the check must not overshoot.
    text = _csv(("Tijdstip", "A"), (f"30-03-2025 {clock}", 1.0))
    wide = csv_wide.parse_wide_csv(text, AMSTERDAM_TZ)
    assert str(wide.index[0]) == expected
    assert not wide.ambiguous.any()


def test_the_same_march_file_is_accepted_when_declared_utc():
    text = _csv(("Tijdstip", "A"), ("30-03-2025 02:30:00", 2.0))
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    assert str(wide.index[0]) == "2025-03-30T02:30:00"


def test_march_transition_hours_either_side_are_fine():
    text = _csv(
        ("Tijdstip", "A"),
        ("30-03-2025 01:00:00", 1.0),  # CET  → 00:00 UTC
        ("30-03-2025 03:00:00", 2.0),  # CEST → 01:00 UTC
    )
    wide = csv_wide.parse_wide_csv(text, AMSTERDAM_TZ)
    assert [str(t) for t in wide.index] == ["2025-03-30T00:00:00", "2025-03-30T01:00:00"]
    assert not wide.ambiguous.any()


# --- resolution (reuses infer_resolution_s) --------------------------------------------------

def test_hourly_resolution_is_inferred():
    assert csv_wide.parse_wide_csv(SIMPLE, UTC_TZ).resolution_s == 3600


def test_quarter_hourly_resolution_is_inferred():
    text = _csv(
        ("Tijdstip", "A"),
        ("01-01-2025 00:00:00", 1.0),
        ("01-01-2025 00:15:00", 1.0),
        ("01-01-2025 00:30:00", 1.0),
    )
    assert csv_wide.parse_wide_csv(text, UTC_TZ).resolution_s == 900


def test_irregular_spacing_yields_no_resolution():
    # §4.2a: an irregular file is accepted with resolution_s = None, not rejected.
    text = _csv(
        ("Tijdstip", "A"),
        ("01-01-2025 00:00:00", 1.0),
        ("01-01-2025 00:07:00", 1.0),
        ("01-01-2025 00:31:00", 1.0),
    )
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    assert wide.resolution_s is None
    frame, _ = csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    assert frame.resolution_s is None


# --- values, units and gaps ------------------------------------------------------------------

def test_kwh_is_the_identity_and_the_frame_is_per_interval_energy():
    wide = csv_wide.parse_wide_csv(SIMPLE, UTC_TZ)
    frame, warnings = csv_wide.column_frame(wide, "Verbruik_T1", "grid_import_t1", "kWh")
    assert frame.name == "grid_import_t1"
    assert frame.kind == "energy"
    assert frame.resolution_s == 3600
    # No differencing (D-KIND): the column's values ARE the frame's values.
    assert np.allclose(frame.values, [0.412, 0.388, 0.401])
    assert len(frame.index) == 3
    assert warnings == []


def test_wh_is_divided_by_a_thousand():
    text = _csv(
        ("Tijdstip", "A"),
        ("01-01-2025 00:00:00", 412.0),
        ("01-01-2025 01:00:00", 388.0),
    )
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    frame, _ = csv_wide.column_frame(wide, "A", "grid_import_t1", "Wh")
    assert np.allclose(frame.values, [0.412, 0.388])


def test_unknown_unit_is_rejected():
    wide = csv_wide.parse_wide_csv(SIMPLE, UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "Verbruik_T1", "grid_import_t1", "MWh")
    assert exc.value.code == "bad_unit"


def test_empty_cell_is_a_gap_not_a_zero():
    # Open item 4: NaN + GAP_FILLED, the same convention cumulative_to_delta uses.
    text = "Tijdstip,A\n01-01-2025 00:00:00,0.4\n01-01-2025 01:00:00,\n01-01-2025 02:00:00,0.5\n"
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    frame, warnings = csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    assert np.isnan(frame.values[1])
    assert not np.isnan(frame.values[0]) and not np.isnan(frame.values[2])
    assert int(frame.quality[1]) & QualityFlags.GAP_FILLED
    assert int(frame.quality[0]) == 0
    # A gap must not be summed as a zero: nansum skips it, plain sum would poison the total.
    assert np.nansum(frame.values) == pytest.approx(0.9)
    assert [w["code"] for w in warnings] == ["CSV_GAP_CELLS"]
    assert warnings[0]["count"] == 1


@pytest.mark.parametrize("token", ["", " ", "NaN", "nan", "N/A", "null", "-"])
def test_gap_spellings_all_read_as_gaps(token):
    text = f"Tijdstip,A\n01-01-2025 00:00:00,0.4\n01-01-2025 01:00:00,{token}\n"
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    assert np.isnan(csv_wide.parse_column_values(wide, "A")[1])


@pytest.mark.parametrize("token", ["inf", "-inf", "Infinity", "1e400"])
def test_infinities_are_rejected_not_treated_as_gaps(token):
    # An infinity is a present, corrupt reading — not an absent one. It must not reach the frame:
    # reconcile._resample_sum neutralises NaN but not inf, so it would poison every total while
    # a GAP_FILLED flag claimed the interval was excluded. `1e400` overflows to inf via float().
    text = f"Tijdstip,A\n01-01-2025 00:00:00,0.4\n01-01-2025 01:00:00,{token}\n"
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    assert exc.value.code == "non_finite_value"
    assert exc.value.row == 3


def test_an_all_nan_column_is_all_gaps_and_sums_to_zero():
    text = "Tijdstip,A\n01-01-2025 00:00:00,\n01-01-2025 01:00:00,\n01-01-2025 02:00:00,\n"
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    frame, warnings = csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    assert np.isnan(frame.values).all()
    assert all(int(q) & QualityFlags.GAP_FILLED for q in frame.quality)
    assert np.nansum(frame.values) == 0.0
    assert warnings[0]["code"] == "CSV_GAP_CELLS" and warnings[0]["count"] == 3
    # All-NaN has no finite samples, so the register check cannot fire on it.


def test_negative_values_are_accepted():
    # A signed series (power_grid, or a net meter column) legitimately goes negative, and a
    # negative value is also what proves a column is not a register.
    text = _csv(
        ("Tijdstip", "Net"),
        ("01-01-2025 00:00:00", -0.4),
        ("01-01-2025 01:00:00", 0.9),
        ("01-01-2025 02:00:00", -1.25),
    )
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    frame, warnings = csv_wide.column_frame(wide, "Net", "power_grid", "kWh")
    assert np.allclose(frame.values, [-0.4, 0.9, -1.25])
    assert warnings == []


def test_non_numeric_value_is_rejected_naming_the_column_and_row():
    text = _csv(
        ("Tijdstip", "A"),
        ("01-01-2025 00:00:00", 0.4),
        ("01-01-2025 01:00:00", "kaputt"),
    )
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    assert exc.value.code == "non_numeric_value"
    assert "'A'" in str(exc.value) and "kaputt" in str(exc.value) and "row 3" in str(exc.value)
    assert exc.value.row == 3


def test_non_numeric_row_number_survives_sorting_and_is_the_original_line():
    # §4.2a requires naming *where*. The bad cell is on file line 3; after sorting it lands last,
    # so a position-in-sorted-data number would say "row 4" and point at the wrong line — and the
    # route needs `.row` populated to report anything at all.
    text = _csv(
        ("Tijdstip", "A"),
        ("01-01-2025 02:00:00", 0.4),
        ("01-01-2025 00:00:00", "bad"),
        ("01-01-2025 01:00:00", 0.5),
    )
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    assert exc.value.row == 3
    assert "row 3" in str(exc.value)


def test_decimal_comma_is_rejected_with_the_dot_rule_named():
    # Quoted, because an unquoted decimal comma is not even one cell.
    text = 'Tijdstip,A\n01-01-2025 00:00:00,"0,412"\n'
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "A", "grid_import_t1", "kWh")
    assert exc.value.code == "non_numeric_value"
    assert "decimal separator" in str(exc.value)


def test_unknown_column_is_rejected_listing_the_available_ones():
    wide = csv_wide.parse_wide_csv(SIMPLE, UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "Nope", "grid_import_t1", "kWh")
    assert exc.value.code == "unknown_column"
    assert "Verbruik_T1" in str(exc.value)


def test_a_bad_column_does_not_invalidate_a_good_one_in_the_same_file():
    # §4.2a: column-level failures reject only that binding.
    text = _csv(
        ("Tijdstip", "Good", "Bad"),
        ("01-01-2025 00:00:00", 0.4, "x"),
        ("01-01-2025 01:00:00", 0.5, "y"),
    )
    wide = csv_wide.parse_wide_csv(text, UTC_TZ)
    frame, _ = csv_wide.column_frame(wide, "Good", "grid_import_t1", "kWh")
    assert np.allclose(frame.values, [0.4, 0.5])
    with pytest.raises(CsvFormatError):
        csv_wide.column_frame(wide, "Bad", "grid_import_t2", "kWh")


# --- cumulative-register rejection (D-KIND; open item 2's threshold) -------------------------

_HOURS = list(range(24))


def test_a_rising_register_column_is_rejected():
    values = [14200.0 + 0.5 * i for i in range(24)]
    wide = csv_wide.parse_wide_csv(_hourly("01-01-2025", _HOURS, values), UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "Verbruik", "grid_import_t1", "kWh")
    assert exc.value.code == "cumulative_column"
    assert "per-interval" in str(exc.value)


def test_a_register_with_a_gap_in_the_middle_is_still_rejected():
    # A NaN must not break the monotonic chain — finite readings are compared to each other.
    values = [str(14200.0 + 0.5 * i) for i in range(24)]
    values[10] = ""
    wide = csv_wide.parse_wide_csv(_hourly("01-01-2025", _HOURS, values), UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "Verbruik", "grid_import_t1", "kWh")
    assert exc.value.code == "cumulative_column"


def test_a_flat_zero_column_is_ordinary_data_not_a_register():
    # An unused register, or solar over a window with no daylight. Non-decreasing but no rise.
    wide = csv_wide.parse_wide_csv(_hourly("01-01-2025", _HOURS, [0.0] * 24), UTC_TZ)
    frame, _ = csv_wide.column_frame(wide, "Verbruik", "solar_production", "kWh")
    assert np.allclose(frame.values, np.zeros(24))


def test_an_all_constant_column_is_ordinary_data_not_a_register():
    wide = csv_wide.parse_wide_csv(_hourly("01-01-2025", _HOURS, [0.25] * 24), UTC_TZ)
    frame, _ = csv_wide.column_frame(wide, "Verbruik", "grid_import_t1", "kWh")
    assert np.allclose(frame.values, np.full(24, 0.25))


def test_an_11_sample_ascending_column_is_not_judged_a_register():
    # Below the 12-sample threshold, "never decreases" carries no information. The literal 12 is
    # written out on purpose: reading MONOTONIC_MIN_SAMPLES here would make the test pass at any
    # threshold value and so pin nothing.
    values = [0.1 * (i + 1) for i in range(11)]
    wide = csv_wide.parse_wide_csv(_hourly("01-01-2025", list(range(11)), values), UTC_TZ)
    frame, _ = csv_wide.column_frame(wide, "Verbruik", "grid_import_t1", "kWh")
    assert len(frame.values) == 11


def test_at_12_samples_an_ascending_column_is_a_register():
    values = [0.1 * (i + 1) for i in range(12)]
    wide = csv_wide.parse_wide_csv(_hourly("01-01-2025", list(range(12)), values), UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "Verbruik", "grid_import_t1", "kWh")
    assert exc.value.code == "cumulative_column"


def test_monotone_partial_day_pv_is_rejected_a_known_false_positive():
    # DOCUMENTED RESIDUAL RISK, pinned so a change of behaviour is deliberate rather than
    # accidental: 15-minute PV from dawn to solar noon rises monotonically, is perfectly ordinary
    # per-interval data, and is refused. See the note at MONOTONIC_MIN_SAMPLES in csv_wide.py.
    values = [round(0.01 * i * i, 4) for i in range(28)]
    rows = [(f"01-07-2025 {6 + i // 4:02d}:{(i % 4) * 15:02d}:00", v)
            for i, v in enumerate(values)]
    wide = csv_wide.parse_wide_csv(_csv(("Tijdstip", "Zon"), *rows), UTC_TZ)
    with pytest.raises(CsvFormatError) as exc:
        csv_wide.column_frame(wide, "Zon", "solar_production", "kWh")
    assert exc.value.code == "cumulative_column"


def test_a_full_day_of_pv_is_accepted_because_the_afternoon_declines():
    # The counterpart to the test above: the same data over a full day passes. What differs is the
    # window, not the nature of the data — which is exactly why the heuristic is weak.
    rise = [round(0.01 * i * i, 4) for i in range(12)]
    values = rise + rise[::-1]
    wide = csv_wide.parse_wide_csv(_hourly("01-07-2025", _HOURS, values), UTC_TZ)
    frame, _ = csv_wide.column_frame(wide, "Verbruik", "solar_production", "kWh")
    assert len(frame.values) == 24


def test_a_register_spanning_a_reset_is_accepted_a_known_false_negative():
    # DOCUMENTED RESIDUAL RISK in the other direction: the drop at the reset breaks monotonicity,
    # so a genuine cumulative register slips through and would produce nonsense. This path cannot
    # detect it, having decided not to difference anything (D-KIND).
    values = [14200.0 + 0.5 * i for i in range(12)] + [0.5 * i for i in range(12)]
    wide = csv_wide.parse_wide_csv(_hourly("01-01-2025", _HOURS, values), UTC_TZ)
    frame, _ = csv_wide.column_frame(wide, "Verbruik", "grid_import_t1", "kWh")
    assert len(frame.values) == 24


def test_one_genuine_decrease_makes_a_column_per_interval_data():
    # 0.005 kWh is float noise to the register logic in ingest.py, but decisive evidence here.
    values = [14200.0 + 0.5 * i for i in range(24)]
    values[12] = values[11] - 0.005
    wide = csv_wide.parse_wide_csv(_hourly("01-01-2025", _HOURS, values), UTC_TZ)
    frame, _ = csv_wide.column_frame(wide, "Verbruik", "grid_import_t1", "kWh")
    assert len(frame.values) == 24


def test_a_realistic_load_profile_is_accepted():
    profile = [0.31, 0.28, 0.26, 0.25, 0.27, 0.44, 0.71, 0.62, 0.48, 0.39, 0.35, 0.33,
               0.41, 0.38, 0.36, 0.42, 0.68, 0.95, 1.12, 0.87, 0.64, 0.52, 0.41, 0.35]
    wide = csv_wide.parse_wide_csv(_hourly("01-01-2025", _HOURS, profile), UTC_TZ)
    frame, warnings = csv_wide.column_frame(wide, "Verbruik", "grid_import_t1", "kWh")
    assert np.allclose(frame.values, profile)
    assert warnings == []


# --- summary (what the upload dialog shows) --------------------------------------------------

def test_summary_reports_columns_coverage_and_resolution():
    wide, summary = csv_wide.parse_and_summarise(SIMPLE, UTC_TZ)
    assert summary.columns == ("Verbruik_T1", "Verbruik_T2", "Zon")
    assert summary.timestamp_name == "Tijdstip"
    assert summary.rows == 3
    assert summary.resolution_s == 3600
    assert summary.first_ts == datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert summary.last_ts == datetime(2025, 1, 1, 2, 0, tzinfo=timezone.utc)
    assert summary.tz == UTC_TZ
    assert summary.ambiguous_rows == 0
    assert wide.rows == summary.rows


def test_summary_counts_the_ambiguous_rows():
    _, summary = csv_wide.parse_and_summarise(OCTOBER, AMSTERDAM_TZ)
    assert summary.ambiguous_rows == 2


def test_summary_timestamps_are_tz_aware_utc():
    _, summary = csv_wide.parse_and_summarise(SIMPLE, AMSTERDAM_TZ)
    assert summary.first_ts.tzinfo is timezone.utc
    assert summary.first_ts == datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc)


# --- one file, many slots (§4.2a; harness fixture 22) ---------------------------------------

def test_two_slots_can_bind_two_columns_of_one_parsed_file():
    wide = csv_wide.parse_wide_csv(SIMPLE, UTC_TZ)
    imp, _ = csv_wide.column_frame(wide, "Verbruik_T1", "grid_import_t1", "kWh")
    sun, _ = csv_wide.column_frame(wide, "Zon", "solar_production", "kWh")
    assert imp.name == "grid_import_t1" and sun.name == "solar_production"
    assert np.array_equal(imp.index, sun.index)
    assert not np.allclose(imp.values, sun.values)
