"""Live round-trip test against a real Home Assistant instance (specs §4.3).

Skipped unless a token and URL are available, so CI and other machines are unaffected. When it
runs, it does the *whole* data path the way the browser will in Phase 2 — WS auth, list ids,
statistics_during_period — but from Python, then feeds the fetched rows through the same domain
ingest the WS endpoint uses, asserting real HA data becomes valid SeriesFrames. This is the
feasibility check from changelog/20260723-ha-data-import.md, pinned as a test.

Enable by pointing at an instance:
    HA_URL=wss://192.168.2.8:8123/api/websocket \
    HA_TOKEN_FILE=~/.homeassistant \
    HA_INSECURE=1 \
    uv run pytest tests/test_ha_live.py -v

HA_INSECURE=1 disables TLS verification for a self-signed LAN cert (the probe posture, not the
app's — the browser handles the cert in production).
"""

import asyncio
import json
import os
import ssl
from pathlib import Path

import pytest

from app.domain import ingest

HA_URL = os.environ.get("HA_URL")
_TOKEN_FILE = os.environ.get("HA_TOKEN_FILE")
HA_TOKEN = Path(_TOKEN_FILE).expanduser().read_text().strip() if _TOKEN_FILE and Path(_TOKEN_FILE).expanduser().exists() else None

pytestmark = pytest.mark.skipif(
    not (HA_URL and HA_TOKEN),
    reason="set HA_URL and HA_TOKEN_FILE to run the live HA round-trip",
)


def _ssl_context():
    if os.environ.get("HA_INSECURE") == "1":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


async def _fetch(statistic_ids, start_iso, end_iso, period="hour", types=None):
    """Minimal WS fetch mirroring the browser's Phase-2 client (specs §4.3)."""
    import websockets

    async with websockets.connect(HA_URL, ssl=_ssl_context(), max_size=64 * 2**20) as ws:
        await ws.recv()  # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        _id = 0

        async def call(payload):
            nonlocal _id
            _id += 1
            payload["id"] = _id
            await ws.send(json.dumps(payload))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == _id and m.get("type") == "result":
                    return m

        ids = await call({"type": "recorder/list_statistic_ids", "statistic_type": "sum"})
        stat = await call({
            "type": "recorder/statistics_during_period",
            "start_time": start_iso, "end_time": end_iso,
            "statistic_ids": statistic_ids, "period": period,
            **({"types": types} if types else {}),
        })
        return ids.get("result", []), stat.get("result", {})


def test_live_energy_fetch_becomes_valid_frames():
    # A real P1 register on the instance under test (see changelog feasibility findings).
    stat_id = os.environ.get("HA_ENERGY_STAT", "sensor.energy_consumed_tariff_1")
    ids, result = asyncio.run(_fetch([stat_id], "2026-07-15T00:00:00+00:00", "2026-07-18T00:00:00+00:00"))
    assert any(s.get("statistic_id") == stat_id for s in ids), f"{stat_id} not among statistic ids"
    rows = result.get(stat_id, [])
    assert rows, "no statistics rows returned for the window"

    energy_rows = [ingest.EnergyRow(start_ms=int(r["start"]), sum=r.get("sum")) for r in rows]
    frame, warns = ingest.energy_frame("grid_import_t1", energy_rows)
    assert frame.resolution_s == 3600  # long-term stats are hourly (specs §4.3)
    assert len(frame.values) == len(rows) - 1
    # Real consumption is non-negative once reset-corrected; no ambiguous decreases expected.
    import numpy as np
    assert np.nansum(frame.values) >= 0


def test_live_price_fetch_carries_bracket():
    stat_id = os.environ.get("HA_PRICE_STAT", "sensor.epex_spot_data_market_price")
    _, result = asyncio.run(_fetch(
        [stat_id], "2026-07-15T00:00:00+00:00", "2026-07-16T00:00:00+00:00",
        types=["mean", "min", "max"],
    ))
    rows = result.get(stat_id, [])
    if not rows:
        pytest.skip(f"{stat_id} has no data on this instance")
    price_rows = [ingest.PriceRow(start_ms=int(r["start"]), mean=r.get("mean"),
                                  min=r.get("min"), max=r.get("max")) for r in rows]
    frame = ingest.price_frame("price_spot", price_rows)
    assert frame.kind == "price"
    assert frame.value_min is not None and frame.value_max is not None
