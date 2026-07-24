"""The preset historical spot-price source — Energy-Charts NL, on-disk + bridge (specs §4.3).

The one backend_load source in this increment. It fills the `price_spot` slot with NL day-ahead
spot prices without any browser round-trip: it reads the committed on-disk dataset
(price_store, app/data/spot_prices/NL-YYYY.csv, 2023→a recent tail) and, when the requested
window extends past the last committed interval, bridges the gap by calling the public
Energy-Charts API (energy_charts_api.fetch_prices) for just those tail days.

The merged points are converted to ingest.PriceRow and fed through ingest.price_frame — the same
normaliser the HA price path uses — so the resulting SeriesFrame's shape, resolution inference,
and price kind match the HA path exactly (specs §4.3). This source owns only *where the points
come from*, not how a price frame is built.

Purity/testability: `load` accepts an injected `opener` (threaded to fetch_prices so tests stub
the network) and an injected `now` (so the bridge decision is deterministic — no wall clock in
the domain path a test exercises). The bridge-window arithmetic is `bridge_date_range`, a pure
function tested directly.

Main items:
    DEFAULT_BZN                         the only bidding zone we serve (NL).
    bridge_date_range(last, end, now)   pure: the (from, to) dates to fetch, or None if no bridge.
    EnergyChartsSource                  the DataSource impl for the price_spot slot.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.domain.frames import SeriesFrame
from app.domain.series_vocab import SlotSpec
from app.sources import energy_charts_api, price_store
from app.sources.base import SourceDescriptor
from app.sources.energy_charts_api import BZN_NL, PricePoint
from app.domain import ingest

# The only slot this source fills: NL day-ahead spot price (specs §4.1). It is a single price
# series; it does not supply energy meters, nor the intra-interval min/max bracket slots
# (price_spot_min/max come from an HA measurement statistic's own min/max, not from this API).
_PRICE_SPOT_SLOT_NAME = "price_spot"

# The bidding zone this source serves. The dataset and API are NL-only in this increment.
DEFAULT_BZN = BZN_NL

# Milliseconds per second — PricePoint starts are tz-aware datetimes; ingest.PriceRow wants an
# epoch-millisecond start (its rows model HA statistics, which are ms epochs). Named so the
# unit conversion is explicit rather than an inline 1000 (specs §5.6).
_MS_PER_S = 1000

# Stable descriptor for the drawer. `key` is persisted with the slot's chosen source and must
# not change once shipped (specs §2.2).
_DESCRIPTOR = SourceDescriptor(
    key="energy_charts",
    label="Preset historical (Energy-Charts NL)",
    kind="backend_load",
    blurb=(
        "NL day-ahead spot prices from 2023 to today: committed on disk and bridged live "
        "to the end of your selected range."
    ),
)


def bridge_date_range(
    last_on_disk: datetime | None,
    window_end: datetime,
    now: datetime,
) -> tuple[date, date] | None:
    """The calendar (from, to) date range to fetch from the API to bridge to `window_end`.

    Returns `None` when no bridge is needed: either there is no committed data at all (nothing to
    bridge from — the window is then served entirely from disk or is empty), or `window_end` is
    at/before the last committed interval (the window is fully covered on disk).

    When a bridge is needed, `from` is the calendar date of the last on-disk interval (the API is
    day-granular and inclusive, so re-fetching the last committed day fills the rest of that day
    and dedup drops the overlap), and `to` is the earlier of `window_end`'s date and today's
    date — the API cannot serve the future, so `now` caps the tail (specs §4.3). All datetimes
    are treated as UTC.
    """
    if last_on_disk is None:
        return None
    last = last_on_disk.astimezone(timezone.utc)
    end = window_end.astimezone(timezone.utc)
    if end <= last:
        return None
    from_date = last.date()
    # The API cannot return prices past today; cap the fetch tail at `now` so a window ending in
    # the future does not ask for data that does not exist.
    to_date = min(end.date(), now.astimezone(timezone.utc).date())
    if to_date < from_date:
        return None
    return from_date, to_date


class EnergyChartsSource:
    """DataSource for the preset NL spot-price dataset (on-disk + API bridge, specs §4.3)."""

    @property
    def descriptor(self) -> SourceDescriptor:
        return _DESCRIPTOR

    def available_for(self, slot: SlotSpec) -> bool:
        """True only for the price_spot slot: this is the NL day-ahead spot price and nothing else.

        It does not fill energy slots, nor the price_spot_min/price_spot_max bracket slots (those
        are an HA measurement statistic's intra-interval min/max, not something this API provides).
        """
        return slot.name == _PRICE_SPOT_SLOT_NAME

    def load(
        self,
        slot: SlotSpec,
        window: tuple[datetime, datetime],
        *,
        opener=None,
        now: datetime | None = None,
    ) -> SeriesFrame:
        """Load NL spot prices over `window` = (start, end), tz-aware UTC (specs §4.3).

        Reads committed points from disk, then bridges any tail past the last committed interval
        by fetching just those days from the API. The merged points are normalised through
        ingest.price_frame — the same path the HA price series uses — so the frame shape matches.

        `opener` is threaded to energy_charts_api.fetch_prices so tests stub the network; when
        None the API's default urllib opener is used. `now` (default: datetime.now(UTC)) bounds
        the bridge so the domain path stays deterministic under test — no wall clock is read when
        a caller supplies it.

        Merge policy: on-disk points are authoritative for committed intervals and API points for
        the bridge tail; where the re-fetched last on-disk day overlaps, the on-disk value wins
        (committed data is the reviewable source of truth). If the window is entirely before the
        committed data and the API returns nothing, the result is an empty (zero-row) SeriesFrame
        — ingest.price_frame handles an empty row list and yields resolution_s=None.

        Mixed native resolution (known limitation): the committed NL dataset is hourly for older
        years and 15-minute once the market moved to quarter-hourly (around 2025-09-30). For a
        window that straddles that change, ingest.price_frame stamps a single `resolution_s` (the
        modal spacing), which is not authoritative per-interval and can flip with where the window
        is cut. There is no downstream consumer of this frame's resolution yet; the simulation
        grid selector (specs §6.2) is where a genuine two-resolution split will be handled, the
        same way the HA hourly/5-minute pair is (specs §4.3). Tracked as a follow-up, not resolved
        here.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        start, end = window

        on_disk = price_store.load_range(start, end, bzn=DEFAULT_BZN)

        bridge_points: list[PricePoint] = []
        span = bridge_date_range(price_store.last_on_disk(bzn=DEFAULT_BZN), end, now)
        if span is not None:
            from_date, to_date = span
            fetch_kwargs = {} if opener is None else {"opener": opener}
            fetched = energy_charts_api.fetch_prices(
                from_date, to_date, bzn=DEFAULT_BZN, **fetch_kwargs
            )
            # Keep only fetched points inside the requested half-open window. The on-disk/API
            # overlap is not resolved here but in _merge, which keeps the on-disk value for any
            # start present in both — so a re-fetched committed day is safely superseded there.
            bridge_points = [p for p in fetched if start <= p.start < end]

        merged = self._merge(on_disk, bridge_points)
        rows = [
            ingest.PriceRow(
                start_ms=int(p.start.timestamp() * _MS_PER_S),
                mean=p.price_eur_kwh,
                min=None,
                max=None,
            )
            for p in merged
        ]
        return ingest.price_frame(_PRICE_SPOT_SLOT_NAME, rows)

    @staticmethod
    def _merge(on_disk: list[PricePoint], bridge: list[PricePoint]) -> list[PricePoint]:
        """Combine on-disk and bridge points, deduped by start with on-disk authoritative.

        Committed data is the reviewable source of truth, so for any interval start present in
        both, the on-disk price is kept and the bridged one dropped. The result is sorted by start
        (ingest.price_frame sorts too, but a sorted input keeps the merge intent legible).
        """
        by_start: dict[datetime, PricePoint] = {}
        for p in bridge:
            by_start[p.start] = p
        for p in on_disk:  # on-disk written last → wins on overlap
            by_start[p.start] = p
        return sorted(by_start.values(), key=lambda p: p.start)
