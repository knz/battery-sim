"""Unit tests for the data summary (docs/specs/02-ux-wireframes.md §2.3a).

Three layers:

  * The sample view-model: app/sample_data._data_summary()'s shape, and that sample_view() carries
    it. These are the shared shape CONTRACT the computed view-model must also satisfy.
  * The computed view-model: app/summary_view.data_summary_from() over synthetic datasets with
    known totals — the real §6.3 load reconstruction + §6.11 battery-free metrics. Covers the base
    totals, the existing-battery net-of variant, omit-don't-zero for the optional groups, the
    negative-load clamp, and the no-grid → None guard.
  * Panel ①'s data-quality box, on BOTH paths: app/data_view.panel_data_from() (computed) and
    app/sample_data._panel_data() (the static sample the fresh-install page renders). Their
    strings are (msgid, params) MESSAGE PAIRS rather than formatted strings, so their msgid is a
    constant the extractor can see. Asserted both on shape and on the English they render to,
    since the wording IS the msgid — and asserted on the sample too, because the sample is what
    a first-time user sees and a formatted string there would render English on a Dutch page
    while the live page rendered Dutch.

No layer launches a browser or seeds a real dataset (the smoke test covers empty-state absence);
the computed cases build SeriesFrames in-process and wrap them in a LoadedDataset.
"""

from datetime import datetime, timezone

import numpy as np

from app.dataset import LoadedDataset
from app.domain.frames import QUALITY_DTYPE, QualityFlags, SeriesFrame
from app.sample_data import _data_summary, _panel_data, _panel_results, sample_view
from app import i18n
from app.summary_view import data_summary_from


def test_sample_view_includes_data_summary():
    # sample_view() carries the band unconditionally (main.py drops it in the empty state).
    assert "data_summary" in sample_view()


def test_sample_roster_requirement_matches_the_vocabulary():
    # The demo roster's `req` must agree with SlotSpec, not be hand-copied. It drifted once: the
    # T2 registers were written out as "required" while series_vocab called them "optional", so
    # the sample screen painted ● where the live screen painted ○ — which reads as "you must
    # supply a night register" to exactly the single-tariff households §4.1 note 1 describes.
    from app.domain.series_vocab import SLOT_BY_NAME

    rows = _panel_data()["mapping"]
    assert {r["name"] for r in rows} == set(SLOT_BY_NAME)
    for r in rows:
        assert r["req"] == SLOT_BY_NAME[r["name"]].requirement, r["name"]

    # The specific pair the drift hit, pinned by name: expected (note 4), never required.
    by_name = {r["name"]: r for r in rows}
    assert by_name["grid_import_t2"]["req"] == "optional"
    assert by_name["grid_export_t2"]["req"] == "optional"
    assert by_name["grid_import_t1"]["req"] == "required"
    assert by_name["grid_export_t1"]["req"] == "required"


def test_summary_always_present_groups():
    # Grid and Household are always present (specs §2.3a table): they need no PV, no battery, no
    # price — only the meter registers and the load reconstruction.
    s = _data_summary()
    assert set(s["grid"]) == {"imported", "exported"}
    assert set(s["household"]) >= {"consumption", "self_sufficiency", "net_battery"}


def test_summary_existing_battery_variant():
    # The sample demos the existing-battery variant (confirmed with the user): the battery group
    # is present, and Household is flagged net_of the existing battery so the template labels it.
    s = _data_summary()
    assert s["battery"] is not None
    assert set(s["battery"]) == {"charged", "discharged"}
    assert s["household"]["net_battery"] is True


def test_summary_optional_groups_are_omit_not_zero():
    # The optional groups are separate keys the template guards on, so a no-PV / no-battery /
    # no-price dataset omits them (renders None) rather than showing 0 (specs §2.4). Here the
    # sample has all three, but the keys must exist so the template's `{% if %}` guards resolve.
    s = _data_summary()
    for key in ("solar", "battery", "price"):
        assert key in s


# ── The computed view-model (app/summary_view.data_summary_from) ─────────────────────────────
#
# Synthetic frames on a fixed hourly window so the totals are exact. HOURS intervals of 1 h each,
# starting at 2026-01-01T00:00 UTC; a constant per-interval value v sums to v * HOURS kWh.

HOURS = 24
_WIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_WIN_END = datetime(2026, 1, 2, tzinfo=timezone.utc)  # HOURS hourly intervals


def _energy(name: str, per_interval, n: int = HOURS) -> SeriesFrame:
    """An hourly energy frame of `n` intervals; `per_interval` is a scalar or an array of kWh."""
    idx = (np.arange(n).astype("timedelta64[s]") * 3600 + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    values = np.full(n, float(per_interval)) if np.isscalar(per_interval) else np.asarray(per_interval, dtype=float)
    return SeriesFrame(name, "energy", 3600, idx, values, np.zeros(n, dtype=QUALITY_DTYPE))


def _price(name: str, values, n: int = HOURS) -> SeriesFrame:
    idx = (np.arange(n).astype("timedelta64[s]") * 3600 + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    vals = np.full(n, float(values)) if np.isscalar(values) else np.asarray(values, dtype=float)
    return SeriesFrame(name, "price", 3600, idx, vals, np.zeros(n, dtype=QUALITY_DTYPE))


def _dataset(frames: list[SeriesFrame]) -> LoadedDataset:
    return LoadedDataset(
        id=1,
        source_type="test",
        window=(_WIN_START, _WIN_END),
        fetched_at=_WIN_START,
        frames=frames,
        warnings=[],
        series_sources={f.name: "test" for f in frames},
    )


def _render(m, locale: str = "en") -> str:
    """Render a view-model message or FIGURE the way the template does — in English by default.

    Goes through the real per-locale Jinja environment and the real `_msg.html` macro, so this
    asserts what a reader sees rather than a reimplementation of the render.

    `locale` is explicit and defaults to "en" because these tests assert English wording AND
    English number conventions ("48 kWh", "0.142 \u20ac/kWh"). Those assertions stay valid as
    assertions about English now that figures are formatted at render time (A6) — what changed is
    that the locale has to be named. Pass locale="nl" to assert the Dutch form.
    """
    from app import i18n
    tpl = '{% from "_msg.html" import msg with context %}{{ msg(m) }}'
    return i18n.env_for(locale).from_string(tpl).render(m=m)


def test_computed_grid_and_household_totals():
    # import 2 kWh/h, export 0, no PV, no battery → load = import − export = 2 kWh/h.
    #   imported = 2 * 24 = 48 kWh; exported = 0; consumption = load = 48 kWh.
    #   self_sufficiency = 1 − import/load = 1 − 48/48 = 0 → "0%" (all consumption from the grid).
    ds = _dataset([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    s = data_summary_from(ds)
    assert s is not None
    assert {k: _render(v) for k, v in s["grid"].items()} == {
        "imported": "48 kWh", "exported": "0 kWh"}
    # load = 48 − 0 = 48 kWh; self_sufficiency = 1 − 48/48 = 0 → "0%".
    assert _render(s["household"]["consumption"]) == "48 kWh"
    assert _render(s["household"]["self_sufficiency"]) == "0%"
    assert s["household"]["net_battery"] is False
    assert s["days"] == 1
    assert s["coverage"] == "2026-01-01 → 2026-01-02"
    # No PV, no battery, no price → those groups omitted (None), template drops them.
    assert s["solar"] is None
    assert s["battery"] is None
    assert s["price"] is None


def test_computed_self_sufficiency_with_pv():
    # import 1 kWh/h, export 0, PV 3 kWh/h → load = 1 + 3 = 4 kWh/h; over 24 h: import 24, load 96.
    #   self_sufficiency = 1 − 24/96 = 0.75 → "75%".
    #   self_consumption = 1 − export/pv = 1 − 0/72 = 1.0 → "100%".
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ])
    s = data_summary_from(ds)
    assert _render(s["household"]["self_sufficiency"]) == "75%"
    assert _render(s["solar"]["produced"]) == "72 kWh"
    assert _render(s["solar"]["self_consumption"]) == "100%"
    assert s["solar"]["partial"] is False  # PV spans the whole window here
    assert s["household"]["net_battery"] is False
    assert s["notes"] == []


def test_computed_tariff_registers_fold_together():
    # T1 + T2 import fold into one import total: 1 + 2 = 3 kWh/h → 72 kWh imported.
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_import_t2", 2.0),
        _energy("grid_export_t1", 0.0),
    ])
    s = data_summary_from(ds)
    assert _render(s["grid"]["imported"]) == "72 kWh"


def test_computed_existing_battery_variant():
    # An existing battery is mapped → §6.3 strips it: load = imp − exp + batt_dis − batt_chg.
    #   import 5 kWh/h, export 0, charge 2 kWh/h, discharge 1 kWh/h.
    #   load = 5 + 1 − 2 = 4 kWh/h → 96 kWh; battery group present; household net_battery True.
    ds = _dataset([
        _energy("grid_import_t1", 5.0),
        _energy("grid_export_t1", 0.0),
        _energy("battery_charge", 2.0),
        _energy("battery_discharge", 1.0),
    ])
    s = data_summary_from(ds)
    assert _render(s["household"]["consumption"]) == "96 kWh"
    assert s["household"]["net_battery"] is True
    assert {k: _render(v) for k, v in s["battery"].items()} == {
        "charged": "48 kWh", "discharged": "24 kWh"}


def test_computed_heavy_clamp_marks_reconstruction_unreliable():
    # export > import with no PV/battery → reconstructed load is negative every interval and is
    # clamped (§6.3). The clamp discards ~all of the load, over the 5% reliability threshold, so
    # consumption + self_sufficiency are SUPPRESSED (None) and a `load_unreliable` note is added —
    # the tell-tale of real PV export the solar sensor did not report (the live-data bug this fixes).
    ds = _dataset([_energy("grid_import_t1", 1.0), _energy("grid_export_t1", 3.0)])
    s = data_summary_from(ds)
    assert s["household"]["consumption"] is None
    assert s["household"]["self_sufficiency"] is None
    assert s["household"]["self_sufficiency_clamped"] is False
    assert any(n["key"] == "load_unreliable" for n in s["notes"])
    # The note carries the exported total so the warning can name it (48 kWh over the window).
    note = next(n for n in s["notes"] if n["key"] == "load_unreliable")
    assert _render(note["export_kwh"]) == "72 kWh"  # 3 kWh/h × 24


def test_computed_small_clamp_stays_reliable():
    # A FEW clamped intervals (sensor noise / minor skew) stay under the 5% threshold, so the
    # figures are still shown and no warning fires. One export spike in an otherwise net-import
    # window: 23 h at load 5, 1 h at load −5 (clamped). clamped 5 of ~115 kWh ≈ 4.3% < 5%.
    imp = np.full(HOURS, 5.0)
    exp = np.zeros(HOURS)
    exp[0] = 10.0  # one hour exports 10 while importing 5 → load −5, clamped
    ds = _dataset([_energy("grid_import_t1", imp), _energy("grid_export_t1", exp)])
    s = data_summary_from(ds)
    assert s["household"]["consumption"] is not None
    assert not any(n["key"] == "load_unreliable" for n in s["notes"])


def test_computed_negative_self_sufficiency_is_display_clamped():
    # An existing battery that net-CHARGES over the window (charge 2 > discharge 1 each hour) ends
    # more charged than it started, so grid import (5) exceeds reconstructed load (5+1−2=4). The
    # raw 1 − import/load = 1 − 120/96 = −0.25 is honest but negative; the DISPLAY clamps to 0%
    # and sets self_sufficiency_clamped so the band shows the "evens out over cycles" caveat (§2.3a).
    ds = _dataset([
        _energy("grid_import_t1", 5.0),
        _energy("grid_export_t1", 0.0),
        _energy("battery_charge", 2.0),
        _energy("battery_discharge", 1.0),
    ])
    s = data_summary_from(ds)
    assert _render(s["household"]["consumption"]) == "96 kWh"  # 4 kWh/h × 24
    assert _render(s["household"]["self_sufficiency"]) == "0%"
    assert s["household"]["self_sufficiency_clamped"] is True


def test_computed_self_sufficiency_not_clamped_when_positive():
    # The clamp flag stays False in the ordinary case (import < load), so the caveat is not shown.
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", 3.0),
    ])
    s = data_summary_from(ds)
    assert _render(s["household"]["self_sufficiency"]) == "75%"
    assert s["household"]["self_sufficiency_clamped"] is False


def test_computed_price_stats_over_own_coverage():
    # Price avg/min/max over the price series, with a negative spot price rendered with U+2212.
    prices = np.array([0.10, 0.20, -0.05] + [0.15] * (HOURS - 3))
    ds = _dataset([
        _energy("grid_import_t1", 1.0),
        _energy("grid_export_t1", 0.0),
        _price("price_spot", prices),
    ])
    s = data_summary_from(ds)
    assert _render(s["price"]["min"]) == "−0.050 €/kWh"  # U+2212 minus, 3 dp
    assert _render(s["price"]["max"]) == "0.200 €/kWh"
    # avg is the plain mean of the per-interval prices.
    assert _render(s["price"]["avg"]) == f"{prices.mean():.3f} €/kWh"


def test_computed_returns_none_without_grid():
    # A dataset with only a price series (no covering energy series) has no simulatable grid, so
    # the band is unsummarisable → None (main.py then omits it, as in the empty state).
    ds = _dataset([_price("price_spot", 0.15)])
    assert data_summary_from(ds) is None


def _energy_subwindow(name: str, per_interval: float, start_hour: int, n: int) -> SeriesFrame:
    """An hourly energy frame starting `start_hour` hours into the base window, `n` intervals long.

    Models a series (solar, battery) mapped PART-WAY through a longer meter history — the real case
    behind the "grid import looks low" bug: panels installed months into a two-year record.
    """
    base = np.datetime64("2026-01-01T00:00:00") + np.timedelta64(start_hour, "h")
    idx = (np.arange(n).astype("timedelta64[s]") * 3600 + base).astype("datetime64[s]")
    return SeriesFrame(name, "energy", 3600, idx, np.full(n, float(per_interval)), np.zeros(n, dtype=QUALITY_DTYPE))


def _dataset_2day(frames: list[SeriesFrame]) -> LoadedDataset:
    # A 48-hour window so a short (24 h) solar series can be strictly inside it.
    return LoadedDataset(
        id=1, source_type="test",
        window=(_WIN_START, datetime(2026, 1, 3, tzinfo=timezone.utc)),
        fetched_at=_WIN_START, frames=frames, warnings=[],
        series_sources={f.name: "test" for f in frames},
    )


def test_computed_short_solar_does_not_clip_grid_totals():
    # THE "grid import looks very low" FIX. The meters span the full 48 h; solar covers only the
    # last 24 h. The window must be driven by the GRID meters, so import totals the full 48 h, not
    # the 24 h solar overlap. (Before the fix, effective_window intersected all series and import
    # was clipped to solar's span.)
    meters_full = [
        _energy("grid_import_t1", 2.0, n=48),   # 48 h × 2 = 96 kWh
        _energy("grid_export_t1", 0.0, n=48),
    ]
    solar_late = _energy_subwindow("solar_production", 1.0, start_hour=24, n=24)  # last 24 h only
    ds = _dataset_2day(meters_full + [solar_late])
    s = data_summary_from(ds)
    # Import spans the full 48 h (96 kWh), NOT clipped to solar's 24 h (which would give 48 kWh).
    assert _render(s["grid"]["imported"]) == "96 kWh"
    assert s["days"] == 2
    # Solar reports its OWN 24 h span and flags partial so it is not read against the 48 h window.
    assert _render(s["solar"]["produced"]) == "24 kWh"
    assert s["solar"]["partial"] is True
    assert s["solar"]["days"] == 1


def test_computed_near_zero_pv_omits_solar_with_note():
    # THE −1001532% FIX. A solar sensor mapped but reporting almost nothing (below the 1 kWh floor)
    # is treated as empty: the Solar group is omitted (not "Produced 0 kWh", not a divide-by-~0
    # self_consumption) and a `solar_empty` data-quality note is added instead.
    tiny = np.zeros(HOURS)
    tiny[0] = 0.03  # a single stray reading, 0.03 kWh total — well below PV_PRESENT_FLOOR_KWH
    ds = _dataset([
        _energy("grid_import_t1", 2.0),
        _energy("grid_export_t1", 0.0),
        _energy("solar_production", tiny),
    ])
    s = data_summary_from(ds)
    assert s["solar"] is None
    assert any(n["key"] == "solar_empty" for n in s["notes"])
    # Household still computes (import 48, no real PV → load 48): the empty PV adds ~nothing.
    assert _render(s["household"]["consumption"]) == "48 kWh"


def test_computed_self_consumption_over_pv_window_not_full_window():
    # self_consumption compares PV against export over the PV's OWN window, not the whole window.
    # Meters span 48 h and export 1 kWh/h throughout (48 kWh). Solar covers the last 24 h at 4
    # kWh/h (96 kWh). self_consumption = 1 − export_in_pv_window/pv = 1 − 24/96 = 0.75 → "75%".
    # (Using full-window export 48 would wrongly give 1 − 48/96 = 50%.)
    ds = _dataset_2day([
        _energy("grid_import_t1", 3.0, n=48),
        _energy("grid_export_t1", 1.0, n=48),
        _energy_subwindow("solar_production", 4.0, start_hour=24, n=24),
    ])
    s = data_summary_from(ds)
    assert _render(s["solar"]["produced"]) == "96 kWh"
    assert _render(s["solar"]["self_consumption"]) == "75%"


def test_computed_window_restricts_totals_to_subwindow():
    # data_summary_from(ds, window=<subwindow>) reconciles over the passed window, not the dataset's
    # full coverage. Meters span the full 48 h at 2 kWh/h import (96 kWh over the full window); a
    # 24 h sub-window must total only 48 kWh, and the header must show the sub-window's span.
    ds = _dataset_2day([
        _energy("grid_import_t1", 2.0, n=48),
        _energy("grid_export_t1", 0.0, n=48),
    ])
    sub = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
    s = data_summary_from(ds, window=sub)
    assert _render(s["grid"]["imported"]) == "48 kWh"  # 24 h × 2, HALF the full-window 96 kWh
    assert s["days"] == 1
    assert s["coverage"] == "2026-01-01 → 2026-01-02"
    # The no-arg (full-coverage) call is unchanged: still the whole 48 h.
    assert _render(data_summary_from(ds)["grid"]["imported"]) == "96 kWh"


def test_computed_clamp_price_to_window_restricts_price_stats():
    # clamp_price_to_window=True prices only over the sub-window. Prices are 0.10 in the first 24 h
    # and 0.90 in the second 24 h; the first-day sub-window must see only the 0.10 prices, and the
    # full-coverage call (default) must average both halves.
    prices = np.concatenate([np.full(24, 0.10), np.full(24, 0.90)])
    ds = _dataset_2day([
        _energy("grid_import_t1", 1.0, n=48),
        _energy("grid_export_t1", 0.0, n=48),
        _price("price_spot", prices, n=48),
    ])
    sub = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
    s = data_summary_from(ds, window=sub, clamp_price_to_window=True)
    # Only the 0.10 prices fall in the sub-window.
    assert {k: _render(v) for k, v in s["price"].items()} == {
        "avg": "0.100 €/kWh",
        "min": "0.100 €/kWh",
        "max": "0.100 €/kWh",
    }
    # Full-coverage default: both halves, avg 0.50, min 0.10, max 0.90.
    full = data_summary_from(ds)
    assert _render(full["price"]["avg"]) == "0.500 €/kWh"
    assert _render(full["price"]["min"]) == "0.100 €/kWh"
    assert _render(full["price"]["max"]) == "0.900 €/kWh"
    # window given but clamp_price_to_window=False → price still over the series' OWN full coverage.
    unclamped = data_summary_from(ds, window=sub)
    assert _render(unclamped["price"]["avg"]) == "0.500 €/kWh"


def test_computed_view_satisfies_sample_shape_contract():
    # The computed view-model must carry the same keys the sample contract asserts, so the template
    # renders either identically. Build the full existing-battery + PV + price variant and re-run
    # the shape checks the sample tests use.
    ds = _dataset([
        _energy("grid_import_t1", 5.0),
        _energy("grid_export_t1", 1.0),
        _energy("solar_production", 3.0),
        _energy("battery_charge", 2.0),
        _energy("battery_discharge", 1.0),
        _price("price_spot", 0.15),
    ])
    s = data_summary_from(ds)
    assert set(s["grid"]) == {"imported", "exported"}
    assert set(s["household"]) >= {"consumption", "self_sufficiency", "net_battery"}
    assert set(s["battery"]) == {"charged", "discharged"}
    assert s["household"]["net_battery"] is True
    for key in ("solar", "battery", "price"):
        assert key in s


# ── Panel ①'s quality box as MESSAGES (app/data_view.panel_data_from) ─────────────────────────
#
# Every user-facing string this view-model emits is a (msgid, params) pair, not a formatted
# string, so its msgid is a compile-time constant `pybabel extract` can see. These pin both
# halves of that: the SHAPE the template's `msg()` macro consumes, and the ENGLISH the pair
# renders to — the wording is the msgid, so a test that only checked the shape would let the
# English drift silently.

def _panel(frames):
    from app.data_view import panel_data_from
    return panel_data_from(_dataset(frames))


def test_panel_quality_strings_are_message_pairs_not_formatted_strings():
    """The regression this whole shape exists for: a string assembled here has a msgid that only
    exists at runtime, so it can never be translated and renders in English on a Dutch page."""
    q = _panel([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])["quality"]
    for key in ("coverage", "grid", "gaps", "resets", "registers"):
        assert isinstance(q[key], dict) and "msgid" in q[key], f"{key} is not a message pair"


def test_panel_quality_renders_the_expected_english():
    d = _panel([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])
    q = d["quality"]
    assert _render(q["coverage"]) == "2026-01-01 → 2026-01-02   (1 day)"
    assert _render(q["grid"]) == "hourly  ·  24 intervals"
    assert _render(q["gaps"]) == "none detected"
    assert _render(q["resets"]) == "none detected"
    # T1 has data and is non-zero; T2 was never mapped.
    assert _render(q["registers"]) == "import T1 mapped, active · T2 not mapped"
    assert _render(d["summary"]) == "Home Assistant · 2 series · simulated hourly"


def test_panel_register_marks_distinguish_flat_from_active():
    """A mapped register that recorded nothing is "flat", not "active" — the §6.4 availability fact
    is what the register was mapped to AND whether it moved."""
    q = _panel([
        _energy("grid_import_t1", 2.0),
        _energy("grid_import_t2", 0.0),      # mapped but never advanced
        _energy("grid_export_t1", 0.0),
    ])["quality"]
    assert _render(q["registers"]) == "import T1 mapped, active · T2 mapped, flat"


def test_panel_resolution_label_is_a_nested_message_not_a_baked_word():
    """The resolution word is translated on its own and substituted afterwards.

    If it were interpolated as a bare string it would survive translation untouched, leaving
    "hourly" inside an otherwise-Dutch sentence — interpolation runs after the catalog lookup and
    never sees a value's msgid.
    """
    q = _panel([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])["quality"]
    res = q["grid"]["params"]["res"]
    assert isinstance(res, dict) and res["msgid"] == "hourly"


def test_panel_granularity_cells_are_messages():
    q = _panel([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0)])["quality"]
    row = q["series"][0]
    assert [_render(r) for r in row["recorded"]] == ["hourly (full)"]
    assert _render(row["uses"]) == "hourly"


def test_panel_price_warning_is_a_message_when_granularity_is_lost():
    """A 15-min price on an hourly grid is averaged down (§6.2), which fires the caveat."""
    n = HOURS * 4
    idx = (np.arange(n).astype("timedelta64[s]") * 900
           + np.datetime64("2026-01-01T00:00:00")).astype("datetime64[s]")
    price = SeriesFrame("price_spot", "price", 900, idx,
                        np.linspace(0.1, 0.4, n), np.zeros(n, dtype=QUALITY_DTYPE))
    q = _panel([_energy("grid_import_t1", 2.0), _energy("grid_export_t1", 0.0), price])["quality"]
    assert _render(q["price_warning"]) == (
        "Your prices change every 15-min but the run is hourly, so the run sees one averaged "
        "price per interval and cannot act on within-interval swings."
    )
    price_row = next(r for r in q["series"] if r["name"] == "Spot price")
    assert price_row["warn"] is True
    assert _render(price_row["uses"]) == "hourly, averaged"


def test_panel_counted_messages_pick_the_singular_at_one():
    """"1 intervals" was the shipped wording. `_msg_n` makes the count that drives the plural and
    the count printed in the text the same value, so they cannot disagree."""
    from app.data_view import _msg_n
    m = _msg_n("%(n)s interval flagged as gaps", "%(n)s intervals flagged as gaps", 1, n=1)
    assert _render(m) == "1 interval flagged as gaps"
    m2 = _msg_n("%(n)s interval flagged as gaps", "%(n)s intervals flagged as gaps", 3, n=3)
    assert _render(m2) == "3 intervals flagged as gaps"


# ── The SAMPLE view-model's messages (app/sample_data) ────────────────────────────────────────
#
# The sample is the fresh-install page: it renders through the same templates as the computed
# view-models, so it has to emit the same (msgid, params) shape. A pre-formatted string here
# would be a msgid `pybabel extract` never sees, and the sample would render English on a Dutch
# page while the live page rendered Dutch — the exact defect the pair shape exists to remove.
#
# Asserted on the rendered ENGLISH as well as the shape, because the wording IS the msgid, and
# because the sample's English is the wireframe's (specs §2.2/§2.4) and must not drift.


def test_sample_panel_quality_strings_are_message_pairs():
    q = _panel_data()["quality"]
    for key in ("coverage", "grid", "gaps", "resets", "price_warning", "load_warning"):
        assert isinstance(q[key], dict) and "msgid" in q[key], f"{key} is not a message pair"
    # `registers` is a plain marked string: it carries no runtime value, so there is nothing to
    # hold out and the whole line is one constant msgid the macro translates directly.
    assert isinstance(q["registers"], str)


def test_sample_panel_quality_renders_the_wireframe_english():
    d = _panel_data()
    q = d["quality"]
    assert _render(d["summary"]) == "Home Assistant · 5 series · simulated hourly"
    assert _render(q["coverage"]) == "2025-06-01 → 2026-07-21   (416 days)"
    assert _render(q["grid"]) == "hourly  ·  8,760 intervals"
    assert _render(q["gaps"]) == "3 gaps totalling 4.2 h  (0.04%)"
    assert _render(q["resets"]) == "2 detected and corrected"
    assert _render(q["registers"]) == "T1 ✓ mapped    T2 ✓ mapped, active"


def test_sample_granularity_cells_are_messages_with_a_nested_resolution():
    """The resolution is a WORD, so it travels as a nested message and is translated on its own.

    Passed as a bare string it would survive translation untouched — interpolation runs after the
    catalog lookup — and put "hourly" inside an otherwise-Dutch cell.
    """
    rows = _panel_data()["quality"]["series"]
    first = rows[0]
    assert [_render(r) for r in first["recorded"]] == ["hourly (full)", "5-min (last 9 days)"]
    assert _render(first["uses"]) == "hourly"
    assert first["recorded"][0]["params"]["res"]["msgid"] == "hourly"
    # The one lossy reconciliation: the whole cell is one reorderable msgid, not a glued suffix.
    price = next(r for r in rows if r["name"] == "Spot price")
    assert price["warn"] is True
    assert price["uses"]["msgid"] == "%(res)s, averaged"
    assert _render(price["uses"]) == "hourly, averaged"


def test_sample_shares_the_computed_paths_msgids_where_the_wording_matches():
    """Where sample and computed word a field identically they must use ONE msgid, not two copies.

    Two copies would be two catalog entries that can be translated differently, which is the
    drift this module's shape-compatibility claim is supposed to rule out.
    """
    from app.data_view import panel_data_from

    sample = _panel_data()
    computed = panel_data_from(_dataset([_energy("grid_import_t1", 2.0),
                                         _energy("grid_export_t1", 0.0)]))
    for key in ("coverage", "grid"):
        assert sample["quality"][key]["msgid"] == computed["quality"][key]["msgid"], key
    assert sample["summary"]["msgid"] == computed["summary"]["msgid"]
    # `resets` cannot be compared against this fixture — it has no corrected resets, so the
    # computed path returns the "none detected" branch. Compare against the branch the sample
    # is in: a dataset WITH resets, which data_view words the same way the sample does.
    reset_frame = _energy("grid_import_t1", 2.0)
    reset_frame.quality[3] = int(QualityFlags.RESET_CORRECTED)
    with_resets = panel_data_from(_dataset([reset_frame, _energy("grid_export_t1", 0.0)]))
    assert (sample["quality"]["resets"]["msgid"]
            == with_resets["quality"]["resets"]["msgid"] == "%(n)s detected and corrected")
    # The granularity cells too — same msgid, different figures.
    assert (sample["quality"]["series"][0]["recorded"][0]["msgid"]
            == computed["quality"]["series"][0]["recorded"][0]["msgid"])


def test_sample_panel_results_messages_render_the_wireframe_english():
    r = _panel_results()
    assert _render(r["period_run"]) == "simulated hourly · 8,760 intervals"
    efc = r["kpis"][2]
    assert _render(efc["delta"]) == "0.66 / day"
    assert _render(efc["extra"]) == "2,410 kWh throughput"
    # The first two tiles carry only figures — no words — so neither needs a msgid. They are no
    # longer plain strings either: a figure is formatted in the render locale (A6), and the
    # self-sufficiency comparison is a message whose two halves are figures.
    assert _render(r["kpis"][0]["value"]) == "1,412"
    assert _render(r["kpis"][0]["delta"]) == "+34.2 %"
    assert _render(r["kpis"][1]["value"]) == "31% → 52%"
    assert _render(r["kpis"][1]["delta"]) == "+21 pp"
    # …and Dutch conventions in Dutch. The wording around them is the catalog's business; these
    # two carry no words at all, so the separators are the whole assertion.
    assert _render(r["kpis"][0]["value"], locale="nl") == "1.412"
    assert _render(r["kpis"][0]["delta"], locale="nl") == "+34,2 %"


def test_sample_panel_results_percent_signs_are_real_not_fullwidth():
    """The fullwidth "％" was a workaround for the old newstyle %-formatting (app/i18n) and was
    rendering a literal ％ to the reader. A literal "%" is inert now, so these are real ones."""
    r = _panel_results()
    rendered = [_render(c) for c in r["caveats"]] + [_render(r["benchmark"]["gloss"])]
    for text in rendered:
        assert "％" not in text
    assert _render(r["caveats"][2]) == (
        "0.41% of intervals had negative reconstructed load (clamped to 0)."
    )
    assert _render(r["benchmark"]["gloss"]) == (
        "Your policy captures 71% of the grid import a perfectly-informed battery could have "
        "avoided. Allowed to export, that ceiling rises to 2,311 kWh (a 61% capture) — the "
        "extra is arbitrage your export setting currently forbids."
    )


def test_sample_caveats_are_message_pairs_like_the_computed_path():
    """`results_view.results_from` emits caveats as pairs; the template renders both through the
    same `msg()` macro, so the sample must not hand it a pre-formatted sentence."""
    for c in _panel_results()["caveats"]:
        assert isinstance(c, dict) and "msgid" in c


def test_sample_resolution_labels_are_msgids_data_view_owns():
    """`_res` passes its label as a runtime value, so extraction never sees it from sample_data.

    That is fine only because every label it is called with is one app/data_view._RES_LABELS
    `_N`-marks. A label outside that table would have no catalog entry and would render in
    English on a Dutch page — silently, since nothing else would fail.
    """
    from app.data_view import _RES_LABELS

    known = set(_RES_LABELS.values())

    def labels(m):
        """Every nested-message msgid reachable from a view-model message."""
        if not isinstance(m, dict):
            return
        for v in (m.get("params") or {}).values():
            if isinstance(v, dict) and "msgid" in v:
                yield v["msgid"]
                yield from labels(v)

    seen = set()
    for m in _walk_messages(_panel_data()) + _walk_messages(_panel_results()):
        seen.update(labels(m))
    assert seen, "no nested labels found — the walk is not reaching the messages"
    assert seen <= known, f"nested labels with no data_view msgid: {sorted(seen - known)}"


def _walk_messages(obj) -> list:
    """Every (msgid, params) pair anywhere in a view-model, at any nesting depth."""
    out = []
    if isinstance(obj, dict):
        if "msgid" in obj:
            out.append(obj)
        for v in obj.values():
            out.extend(_walk_messages(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_walk_messages(v))
    return out


def test_the_load_unreliable_warning_renders_its_figure_not_a_dict():
    """The warning must render through the real TEMPLATE, not just through `msg()`.

    `export_kwh` is a `num()` pair (A6). `_data_glance.html` rendered this one warning with a bare
    `_('…') | interpolate(export=…)`, which %-substitutes without formatting, so the page showed

        ⚠ {'num': 72.0, 'fmt': 'kwh'} was exported to the grid but your solar…

    in both locales — on the one note whose entire job is to explain a real data problem.

    Nothing caught it. The English-render diff could not: this branch needs export > import with no
    PV, which no live dataset in the tree produces, so the page never rendered it. The Dutch leakage
    scan could not either: "num"/"fmt" are not English words. And the sibling assertion above
    (`_render(note["export_kwh"]) == "72 kWh"`) passes regardless, because `_render` goes through
    `msg()` — the very step the template was skipping. So this renders the actual macro.
    """
    ds = _dataset([_energy("grid_import_t1", 1.0), _energy("grid_export_t1", 3.0)])
    summary = data_summary_from(ds)
    assert any(n["key"] == "load_unreliable" for n in summary["notes"]), "fixture no longer triggers"

    for locale in i18n.SUPPORTED:
        html = i18n.env_for(locale).from_string(
            '{% from "_data_glance.html" import data_glance with context %}'
            "{{ data_glance(data_summary) }}"
        ).render(data_summary=summary)
        assert "'num'" not in html and "&#39;num&#39;" not in html, (
            f"[{locale}] the warning rendered a raw num() dict instead of a formatted figure"
        )
        assert "72 kWh" in html or "72 kWh".replace(",", ".") in html, (
            f"[{locale}] the exported total is missing from the warning"
        )


# ── Requirements 4 and 7: no PV-related figures reach the page without PV ────────────────────
#
# These VERIFY rather than gate. The glance band and panel ③ were already data-driven — the solar
# group renders under `{% if data_summary.solar %}` and panel ③'s self-consumption row under
# `_pv_present()` — so hiding the solar SLOT (has_pv=False → no solar series fetched) should be
# enough on its own. That is a claim about behaviour nobody had asserted, and it is exactly the
# kind of claim that quietly stops being true, so it is pinned here in both locales.


def test_without_a_solar_series_the_glance_band_shows_no_solar_figures():
    """The panel-① band: no Solar group, no self-consumption, no PV caveat — in both locales.

    Rendered through the real macro rather than asserted on the view-model, because the question
    is what a reader SEES. A household with no PV also has no export, which keeps the §6.3 clamp
    quiet and leaves consumption and self-sufficiency present — those are grid-meter figures and
    must NOT disappear with the solar ones (see the consumption test below).
    """
    ds = _dataset([_energy("grid_import_t1", 1.0), _energy("grid_export_t1", 0.0)])
    summary = data_summary_from(ds)
    assert summary["solar"] is None, "no solar slot mapped, so the group must be omitted entirely"

    for locale in i18n.SUPPORTED:
        html = i18n.env_for(locale).from_string(
            '{% from "_data_glance.html" import data_glance with context %}'
            "{{ data_glance(data_summary) }}"
        ).render(data_summary=summary)
        for word in ("Solar", "Zon", "Self-consumption", "Zelfconsumptie"):
            assert word not in html, f"[{locale}] PV wording {word!r} leaked into a no-PV band"


def test_consumption_survives_without_pv():
    """Consumption is a GRID-meter figure and must not vanish with the solar ones.

    Regression guard for a plausible-looking mistake: gating the Household group on PV alongside
    the Solar group. Load reconstruction is `imp − exp + pv + …`; with no PV and no export it is
    just the import, which is perfectly reliable. Suppression is driven ONLY by the §6.3 clamp
    (`clamped_frac > CLAMP_UNRELIABLE_FRAC`), never by has_pv.
    """
    ds = _dataset([_energy("grid_import_t1", 1.0), _energy("grid_export_t1", 0.0)])
    summary = data_summary_from(ds)
    assert summary["household"]["consumption"] == {"num": float(HOURS), "fmt": "kwh"}
    assert summary["household"]["self_sufficiency"] is not None
    assert summary["notes"] == [], "a clean no-PV household should raise no data-quality note"


def test_without_a_battery_series_the_glance_band_shows_no_existing_battery_group():
    """has_battery=False → the two slots are never fetched → the group is omitted (omit-don't-zero).

    Also asserts the "net of your existing battery" captions are absent: they are driven by
    `household.net_battery`, which is False when neither battery slot is mapped.
    """
    ds = _dataset([_energy("grid_import_t1", 1.0), _energy("grid_export_t1", 0.0)])
    summary = data_summary_from(ds)
    assert summary["battery"] is None
    assert summary["household"]["net_battery"] is False

    for locale in i18n.SUPPORTED:
        html = i18n.env_for(locale).from_string(
            '{% from "_data_glance.html" import data_glance with context %}'
            "{{ data_glance(data_summary) }}"
        ).render(data_summary=summary)
        # The GROUP HEADING and the "net of…" captions, not the word "battery" on its own: the
        # self-sufficiency ⓘ legitimately mentions an existing battery while explaining the
        # formula in general terms, and asserting on the bare word would forbid that.
        for heading in ("Your existing battery", "Je bestaande batterij"):
            assert heading not in html, f"[{locale}] the battery GROUP rendered with no battery"
        for caption in ("net of your existing battery", "na aftrek van je bestaande batterij"):
            assert caption not in html, f"[{locale}] a net-of-battery caption leaked: {caption!r}"


def test_the_load_unreliable_note_does_not_blame_a_solar_sensor_that_was_never_mapped():
    """Two diagnoses, chosen by whether a solar series exists — not by `cfg.has_pv`.

    Unexplained export is equally unreliable either way, so the SUPPRESSION is unchanged; what
    changes is the advice. Telling a household that answered "no PV" to check "a solar sensor"
    names a device they just said they do not have, and the actionable reading is the opposite:
    a meter does not export what the house did not generate, so the answer is probably wrong.
    """
    no_pv = data_summary_from(_dataset([_energy("grid_import_t1", 1.0), _energy("grid_export_t1", 3.0)]))
    note = next(n for n in no_pv["notes"] if n["key"] == "load_unreliable")
    assert note["has_pv_series"] is False

    html = i18n.env_for("en").from_string(
        '{% from "_data_glance.html" import data_glance with context %}{{ data_glance(data_summary) }}'
    ).render(data_summary=no_pv)
    assert "you have not supplied any solar data" in html
    assert "a solar sensor is not reporting" not in html, "blamed a sensor that was never mapped"

    # With a solar series mapped but under-reporting, the original sensor diagnosis is right.
    with_pv = data_summary_from(_dataset([
        _energy("grid_import_t1", 1.0), _energy("grid_export_t1", 3.0),
        _energy("solar_production", 0.001),
    ]))
    note2 = next(n for n in with_pv["notes"] if n["key"] == "load_unreliable")
    assert note2["has_pv_series"] is True
    html2 = i18n.env_for("en").from_string(
        '{% from "_data_glance.html" import data_glance with context %}{{ data_glance(data_summary) }}'
    ).render(data_summary=with_pv)
    assert "a solar sensor is not reporting" in html2
