#!/usr/bin/env python3
"""Download NL day-ahead spot prices and (over)write the committed yearly CSVs.

Seeds and refreshes the on-disk spot-price dataset the backend source ships with
(app/data/spot_prices/NL-YYYY.csv, see app/domain/sources/price_store.py). Run once to seed the
repository, and re-run to extend it to the present — the runtime source only needs the API to
bridge from the last committed interval to `now`, so keeping this current shrinks that bridge.

Fetches from https://api.energy-charts.info/price one calendar year per request (a year is tens
of kilobytes) via app/domain/sources/energy_charts_api.py, then writes each year with
price_store.write_year, which sorts and de-duplicates. The current year is fetched up to today.

Usage:
    uv run python scripts/fetch_spot_prices.py                 # 2023 → today, zone NL
    uv run python scripts/fetch_spot_prices.py --start 2024    # from a given year
    uv run python scripts/fetch_spot_prices.py --bzn NL        # bidding zone (default NL)

This script does network I/O and writes into the repo; it is a developer/packager tool, not part
of the running app. The app never calls it — the runtime source reads the files it produces.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

# Allow `python scripts/fetch_spot_prices.py` from the repo root without an install.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.sources.energy_charts_api import BZN_NL, fetch_prices  # noqa: E402
from app.sources.price_store import write_year, year_path  # noqa: E402

# The committed dataset starts here. 2023 is the first full year the NL zone is available from
# the endpoint and is old enough to cover the retrospective windows the simulator runs (specs
# §4.3). Earlier data can be requested with --start if the endpoint ever exposes it.
DEFAULT_START_YEAR = 2023


def _year_bounds(year: int, today: date) -> tuple[date, date]:
    """[start, end] calendar dates to request for `year`; the current year stops at `today`."""
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    if year == today.year:
        end = today
    return start, end


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=DEFAULT_START_YEAR,
                        help=f"first calendar year to fetch (default {DEFAULT_START_YEAR})")
    parser.add_argument("--bzn", default=BZN_NL, help="bidding zone (default NL)")
    args = parser.parse_args(argv)

    today = date.today()
    if args.start > today.year:
        parser.error(f"--start {args.start} is in the future")

    total = 0
    for year in range(args.start, today.year + 1):
        start, end = _year_bounds(year, today)
        # end is inclusive at the API; request one extra day so the last day's intervals are not
        # clipped, then price_store filters to the year.
        points = fetch_prices(start, end + timedelta(days=1), bzn=args.bzn)
        rows = write_year(year, points, bzn=args.bzn)
        total += rows
        print(f"{args.bzn}-{year}: {rows:>6} rows → {year_path(year, args.bzn)}")

    print(f"done: {total} rows across {today.year - args.start + 1} year(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
