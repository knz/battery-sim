"""Unit tests for the per-slot data-source abstraction (specs §2.2, §4.3).

Covers the registry (which sources a slot offers, key lookup), the two source descriptors, and
the Energy-Charts runtime source's on-disk read + API bridge. No network and no wall clock: the
API opener is injected (a stub, or one that fails if called), and `now` is passed explicitly so
the bridge decision is deterministic. The on-disk assertions rely on the committed CSVs in
app/data/spot_prices (NL-2024.csv hourly, NL-2026.csv 15-minute).

    uv run pytest tests/test_sources.py
"""

import json
from datetime import date, datetime, timezone

import pytest

from app.domain.series_vocab import SLOT_BY_NAME
from app.sources import get_source, sources_for
from app.sources.energy_charts import EnergyChartsSource, bridge_date_range
from app.sources.home_assistant import HomeAssistantSource

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

def test_price_spot_offers_ha_then_energy_charts():
    descriptors = sources_for(SLOT_BY_NAME["price_spot"])
    assert [d.key for d in descriptors] == ["home_assistant", "energy_charts"]


def test_energy_slot_offers_ha_only():
    descriptors = sources_for(SLOT_BY_NAME["grid_import_t1"])
    assert [d.key for d in descriptors] == ["home_assistant"]


def test_bracket_slot_offers_ha_only():
    # price_spot_min is an HA measurement stat's own min, not something Energy-Charts provides.
    descriptors = sources_for(SLOT_BY_NAME["price_spot_min"])
    assert [d.key for d in descriptors] == ["home_assistant"]


# --- registry: key lookup ------------------------------------------------------------------

def test_get_source_by_key():
    assert isinstance(get_source("energy_charts"), EnergyChartsSource)
    assert isinstance(get_source("home_assistant"), HomeAssistantSource)


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
