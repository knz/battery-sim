"""Energy-Charts day-ahead price API client + response parsing (pure-ish adapter).

This is the low-level access to https://api.energy-charts.info/price — the public NL
day-ahead spot-price endpoint the spot-price data source is built on (specs/06-home-assistant
-ingestion.md, spot-price backend source). It is shared by two callers:

  * scripts/fetch_spot_prices.py — the one-off/refresh downloader that seeds the committed
    on-disk dataset (app/data/spot_prices/NL-YYYY.csv).
  * app/sources/energy_charts.py — the runtime source, which reads the on-disk data and
    calls this to bridge from the last on-disk timestamp to the end of the requested window.

Two layers, kept apart so the parsing is testable without a network:

  * parse_price_response(payload) — pure: the API's parallel-array JSON → a list of PricePoint
    (interval-start UTC datetime, EUR/kWh). Converts the API's EUR/MWh to the EUR/kWh the
    series vocabulary uses (specs §4.3 price kind), and drops trailing nulls.
  * fetch_prices(bzn, start, end, *, opener) — does the one HTTP GET and parses it. `opener` is
    injected (defaults to urllib) so tests pass a stub and never touch the network.

The response shape (verified against the live API 2026-07-24):
    {"unix_seconds": [<int>, ...], "price": [<float EUR/MWh>, ...], "unit": "EUR / MWh", ...}
Native resolution is hourly for older years and 15-minute for recent ones (the NL market moved
to quarter-hourly); this module preserves whatever spacing the API returns and does not resample.

Main items:
    PricePoint                       (start: aware UTC datetime, price_eur_kwh: float).
    EUR_PER_MWH_TO_EUR_PER_KWH       the unit conversion factor (1/1000).
    ENERGY_CHARTS_PRICE_URL          the endpoint base.
    parse_price_response(payload)    pure parse + unit convert + null drop.
    fetch_prices(bzn, start, end)    GET + parse; `opener` injectable for tests.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone

# The API returns prices in EUR/MWh; the series vocabulary's price kind is EUR/kWh (specs §4.3),
# so every price is divided by 1000. Named because it encodes the unit decision, not arithmetic
# happenstance (specs §5.6).
EUR_PER_MWH_TO_EUR_PER_KWH = 1.0 / 1000.0

ENERGY_CHARTS_PRICE_URL = "https://api.energy-charts.info/price"

# Bidding zone for the Netherlands. The endpoint is multi-country; we only ever ask for NL.
BZN_NL = "NL"

# Network timeout for a single price GET, in seconds. A year chunk is tens of kilobytes, so this
# is generous; it exists so a hung connection fails the fetch rather than blocking a request.
_HTTP_TIMEOUT_S = 30


@dataclass(frozen=True)
class PricePoint:
    """One day-ahead price interval: its UTC start and the price in EUR/kWh."""

    start: datetime
    price_eur_kwh: float


def parse_price_response(payload: dict) -> list[PricePoint]:
    """Energy-Charts price JSON → PricePoints (pure; unit-converted, null-dropped).

    `payload` is the decoded JSON: parallel `unix_seconds` and `price` arrays. Each pair becomes
    a PricePoint with a tz-aware UTC start and EUR/kWh price. A null price (the API pads the tail
    of the current day with nulls before prices are published) drops that point rather than
    carrying a NaN into the on-disk data — a missing interval is simply absent, matching how the
    ingest path treats a gap (specs §4.2).
    """
    seconds = payload.get("unix_seconds") or []
    prices = payload.get("price") or []
    points: list[PricePoint] = []
    for ts, price in zip(seconds, prices):
        if price is None:
            continue
        start = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        points.append(PricePoint(start=start, price_eur_kwh=float(price) * EUR_PER_MWH_TO_EUR_PER_KWH))
    return points


# Sent on every request. The API rate-limits/refuses the default `Python-urllib/x.y` agent
# (observed 429s); a descriptive agent identifying the app is the courteous fix and clears it.
_USER_AGENT = "battery-sim/0.1 (+https://github.com/; spot-price fetch)"


def _default_opener(url: str) -> bytes:
    """Fetch `url` and return the raw body. Isolated so tests inject a stub instead."""
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:  # noqa: S310 (fixed host)
        return resp.read()


def fetch_prices(
    start: date,
    end: date,
    *,
    bzn: str = BZN_NL,
    opener=_default_opener,
) -> list[PricePoint]:
    """GET day-ahead prices for [start, end] and parse them (specs §4.3 spot-price source).

    `start`/`end` are calendar dates; the API treats `end` inclusively at day granularity. The
    HTTP layer is injected via `opener` (a `str -> bytes` callable) so tests exercise the parse
    without a network. Returns PricePoints in ascending time; empty if the API returned nothing.
    """
    url = f"{ENERGY_CHARTS_PRICE_URL}?bzn={bzn}&start={start.isoformat()}&end={end.isoformat()}"
    body = opener(url)
    payload = json.loads(body)
    return parse_price_response(payload)
