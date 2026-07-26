"""On-disk ENTSO-E NL price dataset: yearly CSV read/write (alternate spot-price source).

The alternate spot-price source ships with NL day-ahead prices extracted from the raw ENTSO-E
transparency-platform dumps (app/data/spot_prices_entsoe/NL-YYYY.csv). This module is the single
reader/writer of that on-disk format, shared by:

  * scripts/extract_entsoe_prices.py — writes the yearly files from external_data/entso-e/.
  * app/sources/entsoe.py — reads them at runtime to fill the price_spot slot.

Relationship to price_store.py: that module owns the *other* committed dataset, the one seeded
from the Energy-Charts API (app/data/spot_prices/). The two datasets are independent origins for
the same quantity, kept side by side so they can be compared, and they differ in format by one
column — this one records each row's native resolution:

    timestamp,price_eur_kwh,resolution_s
    2025-09-30T21:00:00+00:00,0.090000,3600
    2025-09-30T22:00:00+00:00,0.102550,900

`timestamp` is an ISO-8601 UTC instant (interval start); `price_eur_kwh` is already
unit-converted; `resolution_s` is that interval's own length in seconds — 3600 for the hourly
regime, 900 since the NL market moved to quarter-hourly on 2025-10-01 local. Because the two
regimes coexist within the 2025 file, a single per-file resolution would be wrong, which is why
it is recorded per row. Nothing is resampled here (specs §6.2 owns resampling).

Note that the per-row resolution is not yet propagated into the frame: ingest.price_frame infers
one modal resolution per frame. The column records the truth at rest so that the §6.2 grid
selector can use it; see the docstring of app/sources/entsoe.py for the current consequence.

Rows are kept sorted and de-duplicated by timestamp on write.

Main items:
    ENTSOE_DATA_DIR                 app/data/spot_prices_entsoe, the committed dataset root.
    PricePointAtRes                 a price point that carries its own native resolution.
    year_path(year, bzn, out_dir)   the CSV path for one year.
    write_year(year, points, ...)   (over)write one yearly file.
    load_range(start, end, bzn)     read committed points overlapping [start, end).
    last_on_disk(bzn)               the latest committed interval start, or None if no data.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# The committed dataset lives beside the code (app/data/), not under the runtime data_dir: it is
# shipped content, versioned with the app, not per-workspace user data. __file__ is
# app/sources/entsoe_store.py, so parent.parent is the app/ package root. This is deliberately a
# *different* directory from price_store.PRICE_DATA_DIR so neither dataset overwrites the other.
ENTSOE_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "spot_prices_entsoe"

_HEADER = ("timestamp", "price_eur_kwh", "resolution_s")


@dataclass(frozen=True)
class PricePointAtRes:
    """One priced interval, carrying its own native resolution.

    The counterpart of energy_charts_api.PricePoint, extended with `resolution_s` because this
    dataset spans the NL hourly→quarter-hourly change and so mixes interval lengths within a
    single year. `start` is the tz-aware UTC interval start; `price_eur_kwh` the price over it.
    """

    start: datetime
    price_eur_kwh: float
    resolution_s: int


def _safe_bzn(bzn: str) -> str:
    """Reject a bidding zone that is not a plain alphanumeric code.

    `bzn` is interpolated into filenames and a glob, so a value like `../../etc` would escape the
    data dir. At runtime `bzn` is always the `NL` constant, but the extractor script exposes it as
    a CLI flag, so guard it here rather than trust the caller (specs §5.5 path-traversal rule).
    """
    if not bzn.isalnum():
        raise ValueError(f"unsafe bidding-zone code: {bzn!r}")
    return bzn


def year_path(year: int, bzn: str = "NL", out_dir: Path | None = None) -> Path:
    """The CSV path for one bidding zone and year, e.g. `.../NL-2024.csv`.

    `out_dir` defaults to ENTSOE_DATA_DIR; the extractor overrides it so a dry run or a trial
    extraction can be written somewhere else.
    """
    return (out_dir or ENTSOE_DATA_DIR) / f"{_safe_bzn(bzn)}-{year}.csv"


def write_year(
    year: int,
    points: list[PricePointAtRes],
    bzn: str = "NL",
    out_dir: Path | None = None,
) -> int:
    """(Over)write one yearly CSV from `points`, sorted and de-duplicated by timestamp.

    Only points whose start falls in `year` (UTC) are written; a caller may pass a mixed list and
    this keeps the right ones. Returns the number of rows written. Creates the data dir if
    missing. An empty result still writes a header-only file so a year with no data is explicit.
    """
    directory = out_dir or ENTSOE_DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    in_year = [p for p in points if p.start.astimezone(timezone.utc).year == year]
    # De-dup by timestamp (last write wins), then sort. The extractor already resolves genuine
    # resolution collisions before this point; this is the final guard on the written file.
    by_ts: dict[datetime, PricePointAtRes] = {}
    for p in in_year:
        by_ts[p.start.astimezone(timezone.utc)] = p
    ordered = sorted(by_ts.items())

    path = year_path(year, bzn, out_dir)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_HEADER)
        for ts, point in ordered:
            writer.writerow([ts.isoformat(), _fmt_price(point.price_eur_kwh), point.resolution_s])
    return len(ordered)


def _fmt_price(price: float) -> str:
    """Format a price without trailing float noise but without losing genuine precision.

    Prices are EUR/kWh to ~5 decimals (the raw dumps give EUR/MWh to 2 decimals → EUR/kWh to 5).
    `repr`-style formatting would emit `0.29550000000000004`; a fixed 6-dp string is exact for
    this source and keeps the committed files clean and diff-stable (same rule as price_store).
    """
    return f"{price:.6f}"


def _read_file(path: Path) -> list[PricePointAtRes]:
    """Parse one yearly CSV into points; missing file → empty (a year we do not ship)."""
    if not path.exists():
        return []
    out: list[PricePointAtRes] = []
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
            out.append(
                PricePointAtRes(start=ts, price_eur_kwh=float(row[1]), resolution_s=int(row[2]))
            )
    return out


def load_range(start: datetime, end: datetime, bzn: str = "NL") -> list[PricePointAtRes]:
    """Committed price points with start in [start, end), across the spanned yearly files.

    `start`/`end` are tz-aware UTC. Reads only the yearly files the window touches, filters to the
    half-open interval, and returns them sorted. Missing years contribute nothing (the committed
    dataset simply does not go that far back), which the runtime source reports.
    """
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    points: list[PricePointAtRes] = []
    for year in range(start.year, end.year + 1):
        for p in _read_file(year_path(year, bzn)):
            if start <= p.start < end:
                points.append(p)
    points.sort(key=lambda p: p.start)
    return points


def last_on_disk(bzn: str = "NL") -> datetime | None:
    """The latest committed interval start for `bzn`, or None if no yearly files exist.

    Used to report the dataset's coverage. Unlike the Energy-Charts source, nothing bridges past
    this point: the raw ENTSO-E corpus is static, with no live endpoint behind it.
    """
    if not ENTSOE_DATA_DIR.exists():
        return None
    years = sorted(
        int(p.stem.split("-")[-1])
        for p in ENTSOE_DATA_DIR.glob(f"{_safe_bzn(bzn)}-*.csv")
        if p.stem.split("-")[-1].isdigit()
    )
    for year in reversed(years):
        pts = _read_file(year_path(year, bzn))
        if pts:
            return max(p.start for p in pts)
    return None
