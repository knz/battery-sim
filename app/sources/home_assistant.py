"""The Home Assistant data source — a browser_fetch descriptor (specs §4.3, §6).

Home Assistant is the primary origin: any slot can be filled from an HA statistic (energy sums
for the energy slots, mean/measurement stats for the price slots). But the fetch happens in the
*browser*, not here — the HA long-lived token stays in localStorage and streams rows to
WS /data/ingest/ws, which app.domain.ingest normalises into SeriesFrames. So this source exists
only as the descriptor the drawer shows and the `available_for` rule; its `load` never runs.

Main items:
    HomeAssistantSource   the DataSource impl: available for every slot, load() raises.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.frames import SeriesFrame
from app.domain.series_vocab import SlotSpec
from app.sources.base import SourceDescriptor

# Stable descriptor for the drawer. `key` is persisted with a slot's chosen source and must not
# change once shipped (specs §2.2). The blurb states the privacy invariant plainly: the token is
# a browser-only credential, so the phrasing tells the user it never reaches this app.
_DESCRIPTOR = SourceDescriptor(
    key="home_assistant",
    label="Home Assistant",
    kind="browser_fetch",
    blurb="Fetched from your Home Assistant in your browser; the token never reaches this app.",
)


class HomeAssistantSource:
    """DataSource for Home Assistant statistics (browser-side fetch, specs §4.3)."""

    @property
    def descriptor(self) -> SourceDescriptor:
        return _DESCRIPTOR

    def available_for(self, slot: SlotSpec) -> bool:
        """HA can fill any slot: energy sums for energy slots, mean stats for price slots."""
        return True

    def load(self, slot: SlotSpec, window: tuple[datetime, datetime]) -> SeriesFrame:
        """Never loaded backend-side: HA frames arrive over the ingest WS (specs §4.3).

        The HA token is a browser-only credential and must never reach this app, so the backend
        has no way to fetch HA data. The frame for an HA slot is produced by the browser→WS
        ingest path (ha_fetch.js → WS /data/ingest/ws → app.domain.ingest), not here.
        """
        raise NotImplementedError(
            "Home Assistant frames are produced by the browser and streamed to "
            "WS /data/ingest/ws; the backend does not load them (the HA token stays "
            "in the browser and never reaches this app)."
        )
