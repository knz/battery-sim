"""The normalised per-series representation — `SeriesFrame` and `QualityFlags` (specs §4.4).

After ingest, every input series (a meter register, a price, a power reading) becomes one
`SeriesFrame`: a UTC, interval-start, left-closed datetime index; a numpy value array (kWh in
the interval for energy, EUR/kWh valid-from for price); the series' *native* resolution; and a
per-interval quality bitfield. The simulation later reconciles many of these onto one grid
(docs/specs/07-internal-representation.md §4.4 `SimulationFrame`), but that is a later increment —
this module is only the per-series frame that the data-import path produces.

`resolution_s` is the spacing at which the series was actually recorded, before any
reconciliation. `None` means irregular (specs §4.4, open question §8.20).

Main items:
    QualityFlags   IntFlag bitfield: OK, GAP_FILLED, RESET_CORRECTED, INTERPOLATED,
                   RESAMPLED_DOWN, CLAMPED_NEGATIVE (specs §4.4).
    SeriesKind     Literal["energy", "price"] — the two kinds a SeriesFrame carries.
    SeriesFrame    the value object above; `.coverage()` and `.covers()` helpers for §6.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntFlag
from typing import Literal

import numpy as np

SeriesKind = Literal["energy", "price"]


class QualityFlags(IntFlag):
    """Per-interval quality bitfield (docs/specs/07-internal-representation.md §4.4).

    Stored as one uint16 per interval alongside the values. `OK` is the zero value so an
    untouched interval carries no set bits. The remaining bits record what ingest did to an
    interval, and each is raised exactly where the spec says: `RESET_CORRECTED` in §6.1,
    `GAP_FILLED`/`INTERPOLATED` in gap handling, `RESAMPLED_DOWN` at grid reconciliation,
    `CLAMPED_NEGATIVE` in load reconstruction (§6.3, a later increment).
    """

    OK = 0
    GAP_FILLED = 1 << 0
    RESET_CORRECTED = 1 << 1
    INTERPOLATED = 1 << 2
    RESAMPLED_DOWN = 1 << 3
    CLAMPED_NEGATIVE = 1 << 4


# numpy dtype for the per-interval quality array. uint16 matches SimulationFrame.quality in
# §4.4 and leaves room for bits beyond the six defined above.
QUALITY_DTYPE = np.uint16


@dataclass
class SeriesFrame:
    """One ingested series, normalised (docs/specs/07-internal-representation.md §4.4).

    Fields mirror the spec's `SeriesFrame` exactly:
        name          the internal series name (specs §4.1 vocabulary), e.g. "grid_import_t1".
        kind          "energy" (kWh per interval) or "price" (EUR/kWh valid-from).
        resolution_s  native spacing in seconds; None if irregular.
        index         np.datetime64[s] array, UTC, interval START, left-closed.
        values        float64; energy: kWh in the interval; price: EUR/kWh valid from the start.
        quality       uint16 per-interval bitfield (QualityFlags).

    A price frame carries no intra-interval bracket. It used to ride along here, taken from an HA
    `measurement` statistic's own min/max, but nothing ever read it: the §6.16 bracket is DERIVED
    at grid reconciliation from the 15-minute values themselves (`simframe._resample_price_stats`),
    which gives one definition of the quantity independent of the source.
    """

    name: str
    kind: SeriesKind
    resolution_s: int | None
    index: np.ndarray
    values: np.ndarray
    quality: np.ndarray
    # A finer native copy of the same series over part of the window (specs §4.3): on the HA
    # path, the 5-minute trailing window alongside the full-window hourly data. It stays part of
    # THIS series (not a second row), and powers the resolution-bias diagnostic (§6.13) even when
    # the run is hourly. Only its resolution and coverage are retained here; the fine values are
    # not persisted in this increment (no consumer yet). Reported as fine_resolution_s /
    # fine_coverage in the result object's `series` block (§4.5).
    fine_resolution_s: int | None = None
    fine_coverage: tuple[datetime, datetime] | None = None
    # The Home Assistant statistic id this series was fetched from (specs §2.2). Carried so the
    # source picker can render a fetched HA slot's entity after a reload; None for non-HA sources
    # (e.g. the energy_charts backend load) and for series built without one. Not secret — only the
    # token is browser-local (§7.5) — so it is persisted in series_meta.
    stat_id: str | None = None

    def __post_init__(self) -> None:
        n = len(self.index)
        if len(self.values) != n or len(self.quality) != n:
            raise ValueError(
                f"SeriesFrame {self.name!r}: index/values/quality length mismatch "
                f"({n}/{len(self.values)}/{len(self.quality)})"
            )

    def coverage(self) -> tuple[datetime, datetime] | None:
        """(start, end) as tz-aware UTC datetimes, or None if the series is empty.

        `start` is the first interval's start; `end` is the last interval's start plus one
        native resolution, i.e. the exclusive end of the covered window. With an irregular
        series (`resolution_s is None`) `end` is the last interval's start, since the trailing
        interval's length is unknown.
        """
        if len(self.index) == 0:
            return None
        start = _to_utc(self.index[0])
        last = _to_utc(self.index[-1])
        if self.resolution_s is not None:
            end = last + np.timedelta64(self.resolution_s, "s").astype("timedelta64[us]").tolist()  # type: ignore[assignment]
        else:
            end = last
        return start, end

    def covers(self, window: tuple[datetime, datetime]) -> bool:
        """True if this series' coverage spans the whole requested window (specs §6.2)."""
        cov = self.coverage()
        if cov is None:
            return False
        return cov[0] <= window[0] and cov[1] >= window[1]


def _to_utc(ts64: np.datetime64) -> datetime:
    """Convert a numpy datetime64 (assumed UTC) to a tz-aware Python datetime."""
    # datetime64 has no tz; the whole pipeline holds UTC (specs §4.4), so attach it here.
    py = ts64.astype("datetime64[us]").astype(datetime)
    return py.replace(tzinfo=timezone.utc)
