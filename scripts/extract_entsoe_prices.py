#!/usr/bin/env python3
"""Extract NL day-ahead prices from the raw ENTSO-E dumps into the committed yearly CSVs.

Reads the raw monthly ENTSO-E "Energy Prices" exports in external_data/entso-e/ and writes the
NL bidding-zone day-ahead series to app/data/spot_prices_entsoe/NL-YYYY.csv, the alternate
spot-price dataset the backend source in app/sources/entsoe.py reads (see app/sources/
entsoe_store.py for the on-disk format).

This is the counterpart of scripts/fetch_spot_prices.py, which seeds the *other* committed
dataset (app/data/spot_prices/) from the Energy-Charts API. The two are independent origins for
the same quantity and are deliberately kept side by side so they can be compared.

Raw input format: one tab-separated file per month, `YYYY_MM_EnergyPrices_12.1.D_r3.1.csv`, with
columns InstanceCode, DateTime(UTC), ResolutionCode, AreaCode, AreaDisplayName, AreaTypeCode,
AreaMapCode, ContractType, Sequence, Price[Currency/MWh], Currency, UpdateTime(UTC). Each file
holds every European bidding zone, so the NL rows are a small fraction of a large file; the whole
corpus is hundreds of megabytes and is therefore streamed line by line, never read whole.

Granularity: the NL market moved from hourly to quarter-hourly at the start of 2025-10-01 local
time (the last PT60M interval is 2025-09-30 21:00 UTC, the first PT15M one 22:00 UTC). Both
resolutions are kept at their native spacing — nothing is resampled here, per the same rule
price_store.py follows (specs §6.2 owns resampling). Where two rows ever claim the same interval
start at different resolutions, the finest wins; see _Accumulator.add.

Usage:
    uv run python scripts/extract_entsoe_prices.py             # all years found in the raw dir
    uv run python scripts/extract_entsoe_prices.py --dry-run   # report only, write nothing
    uv run python scripts/extract_entsoe_prices.py --out-dir /tmp/x

This script reads the repo and writes into it; it is a developer/packager tool, not part of the
running app. The app never calls it — the runtime source reads the files it produces.

Main items:
    RAW_DIR / SELECTORS      default raw-input location and the row filter identifying NL.
    parse_row(fields)        one raw record → (timestamp, resolution_s, price) or None.
    _Accumulator             collects rows per year, resolving collisions finest-resolution-first.
    extract(paths)           stream the raw files into per-year point lists.
    main(argv)               CLI: extract, report, and write the yearly CSVs.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `python scripts/extract_entsoe_prices.py` from the repo root without an install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from app.sources.entsoe_store import ENTSOE_DATA_DIR, PricePointAtRes, write_year  # noqa: E402

# Where the raw monthly dumps live, and the filename shape we accept. The `12.1.D` is the ENTSO-E
# transparency-platform article number for day-ahead prices; `r3.1` the export revision.
RAW_DIR = _REPO_ROOT / "external_data" / "entso-e"
RAW_GLOB = "*_EnergyPrices_12.1.D_r*.csv"

# The raw columns we read, by index. The files carry a header naming these, which _read_header
# verifies before any row is parsed, so a changed export layout fails loudly instead of silently
# reading the wrong column.
COL_DATETIME = 1
COL_RESOLUTION = 2
COL_AREA_TYPE = 5
COL_AREA_MAP = 6
COL_CONTRACT = 7
COL_PRICE = 9
COL_CURRENCY = 10

EXPECTED_HEADER = [
    "InstanceCode", "DateTime(UTC)", "ResolutionCode", "AreaCode", "AreaDisplayName",
    "AreaTypeCode", "AreaMapCode", "ContractType", "Sequence", "Price[Currency/MWh]",
    "Currency", "UpdateTime(UTC)",
]

# The row filter that identifies the series we want: the Netherlands *bidding zone* (BZN — the
# price area, as opposed to the control-area/country aggregations the same files also carry),
# day-ahead contracts, priced in euro. Verified corpus-wide: NL has exactly one BZN and one
# currency, so this selects an unambiguous single series.
SELECTORS = {
    COL_AREA_TYPE: "BZN",
    COL_AREA_MAP: "NL",
    COL_CONTRACT: "Day-ahead",
    COL_CURRENCY: "EUR",
}

# ENTSO-E resolution tokens → seconds. Stored as seconds rather than the raw token so the on-disk
# column matches SeriesFrame.resolution_s downstream (no token parsing at read time). Only these
# two occur for NL day-ahead across the corpus; anything else is a data surprise worth failing on.
RESOLUTION_SECONDS = {"PT60M": 3600, "PT15M": 900, "PT30M": 1800}

# Raw prices are EUR per MWh; the app works in EUR per kWh throughout (specs §5.6).
_KWH_PER_MWH = 1000.0


def parse_row(fields: list[str]) -> tuple[datetime, int, float] | None:
    """One raw tab-split record → (utc_start, resolution_s, price_eur_kwh), or None to skip.

    Returns None for any row that is not the NL day-ahead euro series (the files hold every
    European zone), and for short rows. Raises ValueError for a row that *is* ours but carries an
    unparseable timestamp, an unknown resolution token, or a non-numeric price — those are data
    surprises we want to hear about rather than silently drop.
    """
    if len(fields) <= COL_CURRENCY:
        return None
    for index, expected in SELECTORS.items():
        if fields[index] != expected:
            return None

    token = fields[COL_RESOLUTION]
    if token not in RESOLUTION_SECONDS:
        raise ValueError(f"unknown resolution code {token!r} for an NL day-ahead row")

    # The raw stamp is a naive "YYYY-MM-DD HH:MM:SS" already in UTC (the column says so); attach
    # the zone explicitly so everything downstream is tz-aware.
    stamp = datetime.strptime(fields[COL_DATETIME], "%Y-%m-%d %H:%M:%S")
    stamp = stamp.replace(tzinfo=timezone.utc)

    return stamp, RESOLUTION_SECONDS[token], float(fields[COL_PRICE]) / _KWH_PER_MWH


class _Accumulator:
    """Collects parsed points keyed by interval start, keeping the finest resolution per start.

    The corpus as measured has no such collision — the hourly regime ends exactly where the
    quarter-hourly one begins — so this rule never fires on today's data. It is enforced anyway so
    that a future re-dump containing an overlap resolves deterministically toward the finer series
    (the user's "keep the finest granularity" requirement) instead of keeping whichever row
    happened to be read last.

    A same-start, same-resolution repeat (a revised price for an interval already seen) keeps the
    later row, since the raw files are read in chronological order and a later dump supersedes.
    """

    def __init__(self) -> None:
        self._by_start: dict[datetime, tuple[int, float]] = {}
        self.collisions = 0

    def add(self, start: datetime, resolution_s: int, price: float) -> None:
        previous = self._by_start.get(start)
        if previous is not None:
            self.collisions += 1
            if previous[0] < resolution_s:  # already have a finer one; keep it
                return
        self._by_start[start] = (resolution_s, price)

    def by_year(self) -> dict[int, list[PricePointAtRes]]:
        """The accumulated points grouped by UTC calendar year, each list sorted by start."""
        years: dict[int, list[PricePointAtRes]] = {}
        for start in sorted(self._by_start):
            resolution_s, price = self._by_start[start]
            years.setdefault(start.year, []).append(
                PricePointAtRes(start=start, price_eur_kwh=price, resolution_s=resolution_s)
            )
        return years


def _read_header(handle, path: Path) -> None:
    """Consume the header line and verify the column layout matches EXPECTED_HEADER.

    The raw dumps are CRLF-terminated, so lines are stripped of both terminators throughout
    (`\\r\\n`); an un-stripped `\\r` would otherwise ride along on the last column of every row.
    """
    header = handle.readline().rstrip("\r\n").split("\t")
    if header != EXPECTED_HEADER:
        raise ValueError(
            f"{path.name}: unexpected column layout.\n  expected: {EXPECTED_HEADER}\n"
            f"  found:    {header}"
        )


def extract(paths: list[Path]) -> tuple[dict[int, list[PricePointAtRes]], int]:
    """Stream `paths` (raw monthly TSVs) and return (points by year, collision count).

    Files are read one line at a time: the corpus is ~430 MB and holds every European zone, of
    which NL day-ahead is a small slice, so nothing is loaded whole.
    """
    accumulator = _Accumulator()
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            _read_header(handle, path)
            for line_number, line in enumerate(handle, start=2):
                line = line.rstrip("\r\n")
                if not line:
                    continue
                try:
                    parsed = parse_row(line.split("\t"))
                except ValueError as exc:
                    raise ValueError(f"{path.name}:{line_number}: {exc}") from None
                if parsed is not None:
                    accumulator.add(*parsed)
    return accumulator.by_year(), accumulator.collisions


def _describe(points: list[PricePointAtRes]) -> str:
    """A one-line per-year summary: row count and the split across native resolutions."""
    counts: dict[int, int] = {}
    for point in points:
        counts[point.resolution_s] = counts.get(point.resolution_s, 0) + 1
    split = ", ".join(f"{n}×{s}s" for s, n in sorted(counts.items()))
    return f"{len(points):>6} rows ({split})"


def _report_gaps(year: int, points: list[PricePointAtRes]) -> list[str]:
    """Describe intervals missing between consecutive points, judged by each point's resolution.

    A gap is any pair of consecutive starts further apart than the earlier point's own interval
    length. Reported rather than repaired: a hole in the raw dump is a fact about the dataset the
    operator should see, and silently interpolating it would fabricate prices. The single expected
    step at the hourly→quarter-hourly switchover is not a gap (the hour before it is a full hour
    long) and so does not appear here.
    """
    messages = []
    for earlier, later in zip(points, points[1:]):
        expected = earlier.start.timestamp() + earlier.resolution_s
        actual = later.start.timestamp()
        if actual > expected:
            missing = int((actual - expected) // earlier.resolution_s) + 1
            messages.append(
                f"  {year}: gap of {missing} interval(s) after "
                f"{earlier.start.isoformat()} → {later.start.isoformat()}"
            )
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR,
                        help=f"directory of raw ENTSO-E monthly dumps (default {RAW_DIR})")
    parser.add_argument("--out-dir", type=Path, default=ENTSOE_DATA_DIR,
                        help=f"where to write NL-YYYY.csv (default {ENTSOE_DATA_DIR})")
    parser.add_argument("--bzn", default="NL", help="bidding zone label for filenames (default NL)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be written without writing anything")
    args = parser.parse_args(argv)

    if not args.raw_dir.is_dir():
        parser.error(f"raw directory not found: {args.raw_dir}")
    paths = sorted(args.raw_dir.glob(RAW_GLOB))
    if not paths:
        parser.error(f"no raw dumps matching {RAW_GLOB} in {args.raw_dir}")

    print(f"reading {len(paths)} raw file(s) from {args.raw_dir}")
    by_year, collisions = extract(paths)
    if not by_year:
        print("no NL day-ahead rows found — check the selectors against the raw layout")
        return 1
    if collisions:
        print(f"note: {collisions} interval(s) appeared more than once; kept the finest resolution")

    gaps: list[str] = []
    for year in sorted(by_year):
        gaps.extend(_report_gaps(year, by_year[year]))

    total = 0
    for year in sorted(by_year):
        points = by_year[year]
        total += len(points)
        if args.dry_run:
            print(f"{args.bzn}-{year}: {_describe(points)} (dry run, not written)")
        else:
            written = write_year(year, points, bzn=args.bzn, out_dir=args.out_dir)
            print(f"{args.bzn}-{year}: {_describe(points)} → {args.out_dir}/{args.bzn}-{year}.csv"
                  f"{'' if written == len(points) else f' [{written} written]'}")

    if gaps:
        print(f"\n{len(gaps)} gap(s) in the extracted series — the raw dump is missing intervals:")
        for message in gaps[:20]:
            print(message)
        if len(gaps) > 20:
            print(f"  … and {len(gaps) - 20} more")

    span = f"{min(by_year)}–{max(by_year)}"
    print(f"\ndone: {total} rows across {len(by_year)} year(s) ({span})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
