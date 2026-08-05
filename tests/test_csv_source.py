"""Unit tests for the uploaded-CSV data source (app/sources/csv_source.py, §4.2a, §5.1).

Step 4 of the CSV-import work (changelog/20260805-csv-import-step4-source.md): the adapter between
the uploads store (step 1) and the pure parser (step 2). The parser has its own full matrix in
tests/test_csv_wide.py and the store in tests/test_uploads.py, so this module tests only what the
adapter adds:

  * the registry facts — CSV appears for every energy slot and for no price slot (D-PRICE), and is
    reachable by its descriptor key;
  * the descriptor's stable shape (`csv_upload`, `backend_load`);
  * **windowing**, which is the one thing only this layer does. `column_frame` returns a frame
    covering the whole file, so every case gets its own test: a window inside the coverage, one
    overlapping each end, one wholly before, one wholly after, the exact bounds (half-open at the
    end), and a window whose slice is too short for a modal resolution;
  * unit conversion (Wh ÷ 1000) surviving the slice;
  * the two §7.3 warnings recounted against the WINDOW, not the file — a gap outside the window
    does not warn, and the ambiguous-hour day list names only days inside it;
  * the error paths: no binding, no workspace, unknown upload, a row whose file is gone, an unknown
    column, a cumulative register (D-KIND), a bad unit, and asking for a price slot.

The data dir is a pytest tmp_path via BATTERY_SIM_DATA_DIR, so nothing touches ./data. No network.

    uv run pytest tests/test_csv_source.py
"""

from datetime import datetime, timezone

import numpy as np
import pytest

from app.domain import csv_wide
from app.domain.frames import QUALITY_DTYPE, QualityFlags
from app.domain.series_vocab import SERIES_SLOTS, SLOT_BY_NAME
from app.sources import get_source, sources_for
from app.sources.csv_source import (
    CsvBinding,
    CsvBindingError,
    CsvSource,
    slice_to_window,
)

UTC = timezone.utc
SLOT = SLOT_BY_NAME["grid_import_t1"]


def _hourly_csv(n: int = 6, *, first_day: int = 1, column: str = "Verbruik") -> str:
    """`n` hourly rows from 01-01-2025 00:00, values 0.0, 0.1, 0.2, … in one value column."""
    lines = [f"Tijdstip,{column}"]
    for i in range(n):
        lines.append(f"{first_day:02d}-01-2025 {i:02d}:00:00,{i / 10:.1f}")
    return "\n".join(lines) + "\n"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """The uploads store bound to a throwaway data dir."""
    monkeypatch.setenv("BATTERY_SIM_DATA_DIR", str(tmp_path))
    from app import uploads

    return uploads


def _upload(uploads, text: str, *, tz: str = "UTC", workspace_id: str = "ws1"):
    """Store `text` as an upload, with the summary its own parse yields (as step 3's route will)."""
    wide, summary = csv_wide.parse_and_summarise(text, tz)
    return uploads.create(
        workspace_id,
        filename="export.csv",
        tz=tz,
        content=text,
        # The store keeps the timestamp column at index 0 (uploads.Upload.columns).
        columns=[wide.timestamp_name, *wide.columns],
        rows=summary.rows,
        resolution_s=summary.resolution_s,
        first_ts=summary.first_ts,
        last_ts=summary.last_ts,
    )


def _load(uploads, upload, window, *, column="Verbruik", unit="kWh", slot=SLOT):
    """`CsvSource.load_with_warnings` for one binding, in the fixture's workspace."""
    return CsvSource().load_with_warnings(
        slot,
        window,
        workspace_id=upload.workspace_id,
        binding=CsvBinding(upload_id=upload.id, column=column, unit=unit),
    )


# ── Registry and descriptor ──────────────────────────────────────────────────────────────────


def test_every_energy_slot_offers_csv_except_power_grid_and_no_price_slot_does():
    # D-PRICE across the whole roster, plus the one named exclusion. Asserting over SERIES_SLOTS
    # rather than a couple of examples is what caught `power_grid`: it is declared kind="energy"
    # (see the dedicated test below for why that is a lossy encoding of §4.1's "power").
    for slot in SERIES_SLOTS:
        keys = [d.key for d in sources_for(slot)]
        expected = slot.kind == "energy" and slot.name != "power_grid"
        assert ("csv_upload" in keys) == expected, slot.name


def test_price_spot_does_not_offer_csv():
    assert "csv_upload" not in [d.key for d in sources_for(SLOT_BY_NAME["price_spot"])]


def test_descriptor_is_backend_load():
    d = CsvSource().descriptor
    assert d.key == "csv_upload"
    assert d.kind == "backend_load"
    assert d.label and d.blurb


def test_get_source_by_key():
    assert isinstance(get_source("csv_upload"), CsvSource)


def test_available_for_reads_slot_kind():
    source = CsvSource()
    assert source.available_for(SLOT_BY_NAME["grid_import_t1"])
    assert source.available_for(SLOT_BY_NAME["solar_production"])
    assert not source.available_for(SLOT_BY_NAME["price_spot"])


def test_power_grid_is_excluded_despite_being_kind_energy():
    # §4.1 (docs/specs/05-data-formats.md) gives power_grid kind **power** — "Signed W, import
    # positive" — but `SeriesKind` is only "energy" | "price", so series_vocab records it as
    # "energy". The kind gate alone therefore offered it, and a watt column would have been stored
    # as a kWh-per-interval energy series with its numbers unchanged. §6.17's
    # `power_energy_consistency` (`power_mean_w / 1000 * dt_h`) confirms the slot means mean watts.
    # There is no watt unit on this path, so the slot is excluded until there is one.
    assert SLOT_BY_NAME["power_grid"].kind == "energy"  # the lossy encoding this guards against
    assert not CsvSource().available_for(SLOT_BY_NAME["power_grid"])
    assert "csv_upload" not in [d.key for d in sources_for(SLOT_BY_NAME["power_grid"])]


def test_label_and_blurb_are_mirrored_for_extraction():
    # Ground rule 5: descriptor strings live where pybabel cannot see them, so they are mirrored
    # into sample_data._SOURCE_STRINGS. test_no_english_leakage.py enforces this too; asserting it
    # here names the reason at the source that owns the strings.
    from app.sample_data import _SOURCE_STRINGS

    d = CsvSource().descriptor
    assert d.label in _SOURCE_STRINGS
    assert d.blurb in _SOURCE_STRINGS


# ── Windowing: the whole point of this layer ─────────────────────────────────────────────────


def test_window_inside_coverage_selects_only_those_intervals(store):
    up = _upload(store, _hourly_csv(6))
    frame, _ = _load(
        store, up, (datetime(2025, 1, 1, 2, tzinfo=UTC), datetime(2025, 1, 1, 4, tzinfo=UTC))
    )
    assert frame.name == "grid_import_t1"
    assert frame.kind == "energy"
    assert list(frame.index.astype("datetime64[h]").astype(str)) == [
        "2025-01-01T02",
        "2025-01-01T03",
    ]
    assert frame.values == pytest.approx([0.2, 0.3])


def test_window_end_is_exclusive(store):
    # Half-open [start, end): the interval starting exactly at `end` belongs to the next window,
    # so two adjacent loads cannot double-count it.
    up = _upload(store, _hourly_csv(6))
    frame, _ = _load(
        store, up, (datetime(2025, 1, 1, 0, tzinfo=UTC), datetime(2025, 1, 1, 3, tzinfo=UTC))
    )
    assert frame.values == pytest.approx([0.0, 0.1, 0.2])


def test_window_start_is_inclusive(store):
    up = _upload(store, _hourly_csv(6))
    frame, _ = _load(
        store, up, (datetime(2025, 1, 1, 5, tzinfo=UTC), datetime(2025, 1, 1, 9, tzinfo=UTC))
    )
    assert frame.values == pytest.approx([0.5])


def test_window_overlapping_the_start_clamps_to_coverage(store):
    # §7.4: clamp to coverage, never pad. The frame carries what the file has and nothing else.
    up = _upload(store, _hourly_csv(6))
    frame, _ = _load(
        store, up, (datetime(2024, 12, 30, tzinfo=UTC), datetime(2025, 1, 1, 2, tzinfo=UTC))
    )
    assert frame.values == pytest.approx([0.0, 0.1])


def test_window_overlapping_the_end_clamps_to_coverage(store):
    up = _upload(store, _hourly_csv(6))
    frame, _ = _load(
        store, up, (datetime(2025, 1, 1, 4, tzinfo=UTC), datetime(2025, 6, 1, tzinfo=UTC))
    )
    assert frame.values == pytest.approx([0.4, 0.5])


def test_window_wholly_before_coverage_is_empty_not_an_error(store):
    up = _upload(store, _hourly_csv(6))
    frame, warnings = _load(
        store, up, (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC))
    )
    assert len(frame.index) == 0
    assert len(frame.values) == 0
    assert frame.resolution_s is None
    assert warnings == []


def test_window_wholly_after_coverage_is_empty(store):
    up = _upload(store, _hourly_csv(6))
    frame, _ = _load(
        store, up, (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))
    )
    assert len(frame.index) == 0


def test_resolution_is_inferred_on_the_slice(store):
    up = _upload(store, _hourly_csv(6))
    # Whole file: hourly.
    whole, _ = _load(
        store, up, (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )
    assert whole.resolution_s == 3600
    # A one-sample slice has no spacing to infer from, so None rather than the file's 3600 — the
    # frame reports what the window contains.
    one, _ = _load(
        store, up, (datetime(2025, 1, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, 2, tzinfo=UTC))
    )
    assert len(one.values) == 1
    assert one.resolution_s is None


def test_naive_window_bounds_are_read_as_utc(store):
    up = _upload(store, _hourly_csv(6))
    frame, _ = _load(store, up, (datetime(2025, 1, 1, 1), datetime(2025, 1, 1, 3)))
    assert frame.values == pytest.approx([0.1, 0.2])


def test_offset_window_bounds_are_converted(store):
    from datetime import timedelta

    up = _upload(store, _hourly_csv(6))
    plus_two = timezone(timedelta(hours=2))
    # 03:00+02:00 == 01:00Z, 05:00+02:00 == 03:00Z.
    frame, _ = _load(
        store,
        up,
        (datetime(2025, 1, 1, 3, tzinfo=plus_two), datetime(2025, 1, 1, 5, tzinfo=plus_two)),
    )
    assert frame.values == pytest.approx([0.1, 0.2])


def test_slice_to_window_is_pure_and_directly_testable():
    # The function exists separately because an unsliced load is wrong with no error anywhere; keep
    # a test that does not go through the store at all.
    from app.domain.frames import SeriesFrame

    index = np.array(
        ["2025-01-01T00", "2025-01-01T01", "2025-01-01T02"], dtype="datetime64[s]"
    )
    frame = SeriesFrame(
        name="grid_import_t1",
        kind="energy",
        resolution_s=3600,
        index=index,
        values=np.array([1.0, 2.0, 3.0]),
        quality=np.zeros(3, dtype=QUALITY_DTYPE),
    )
    out = slice_to_window(
        frame, (datetime(2025, 1, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, 2, tzinfo=UTC))
    )
    assert out.values == pytest.approx([2.0])
    assert out.name == "grid_import_t1"
    assert out.kind == "energy"


def test_duplicate_dst_instant_is_never_split_by_a_window_bound():
    # A full-day October Amsterdam file resolves both rows of the repeated hour to one UTC instant
    # (documented in csv_wide's module docstring), so the index is not strictly increasing. Both
    # searchsorted bounds use side="left", so a window boundary at that instant includes both rows
    # or neither — never one of the pair, which would silently halve that hour's energy.
    from app.domain.frames import SeriesFrame

    index = np.array(
        ["2025-10-26T00", "2025-10-26T00", "2025-10-26T02"], dtype="datetime64[s]"
    )
    frame = SeriesFrame(
        name="grid_import_t1",
        kind="energy",
        resolution_s=None,
        index=index,
        values=np.array([1.0, 2.0, 3.0]),
        quality=np.zeros(3, dtype=QUALITY_DTYPE),
    )
    # Start ON the duplicated instant: both.
    inc = slice_to_window(
        frame, (datetime(2025, 10, 26, 0, tzinfo=UTC), datetime(2025, 10, 26, 1, tzinfo=UTC))
    )
    assert inc.values == pytest.approx([1.0, 2.0])
    # End ON the duplicated instant: neither.
    exc = slice_to_window(
        frame, (datetime(2025, 10, 25, tzinfo=UTC), datetime(2025, 10, 26, 0, tzinfo=UTC))
    )
    assert len(exc.values) == 0


@pytest.mark.parametrize(
    "start_h, end_h",
    [
        (1, 0),  # end < start: numpy's negative slice would return empty on its own…
        (1, 1),  # …but end == start needs the clamp, since index[1:1] is only empty by accident
    ],                                                                # of the bounds being equal.
)
def test_slice_to_window_with_end_at_or_before_start_is_empty(start_h, end_h):
    # The `hi = max(hi, lo)` clamp. A review found that deleting it survived the original test,
    # which used end < start only — where numpy's negative-width slice already yields nothing. The
    # end == start case is the one that exercises the clamp as a clamp.
    from app.domain.frames import SeriesFrame

    index = np.array(["2025-01-01T00", "2025-01-01T01"], dtype="datetime64[s]")
    frame = SeriesFrame(
        name="grid_import_t1",
        kind="energy",
        resolution_s=3600,
        index=index,
        values=np.array([1.0, 2.0]),
        quality=np.zeros(2, dtype=QUALITY_DTYPE),
    )
    out = slice_to_window(
        frame,
        (
            datetime(2025, 1, 1, start_h, tzinfo=UTC),
            datetime(2025, 1, 1, end_h, tzinfo=UTC),
        ),
    )
    assert len(out.values) == 0
    assert len(out.index) == 0


def test_fractional_window_bounds_round_up_at_both_ends(store):
    # Sub-second bounds are reachable: `main._parse_window` uses `datetime.fromisoformat`, which
    # accepts "…T00:00:00.5+00:00". Both bounds must round UP (see `slice_to_window`'s derivation).
    # Flooring both, the original bug, is wrong at each end in opposite directions, and the
    # plausible-sounding "floor the start, ceil the end" fixes only one of the two — so both
    # directions get their own assertion.
    up = _upload(store, _hourly_csv(3))

    # A start half a second PAST 00:00 must not pull in the 00:00 sample — it is outside the window.
    frame, _ = _load(
        store,
        up,
        (
            datetime(2025, 1, 1, 0, 0, 0, 500_000, tzinfo=UTC),
            datetime(2025, 1, 1, 2, tzinfo=UTC),
        ),
    )
    assert frame.values == pytest.approx([0.1])

    # An end half a second past 00:00 must KEEP the 00:00 sample — it is inside the window. This is
    # the case the old docstring's "cannot select a different set of samples" claim got wrong.
    frame, _ = _load(
        store,
        up,
        (
            datetime(2025, 1, 1, 0, tzinfo=UTC),
            datetime(2025, 1, 1, 0, 0, 0, 500_000, tzinfo=UTC),
        ),
    )
    assert frame.values == pytest.approx([0.0])


# ── Units ────────────────────────────────────────────────────────────────────────────────────


def test_wh_binding_converts_to_kwh(store):
    text = "Tijdstip,Verbruik\n01-01-2025 00:00:00,1000\n01-01-2025 01:00:00,2500\n"
    up = _upload(store, text)
    frame, _ = _load(
        store,
        up,
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
        unit="Wh",
    )
    assert frame.values == pytest.approx([1.0, 2.5])


def test_bad_unit_is_rejected(store):
    up = _upload(store, _hourly_csv(6))
    with pytest.raises(csv_wide.CsvFormatError) as exc:
        _load(
            store,
            up,
            (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
            unit="MWh",
        )
    assert exc.value.code == "bad_unit"


def test_bad_unit_is_rejected_before_the_file_is_read(store):
    # The unit check is duplicated here on purpose (`column_frame` also raises `bad_unit`), so that a
    # unit the drawer could never satisfy is reported without a disk read. Deleting the file is what
    # makes the difference observable: with the early check, `bad_unit`; without it, the read fails
    # first with FileNotFoundError. A review found that `if ...:` → `if False:` survived every other
    # test in this module precisely because `column_frame` caught it downstream, so the property was
    # asserted in a docstring and nowhere else.
    up = _upload(store, _hourly_csv(6))
    store.path_for(up.workspace_id, up.id).unlink()
    with pytest.raises(csv_wide.CsvFormatError) as exc:
        _load(
            store,
            up,
            (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
            unit="MWh",
        )
    assert exc.value.code == "bad_unit"


def test_wh_scaling_with_a_negative_value_and_a_gap(store):
    # A signed column (a net-meter export reading) with a gap in it: the factor applies to the
    # negative value like any other, and the gap stays NaN rather than becoming 0 Wh.
    text = (
        "Tijdstip,Net\n"
        "01-01-2025 00:00:00,1500\n"
        "01-01-2025 01:00:00,-800\n"
        "01-01-2025 02:00:00,\n"
        "01-01-2025 03:00:00,250\n"
    )
    up = _upload(store, text)
    frame, warnings = _load(
        store,
        up,
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
        column="Net",
        unit="Wh",
    )
    assert frame.values[0] == pytest.approx(1.5)
    assert frame.values[1] == pytest.approx(-0.8)
    assert np.isnan(frame.values[2])
    assert frame.values[3] == pytest.approx(0.25)
    assert warnings[0] == {"code": "CSV_GAP_CELLS", "column": "Net", "count": 1}


# ── Warnings, recounted against the window ───────────────────────────────────────────────────


def test_gap_warning_counts_only_gaps_inside_the_window(store):
    # Two gaps: one at 01:00, one at 04:00.
    text = (
        "Tijdstip,Verbruik\n"
        "01-01-2025 00:00:00,0.1\n"
        "01-01-2025 01:00:00,\n"
        "01-01-2025 02:00:00,0.3\n"
        "01-01-2025 03:00:00,0.4\n"
        "01-01-2025 04:00:00,\n"
        "01-01-2025 05:00:00,0.6\n"
    )
    up = _upload(store, text)

    whole, warnings = _load(
        store, up, (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )
    assert [w["code"] for w in warnings] == ["CSV_GAP_CELLS"]
    assert warnings[0] == {"code": "CSV_GAP_CELLS", "column": "Verbruik", "count": 2}
    gap_bit = QUALITY_DTYPE(QualityFlags.GAP_FILLED)
    assert int(np.count_nonzero(whole.quality & gap_bit)) == 2

    # A window covering only the second gap reports one, not two.
    _, warnings = _load(
        store, up, (datetime(2025, 1, 1, 3, tzinfo=UTC), datetime(2025, 1, 1, 6, tzinfo=UTC))
    )
    assert warnings[0]["count"] == 1

    # A window covering neither reports nothing at all.
    _, warnings = _load(
        store, up, (datetime(2025, 1, 1, 2, tzinfo=UTC), datetime(2025, 1, 1, 4, tzinfo=UTC))
    )
    assert warnings == []


def test_dst_ambiguous_warning_names_the_day_and_is_window_scoped(store):
    # The October repeated hour under Amsterdam: 02:00–02:59 local occurs twice (D-DST), resolved
    # to the first (CEST) occurrence and flagged. Two rows at 02:00 and 02:30 → both flagged.
    text = (
        "Tijdstip,Verbruik\n"
        "26-10-2025 01:00:00,0.1\n"
        "26-10-2025 02:00:00,0.2\n"
        "26-10-2025 02:30:00,0.3\n"
        "26-10-2025 04:00:00,0.4\n"
    )
    up = _upload(store, text, tz="Europe/Amsterdam")

    frame, warnings = _load(
        store, up, (datetime(2025, 10, 25, tzinfo=UTC), datetime(2025, 10, 27, tzinfo=UTC))
    )
    codes = {w["code"]: w for w in warnings}
    assert "CSV_DST_AMBIGUOUS_HOUR" in codes
    amb = codes["CSV_DST_AMBIGUOUS_HOUR"]
    assert amb["column"] == "Verbruik"
    assert amb["count"] == 2
    assert amb["days"] == ["2025-10-26"]
    amb_bit = QUALITY_DTYPE(QualityFlags.DST_AMBIGUOUS)
    assert int(np.count_nonzero(frame.quality & amb_bit)) == 2

    # A window excluding the flagged samples raises no ambiguity warning: the box must not name a
    # day the run does not cover. 02:00 CEST == 00:00Z, so a window starting at 00:30Z drops both.
    _, warnings = _load(
        store,
        up,
        (datetime(2025, 10, 26, 0, 45, tzinfo=UTC), datetime(2025, 10, 27, tzinfo=UTC)),
    )
    assert [w["code"] for w in warnings] == []


def test_upload_tz_is_not_re_applied(store):
    # D-TZ: the parse applied the zone at upload and `Upload.tz` records that. Loading must
    # reproduce the same UTC instants, not shift again. 01-01 00:00 Amsterdam == 2024-12-31 23:00Z.
    up = _upload(store, _hourly_csv(3), tz="Europe/Amsterdam")
    frame, _ = _load(
        store, up, (datetime(2024, 12, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))
    )
    assert str(frame.index[0]) == "2024-12-31T23:00:00"
    assert up.first_ts == datetime(2024, 12, 31, 23, tzinfo=UTC)


# ── Error paths ──────────────────────────────────────────────────────────────────────────────


def test_load_without_a_binding_raises_and_names_the_slot(store):
    with pytest.raises(CsvBindingError) as exc:
        CsvSource().load(
            SLOT,
            (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
            workspace_id="ws1",
        )
    assert "grid_import_t1" in str(exc.value)


def test_load_without_a_workspace_raises(store):
    with pytest.raises(CsvBindingError):
        CsvSource().load(
            SLOT,
            (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
            binding=CsvBinding(upload_id="0" * 32, column="Verbruik", unit="kWh"),
        )


def test_binding_to_an_upload_this_workspace_does_not_have(store):
    up = _upload(store, _hourly_csv(3), workspace_id="ws1")
    # Same id, other workspace: the store scopes by workspace, so it reads as absent.
    with pytest.raises(CsvBindingError):
        CsvSource().load(
            SLOT,
            (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
            workspace_id="ws2",
            binding=CsvBinding(upload_id=up.id, column="Verbruik", unit="kWh"),
        )


def test_row_outliving_its_file_raises_file_not_found(store):
    up = _upload(store, _hourly_csv(3))
    store.path_for(up.workspace_id, up.id).unlink()
    with pytest.raises(FileNotFoundError):
        _load(store, up, (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)))


def test_unknown_column_is_rejected(store):
    up = _upload(store, _hourly_csv(3))
    with pytest.raises(csv_wide.CsvFormatError) as exc:
        _load(
            store,
            up,
            (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
            column="Nope",
        )
    assert exc.value.code == "unknown_column"


def test_cumulative_column_is_rejected_not_differenced(store):
    # D-KIND: a non-decreasing column is a meter register and is refused on selection. 14 rows,
    # rising throughout, clears MONOTONIC_MIN_SAMPLES.
    lines = ["Tijdstip,Meter"]
    for i in range(14):
        lines.append(f"01-01-2025 {i:02d}:00:00,{100 + i * 0.5:.1f}")
    up = _upload(store, "\n".join(lines) + "\n")
    with pytest.raises(csv_wide.CsvFormatError) as exc:
        _load(
            store,
            up,
            (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
            column="Meter",
        )
    assert exc.value.code == "cumulative_column"


def test_single_row_file_has_no_inferrable_resolution(store):
    # One reading is a legitimate upload; there is no spacing to take a mode over, so resolution_s
    # is None rather than a guess. `infer_resolution_s` answers this, not a special case here.
    up = _upload(store, _hourly_csv(1))
    frame, _ = _load(
        store, up, (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )
    assert len(frame.values) == 1
    assert frame.resolution_s is None


def test_all_gap_column_loads_as_all_nan_and_warns_for_every_row(store):
    # A column that is entirely empty cells is a real export shape (an unused sensor). It is a
    # column of gaps, not a column of zeros — the distinction §4.2a insists on — so the values are
    # NaN and every row is flagged. It is NOT rejected: the file is fine and so is the column's
    # shape; the emptiness is a data-quality fact for §7.3 to report.
    text = (
        "Tijdstip,Ongebruikt\n"
        "01-01-2025 00:00:00,\n"
        "01-01-2025 01:00:00,\n"
        "01-01-2025 02:00:00,\n"
    )
    up = _upload(store, text)
    frame, warnings = _load(
        store,
        up,
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
        column="Ongebruikt",
    )
    assert np.all(np.isnan(frame.values))
    assert warnings == [{"code": "CSV_GAP_CELLS", "column": "Ongebruikt", "count": 3}]


def test_binding_uses_the_uniquified_column_name(store):
    # Two columns share a header, so `csv_wide` issues "Zon" and "Zon (2)" — the binding key is the
    # uniquified name, not the raw cell. Step 6's column selector must offer these names verbatim.
    text = (
        "Tijdstip,Zon,Zon\n"
        "01-01-2025 00:00:00,1.0,9.0\n"
        "01-01-2025 01:00:00,2.0,8.0\n"
    )
    up = _upload(store, text)
    assert up.columns == ["Tijdstip", "Zon", "Zon (2)"]
    window = (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))

    first, _ = _load(store, up, window, column="Zon")
    second, _ = _load(store, up, window, column="Zon (2)")
    assert first.values == pytest.approx([1.0, 2.0])
    assert second.values == pytest.approx([9.0, 8.0])


def test_slice_keeps_quality_aligned_with_values(store):
    # The slice takes three parallel arrays with one pair of bounds; a mismatch would silently
    # attribute one row's gap flag to another row's value. The gap is placed off-centre so an
    # off-by-one would move it.
    text = (
        "Tijdstip,V\n"
        "01-01-2025 00:00:00,0.0\n"
        "01-01-2025 01:00:00,1.0\n"
        "01-01-2025 02:00:00,\n"
        "01-01-2025 03:00:00,3.0\n"
        "01-01-2025 04:00:00,4.0\n"
    )
    up = _upload(store, text)
    frame, _ = _load(
        store,
        up,
        (datetime(2025, 1, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, 4, tzinfo=UTC)),
        column="V",
    )
    gap_bit = QUALITY_DTYPE(QualityFlags.GAP_FILLED)
    flagged = (frame.quality & gap_bit) != 0
    # Rows 01:00, 02:00, 03:00; the NaN is the middle one and its flag must be the middle one too.
    assert list(flagged) == [False, True, False]
    assert np.isnan(frame.values[flagged][0])
    assert frame.values[0] == pytest.approx(1.0)
    assert frame.values[2] == pytest.approx(3.0)
    assert len(frame.index) == len(frame.values) == len(frame.quality) == 3


def test_stale_binding_after_the_file_is_replaced_under_the_same_id(store):
    # The uploads store assigns ids, so this needs a deliberate overwrite of the bytes — but a
    # hand-edited data dir, or a restore from a backup taken at a different time, produces exactly
    # this: a binding naming a column the file no longer has. It surfaces as `unknown_column`, which
    # names the columns the file DOES have, rather than as an empty series.
    up = _upload(store, _hourly_csv(3, column="Verbruik"))
    store.path_for(up.workspace_id, up.id).write_text(
        _hourly_csv(3, column="Iets anders"), encoding="utf-8"
    )
    with pytest.raises(csv_wide.CsvFormatError) as exc:
        _load(
            store, up, (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
        )
    assert exc.value.code == "unknown_column"


def test_emptied_file_under_a_live_row_is_rejected_by_the_parser(store):
    # The file is truncated to nothing while its row survives (a failed restore, an interrupted
    # write). `read_text` succeeds — the file exists — so the failure is the parser's, and it is the
    # file-level "no header" rejection rather than a silent zero-row series.
    up = _upload(store, _hourly_csv(3))
    store.path_for(up.workspace_id, up.id).write_text("", encoding="utf-8")
    with pytest.raises(csv_wide.CsvFormatError) as exc:
        _load(
            store, up, (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
        )
    assert exc.value.code == "missing_header"


def test_upload_row_can_be_injected(store):
    # A caller holding the row already (step 3's route, or a test) may pass it and save a query.
    up = _upload(store, _hourly_csv(3))
    frame, _ = CsvSource().load_with_warnings(
        SLOT,
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
        workspace_id=up.workspace_id,
        binding=CsvBinding(upload_id=up.id, column="Verbruik", unit="kWh"),
        upload=up,
    )
    assert len(frame.values) == 3


def test_load_returns_the_frame_alone(store):
    # The protocol call is `load(slot, window) -> SeriesFrame`; the warnings variant is separate.
    up = _upload(store, _hourly_csv(3))
    frame = CsvSource().load(
        SLOT,
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)),
        workspace_id=up.workspace_id,
        binding=CsvBinding(upload_id=up.id, column="Verbruik", unit="kWh"),
    )
    assert len(frame.values) == 3
