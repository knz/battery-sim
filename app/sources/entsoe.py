"""The alternate historical spot-price source — ENTSO-E NL, on-disk only (specs §4.3).

A second backend_load source for the `price_spot` slot, beside EnergyChartsSource. Both fill the
same slot with NL day-ahead spot prices from independent origins, so a run can be repeated
against either and the two compared:

  * energy_charts.py — the Energy-Charts API, committed 2023→recent plus a live bridge to `now`.
  * this module     — the ENTSO-E transparency-platform dumps, committed 2022→the extract date.

Two differences follow from the origin. First, coverage starts in mid-2022 rather than 2023, so
this source reaches further back. Second, there is **no live bridge**: the raw corpus in
external_data/entso-e/ is a static set of monthly dumps with no endpoint behind it, so a window
extending past the last extracted interval simply yields the rows that exist. Extending coverage
means adding raw dumps and re-running scripts/extract_entsoe_prices.py.

Points are read via entsoe_store and converted to ingest.PriceRow, then normalised through
ingest.price_frame — the same path the HA and Energy-Charts price series use — so the resulting
SeriesFrame's shape and price kind match those exactly. This source owns only *where the points
come from*, not how a price frame is built.

Main items:
    DEFAULT_BZN     the only bidding zone we serve (NL).
    EntsoeSource    the DataSource impl for the price_spot slot.
"""

from __future__ import annotations

from datetime import datetime

from app.domain import ingest
from app.domain.frames import SeriesFrame
from app.domain.series_vocab import SlotSpec
from app.sources import entsoe_store
from app.sources.base import SourceDescriptor

# The only slot this source fills: NL day-ahead spot price (specs §4.1). It is a single price
# series; it does not supply energy meters. A day-ahead series has one cleared price per
# interval and no spread within it, so §6.16's intra-hour bracket comes from the interval
# spacing of THIS series (simframe `_resample_price_stats`), not from anything extra here.
_PRICE_SPOT_SLOT_NAME = "price_spot"

# The bidding zone this source serves. The extracted dataset is NL-only.
DEFAULT_BZN = "NL"

# Milliseconds per second — points carry tz-aware datetimes; ingest.PriceRow wants an epoch-
# millisecond start (its rows model HA statistics, which are ms epochs). Named so the unit
# conversion is explicit rather than an inline 1000 (specs §5.6).
_MS_PER_S = 1000

# Stable descriptor for the drawer. `key` is persisted with the slot's chosen source and must not
# change once shipped (specs §2.2).
_DESCRIPTOR = SourceDescriptor(
    key="entsoe_nl",
    label="Preset historical (ENTSO-E NL)",
    kind="backend_load",
    blurb=(
        "NL day-ahead spot prices from mid-2022, extracted from the ENTSO-E transparency "
        "platform at their native hourly then quarter-hourly resolution."
    ),
)


class EntsoeSource:
    """DataSource for the extracted ENTSO-E NL spot-price dataset (on-disk only, specs §4.3)."""

    @property
    def descriptor(self) -> SourceDescriptor:
        return _DESCRIPTOR

    def available_for(self, slot: SlotSpec) -> bool:
        """True only for the price_spot slot: this is the NL day-ahead spot price and nothing else.

        It does not fill energy slots. There is no separate bracket slot to fill either: the
        §6.16 bracket is derived from this series' own interval spacing.
        """
        return slot.name == _PRICE_SPOT_SLOT_NAME

    def load(self, slot: SlotSpec, window: tuple[datetime, datetime]) -> SeriesFrame:
        """Load NL spot prices over `window` = (start, end), tz-aware UTC (specs §4.3).

        Reads the committed extract and normalises it through ingest.price_frame, the same path
        the HA price series uses, so the frame shape matches. No network and no wall clock are
        involved: unlike EnergyChartsSource there is nothing to bridge to, so this needs neither
        an injected `opener` nor an injected `now` to stay deterministic under test.

        A window outside the extracted coverage — before mid-2022, or past the last extracted
        interval — yields only the rows that exist, and an entirely-outside window yields an empty
        (zero-row) SeriesFrame; ingest.price_frame handles an empty row list and yields
        resolution_s=None.

        Mixed native resolution (known limitation, shared with EnergyChartsSource): the dataset is
        hourly before 2025-09-30 22:00 UTC and quarter-hourly after. The on-disk `resolution_s`
        column records each interval's true length, but ingest.price_frame stamps a single
        `resolution_s` per frame (the modal spacing), so for a window straddling that change the
        frame's value is not authoritative per interval and can flip with where the window is cut.
        The per-row truth is preserved on disk for the simulation grid selector (specs §6.2) to
        use, which is where a genuine two-resolution split belongs — the same way the HA
        hourly/5-minute pair is handled (specs §4.3). Tracked as a follow-up, not resolved here.
        """
        start, end = window
        points = entsoe_store.load_range(start, end, bzn=DEFAULT_BZN)
        rows = [
            ingest.PriceRow(
                start_ms=int(p.start.timestamp() * _MS_PER_S),
                mean=p.price_eur_kwh,
            )
            for p in points
        ]
        return ingest.price_frame(_PRICE_SPOT_SLOT_NAME, rows)
