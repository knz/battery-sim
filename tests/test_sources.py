"""Unit tests for the per-slot data-source abstraction (specs §2.2, §4.3).

Covers the registry (which sources a slot offers, key lookup), the source descriptors, the
Energy-Charts runtime source's on-disk read + API bridge, and the ENTSO-E source's on-disk read
plus the extractor that produces its dataset. No network and no wall clock: the API opener is
injected (a stub, or one that fails if called), and `now` is passed explicitly so the bridge
decision is deterministic. The on-disk assertions rely on the committed CSVs in
app/data/spot_prices (NL-2024.csv hourly, NL-2026.csv 15-minute) and app/data/spot_prices_entsoe
(NL-2022.csv hourly, NL-2025.csv straddling the hourly→quarter-hourly change).

    uv run pytest tests/test_sources.py
"""

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.domain.series_vocab import SLOT_BY_NAME
from app.sources import get_source, sources_for
from app.sources.energy_charts import EnergyChartsSource, bridge_date_range
from app.sources.entsoe import EntsoeSource
from app.sources.entsoe_store import PricePointAtRes, _read_file, write_year
from app.sources.home_assistant import HomeAssistantSource

# scripts/ is not an importable package; add the repo root so the extractor can be unit-tested.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.extract_entsoe_prices import _Accumulator, parse_row  # noqa: E402

UTC = timezone.utc


def _boom_opener(url):
    """An opener that must never be called; fails the test loudly if the bridge fires."""
    raise AssertionError(f"opener called unexpectedly for {url!r}")


def _stub_opener(payload: dict):
    """Return a str->bytes opener yielding `payload` as JSON, matching the API's shape."""

    def opener(url):
        return json.dumps(payload).encode("utf-8")

    return opener


# --- registry: which sources a slot offers -------------------------------------------------

def test_price_spot_offers_ha_then_both_preset_sources():
    # Registration order: HA leads, then the two independent NL day-ahead origins.
    descriptors = sources_for(SLOT_BY_NAME["price_spot"])
    assert [d.key for d in descriptors] == ["home_assistant", "energy_charts", "entsoe_nl"]


def test_energy_slot_offers_ha_only():
    descriptors = sources_for(SLOT_BY_NAME["grid_import_t1"])
    assert [d.key for d in descriptors] == ["home_assistant"]


# --- registry: key lookup ------------------------------------------------------------------

def test_get_source_by_key():
    assert isinstance(get_source("energy_charts"), EnergyChartsSource)
    assert isinstance(get_source("home_assistant"), HomeAssistantSource)
    assert isinstance(get_source("entsoe_nl"), EntsoeSource)


def test_get_source_unknown_key_raises():
    with pytest.raises(ValueError):
        get_source("nope")


# --- Home Assistant source: descriptor + no backend load -----------------------------------

def test_home_assistant_descriptor():
    d = HomeAssistantSource().descriptor
    assert d.key == "home_assistant"
    assert d.kind == "browser_fetch"


def test_home_assistant_load_raises():
    src = HomeAssistantSource()
    with pytest.raises(NotImplementedError):
        src.load(SLOT_BY_NAME["grid_import_t1"], (datetime(2024, 1, 1, tzinfo=UTC),
                                                  datetime(2024, 1, 2, tzinfo=UTC)))


# --- bridge-window arithmetic (pure) -------------------------------------------------------

def test_bridge_none_when_window_within_disk():
    last = datetime(2026, 7, 24, 21, 45, tzinfo=UTC)
    end = datetime(2026, 3, 5, tzinfo=UTC)  # before last on-disk
    assert bridge_date_range(last, end, now=datetime(2026, 7, 24, tzinfo=UTC)) is None


def test_bridge_none_when_no_disk_data():
    assert bridge_date_range(None, datetime(2026, 8, 1, tzinfo=UTC),
                             now=datetime(2026, 8, 1, tzinfo=UTC)) is None


def test_bridge_from_last_disk_day_to_window_end():
    last = datetime(2026, 7, 24, 21, 45, tzinfo=UTC)
    end = datetime(2026, 7, 27, tzinfo=UTC)
    now = datetime(2026, 7, 27, 12, tzinfo=UTC)
    assert bridge_date_range(last, end, now=now) == (date(2026, 7, 24), date(2026, 7, 27))


def test_bridge_caps_tail_at_now():
    # Window asks past today; the API cannot serve the future, so `now` caps the `to` date.
    last = datetime(2026, 7, 24, 21, 45, tzinfo=UTC)
    end = datetime(2026, 8, 10, tzinfo=UTC)
    now = datetime(2026, 7, 26, tzinfo=UTC)
    assert bridge_date_range(last, end, now=now) == (date(2026, 7, 24), date(2026, 7, 26))


# --- Energy-Charts load: window fully inside committed data ---------------------------------

def test_load_within_committed_data_no_bridge():
    src = EnergyChartsSource()
    window = (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 5, tzinfo=UTC))
    frame = src.load(SLOT_BY_NAME["price_spot"], window,
                     opener=_boom_opener, now=datetime(2026, 7, 24, tzinfo=UTC))
    assert frame.kind == "price"
    assert frame.name == "price_spot"
    assert frame.resolution_s == 3600
    # 4 days hourly, half-open [2024-03-01, 2024-03-05) → 96 intervals.
    assert len(frame.index) == 96
    # NL 2024 spot prices are a few cents/kWh; sanity-bound them well away from EUR/MWh.
    assert 0.0 <= frame.values.min() and frame.values.max() < 1.0


# --- Energy-Charts load: window tail past last_on_disk triggers the bridge ------------------

def test_load_bridges_past_last_on_disk():
    src = EnergyChartsSource()
    # Committed tail is 2026-07-24T21:45Z; ask through 2026-07-26, bridging the gap.
    window = (datetime(2026, 7, 24, tzinfo=UTC), datetime(2026, 7, 26, tzinfo=UTC))
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)

    # Hand-built bridge payload: two hourly points on 2026-07-25, after the committed tail and
    # inside the window. Raw dict shape parse_price_response expects (EUR/MWh, unix_seconds).
    t0 = int(datetime(2026, 7, 25, 0, 0, tzinfo=UTC).timestamp())
    t1 = int(datetime(2026, 7, 25, 1, 0, tzinfo=UTC).timestamp())
    payload = {
        "unix_seconds": [t0, t1],
        "price": [50.0, 60.0],  # EUR/MWh → 0.05, 0.06 EUR/kWh after conversion
        "unit": "EUR / MWh",
    }
    called = {"n": 0}

    def counting_opener(url):
        called["n"] += 1
        return json.dumps(payload).encode("utf-8")

    frame = src.load(SLOT_BY_NAME["price_spot"], window, opener=counting_opener, now=now)

    assert called["n"] == 1  # the bridge fired
    starts = set(frame.index.astype("datetime64[s]").astype("int64").tolist())
    # An on-disk 15-minute interval from 2026-07-24 is present...
    on_disk_ts = int(datetime(2026, 7, 24, 0, 0, tzinfo=UTC).timestamp())
    assert on_disk_ts in starts
    # ...and both bridged 2026-07-25 intervals are present.
    assert t0 in starts and t1 in starts
    # The bridged prices came through unit-converted (EUR/MWh → EUR/kWh).
    pos = frame.index.astype("datetime64[s]").astype("int64").tolist().index(t0)
    assert abs(frame.values[pos] - 0.05) < 1e-9


def test_load_before_committed_data_is_empty():
    # Window entirely before 2023 (no committed data), API returns nothing → empty frame.
    src = EnergyChartsSource()
    window = (datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 2, tzinfo=UTC))
    frame = src.load(SLOT_BY_NAME["price_spot"], window,
                     opener=_stub_opener({"unix_seconds": [], "price": []}),
                     now=datetime(2026, 7, 24, tzinfo=UTC))
    assert len(frame.index) == 0
    assert frame.resolution_s is None


# --- ENTSO-E extractor: row parsing ---------------------------------------------------------

def _raw(dt="2024-03-01 00:00:00", res="PT60M", area="NL", atype="BZN",
         contract="Day-ahead", price="123.45", currency="EUR"):
    """One raw ENTSO-E record as the tab-split field list parse_row expects."""
    return ["hash", dt, res, "10YNL----------L", "Netherlands (NL)", atype, area,
            contract, " ", price, currency, "2024-10-03 13:37:47"]


def test_parse_row_converts_units_and_resolution():
    start, resolution_s, price = parse_row(_raw(price="123.45"))
    assert start == datetime(2024, 3, 1, tzinfo=UTC)
    assert resolution_s == 3600
    assert abs(price - 0.12345) < 1e-12  # EUR/MWh → EUR/kWh


def test_parse_row_reads_quarter_hourly():
    _, resolution_s, _ = parse_row(_raw(dt="2025-10-01 00:15:00", res="PT15M"))
    assert resolution_s == 900


@pytest.mark.parametrize("kwargs", [
    {"area": "DE"},           # another bidding zone
    {"atype": "CTA"},         # NL control area, not the bidding zone
    {"contract": "Intraday"},  # not day-ahead
    {"currency": "GBP"},      # not euro
])
def test_parse_row_skips_other_series(kwargs):
    assert parse_row(_raw(**kwargs)) is None


def test_parse_row_skips_short_row():
    assert parse_row(["hash", "2024-03-01 00:00:00"]) is None


def test_parse_row_rejects_unknown_resolution():
    # A row that *is* ours but carries an unparseable field is a data surprise, not a skip.
    with pytest.raises(ValueError):
        parse_row(_raw(res="PT5M"))


def test_parse_row_rejects_non_numeric_price():
    with pytest.raises(ValueError):
        parse_row(_raw(price="n/a"))


# --- ENTSO-E extractor: finest-granularity collision rule -----------------------------------

def test_accumulator_prefers_finest_resolution():
    # The rule the user asked for: when one interval start is claimed at two resolutions, the
    # finer one wins regardless of the order the rows arrive in.
    start = datetime(2025, 9, 30, 22, tzinfo=UTC)
    for order in ([(3600, 0.10), (900, 0.20)], [(900, 0.20), (3600, 0.10)]):
        acc = _Accumulator()
        for resolution_s, price in order:
            acc.add(start, resolution_s, price)
        points = acc.by_year()[2025]
        assert [(p.resolution_s, p.price_eur_kwh) for p in points] == [(900, 0.20)]
        assert acc.collisions == 1


def test_accumulator_same_resolution_repeat_keeps_later():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    acc = _Accumulator()
    acc.add(start, 3600, 0.10)
    acc.add(start, 3600, 0.20)  # a revised price for an interval already seen
    assert acc.by_year()[2024][0].price_eur_kwh == 0.20


def test_accumulator_groups_by_year_sorted():
    acc = _Accumulator()
    acc.add(datetime(2025, 1, 1, 5, tzinfo=UTC), 3600, 0.3)
    acc.add(datetime(2024, 6, 1, tzinfo=UTC), 3600, 0.1)
    acc.add(datetime(2025, 1, 1, 2, tzinfo=UTC), 3600, 0.2)
    years = acc.by_year()
    assert sorted(years) == [2024, 2025]
    assert [p.start.hour for p in years[2025]] == [2, 5]  # sorted within the year


# --- ENTSO-E store: three-column round-trip -------------------------------------------------

def test_store_round_trip_preserves_per_row_resolution(tmp_path):
    points = [
        PricePointAtRes(datetime(2025, 9, 30, 21, tzinfo=UTC), 0.09, 3600),
        PricePointAtRes(datetime(2025, 9, 30, 22, tzinfo=UTC), 0.10255, 900),
        PricePointAtRes(datetime(2025, 9, 30, 22, 15, tzinfo=UTC), 0.09217, 900),
    ]
    written = write_year(2025, points, out_dir=tmp_path)
    assert written == 3
    back = _read_file(tmp_path / "NL-2025.csv")
    assert [p.resolution_s for p in back] == [3600, 900, 900]
    assert [p.start for p in back] == [p.start for p in points]
    assert abs(back[1].price_eur_kwh - 0.10255) < 1e-9


def test_store_write_year_filters_to_year(tmp_path):
    points = [
        PricePointAtRes(datetime(2024, 12, 31, 23, tzinfo=UTC), 0.1, 3600),
        PricePointAtRes(datetime(2025, 1, 1, 0, tzinfo=UTC), 0.2, 3600),
    ]
    assert write_year(2025, points, out_dir=tmp_path) == 1
    assert len(_read_file(tmp_path / "NL-2025.csv")) == 1


def test_store_rejects_unsafe_bzn(tmp_path):
    with pytest.raises(ValueError):
        write_year(2025, [], bzn="../../etc", out_dir=tmp_path)


def test_store_rejects_wrong_header(tmp_path):
    # A two-column file (the *other* dataset's format) must not be read as this one.
    path = tmp_path / "NL-2025.csv"
    path.write_text("timestamp,price_eur_kwh\n2025-01-01T00:00:00+00:00,0.1\n")
    with pytest.raises(ValueError):
        _read_file(path)


# --- ENTSO-E source: descriptor + on-disk load -----------------------------------------------

def test_entsoe_descriptor():
    d = EntsoeSource().descriptor
    assert d.key == "entsoe_nl"
    assert d.kind == "backend_load"


def test_entsoe_load_hourly_window():
    # 2022 is hourly throughout, and is coverage the Energy-Charts dataset (2023→) does not have.
    frame = EntsoeSource().load(
        SLOT_BY_NAME["price_spot"],
        (datetime(2022, 8, 1, tzinfo=UTC), datetime(2022, 8, 5, tzinfo=UTC)),
    )
    assert frame.kind == "price"
    assert frame.name == "price_spot"
    assert frame.resolution_s == 3600
    assert len(frame.index) == 96  # 4 days hourly, half-open
    # NL spot prices are euro-per-kWh here; 2022 was expensive but still well under 1 EUR/kWh.
    assert 0.0 <= frame.values.min() and frame.values.max() < 1.0


def test_entsoe_load_quarter_hourly_window():
    frame = EntsoeSource().load(
        SLOT_BY_NAME["price_spot"],
        (datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC)),
    )
    assert frame.resolution_s == 900
    assert len(frame.index) == 96  # 1 day quarter-hourly


def test_entsoe_load_outside_coverage_is_empty():
    # Before the raw corpus begins (2022-07); no bridge exists, so this is simply empty.
    frame = EntsoeSource().load(
        SLOT_BY_NAME["price_spot"],
        (datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 2, tzinfo=UTC)),
    )
    assert len(frame.index) == 0
    assert frame.resolution_s is None


def test_entsoe_load_across_resolution_change():
    """A window straddling the 2025-09-30 switchover yields both regimes' intervals.

    Documents the known limitation: the frame carries a single modal `resolution_s` even though
    the window genuinely mixes hourly and quarter-hourly intervals. The per-interval truth is
    preserved on disk (entsoe_store's resolution_s column) for the specs §6.2 grid selector.
    """
    window = (datetime(2025, 9, 30, 20, tzinfo=UTC), datetime(2025, 10, 1, tzinfo=UTC))
    frame = EntsoeSource().load(SLOT_BY_NAME["price_spot"], window)
    # 2 hourly intervals (20:00, 21:00) + 8 quarter-hourly (22:00 … 23:45).
    assert len(frame.index) == 10
    # The on-disk rows for this window do carry both native resolutions.
    from app.sources import entsoe_store
    resolutions = {p.resolution_s for p in entsoe_store.load_range(*window)}
    assert resolutions == {3600, 900}
