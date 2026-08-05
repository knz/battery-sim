"""On-disk committed spot-price dataset: yearly CSV read/write (spot-price backend source).

The spot-price source ships with historical NL day-ahead prices committed to the repository
(app/data/spot_prices/NL-YYYY.csv), so a first run needs no network for anything but the recent
tail. This module is the single reader/writer of that on-disk format, shared by:

  * scripts/fetch_spot_prices.py — writes/refreshes the yearly files from the API.
  * app/sources/energy_charts.py — reads them at runtime, then bridges the gap to `now`.

Format (chosen for reviewability over the .npz series store, per the data-format decision):
one CSV per calendar year, two columns, header `timestamp,price_eur_kwh`. `timestamp` is an
ISO-8601 UTC instant (interval start, e.g. `2024-01-01T00:00:00+00:00`); `price_eur_kwh` is the
already-unit-converted price. One row per native interval — hourly for older years, 15-minute
for recent ones — preserved as fetched, never resampled here (specs §4.3, §6.2 owns resampling).

Rows are kept sorted and de-duplicated by timestamp on write, so a refresh that re-fetches an
overlapping tail does not double-write an interval.

Main items:
    PRICE_DATA_DIR                 app/data/spot_prices, the committed dataset root.
    year_path(year, bzn)           the CSV path for one year.
    write_year(year, points, bzn)  (over)write one yearly file from PricePoints.
    load_range(start, end, bzn)    read committed points overlapping [start, end).
    last_on_disk(bzn)              the latest committed interval start, or None if no data.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from app.sources.energy_charts_api import BZN_NL, PricePoint

# The committed dataset lives beside the code (app/data/), not under the runtime data_dir: it
# is shipped content, versioned with the app, not per-workspace user data. __file__ is
# app/sources/price_store.py, so parent.parent is the app/ package root.
PRICE_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "spot_prices"

_HEADER = ("timestamp", "price_eur_kwh")


def _safe_bzn(bzn: str) -> str:
    """Reject a bidding zone that is not a plain alphanumeric code.

    `bzn` is interpolated into filenames and a glob, so a value like `../../etc` would escape
    PRICE_DATA_DIR. At runtime `bzn` is always the `NL` constant, but the seed script exposes it
    as a CLI flag, so guard it here rather than trust the caller (specs §5.5 path-traversal rule).
    """
    if not bzn.isalnum():
        raise ValueError(f"unsafe bidding-zone code: {bzn!r}")
    return bzn


def year_path(year: int, bzn: str = BZN_NL) -> Path:
    """The CSV path for one bidding zone and year, e.g. `.../NL-2024.csv`."""
    return PRICE_DATA_DIR / f"{_safe_bzn(bzn)}-{year}.csv"


def write_year(year: int, points: list[PricePoint], bzn: str = BZN_NL) -> int:
    """(Over)write one yearly CSV from `points`, sorted and de-duplicated by timestamp.

    Only points whose start falls in `year` (UTC) are written; a caller may pass a mixed list
    and this keeps the right ones. Returns the number of rows written. Creates the data dir if
    missing. An empty result still writes a header-only file so a year with no data is explicit.
    """
    PRICE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    in_year = [p for p in points if p.start.astimezone(timezone.utc).year == year]
    # De-dup by timestamp (last write wins), then sort — a refresh may re-fetch an overlap.
    by_ts: dict[datetime, float] = {}
    for p in in_year:
        by_ts[p.start.astimezone(timezone.utc)] = p.price_eur_kwh
    ordered = sorted(by_ts.items())

    path = year_path(year, bzn)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_HEADER)
        for ts, price in ordered:
            writer.writerow([ts.isoformat(), _fmt_price(price)])
    return len(ordered)


def _fmt_price(price: float) -> str:
    """Format a price without trailing float noise but without losing genuine precision.

    Prices are EUR/kWh to ~5 decimals (the API gives EUR/MWh to 2 decimals → EUR/kWh to 5).
    `repr`-style formatting would emit `0.29550000000000004`; a fixed 6-dp string is exact for
    this source and keeps the committed files clean and diff-stable.
    """
    return f"{price:.6f}"


def _read_file(path: Path) -> list[PricePoint]:
    """Parse one yearly CSV into PricePoints; missing file → empty (a year we do not ship)."""
    if not path.exists():
        return []
    out: list[PricePoint] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header != list(_HEADER):
            raise ValueError(f"{path}: unexpected header {header!r}, expected {list(_HEADER)}")
        for row in reader:
            if not row:
                continue
            ts = datetime.fromisoformat(row[0])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out.append(PricePoint(start=ts, price_eur_kwh=float(row[1])))
    return out


def load_range(start: datetime, end: datetime, bzn: str = BZN_NL) -> list[PricePoint]:
    """Committed price points with start in [start, end), across the spanned yearly files.

    `start`/`end` are tz-aware UTC. Reads only the yearly files the window touches, filters to
    the half-open interval, and returns them sorted. Missing years contribute nothing (the
    committed dataset simply does not go that far back), which the runtime source reports.
    """
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    points: list[PricePoint] = []
    for year in range(start.year, end.year + 1):
        for p in _read_file(year_path(year, bzn)):
            if start <= p.start < end:
                points.append(p)
    points.sort(key=lambda p: p.start)
    return points


def last_on_disk(bzn: str = BZN_NL) -> datetime | None:
    """The latest committed interval start for `bzn`, or None if no yearly files exist.

    Reads the newest present yearly file and returns its last row's timestamp — the point from
    which the runtime source bridges to `now` via the API (specs §4.3 spot-price source).
    """
    if not PRICE_DATA_DIR.exists():
        return None
    years = sorted(
        int(p.stem.split("-")[-1])
        for p in PRICE_DATA_DIR.glob(f"{_safe_bzn(bzn)}-*.csv")
        if p.stem.split("-")[-1].isdigit()
    )
    for year in reversed(years):
        pts = _read_file(year_path(year, bzn))
        if pts:
            return max(p.start for p in pts)
    return None
