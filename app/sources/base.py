"""The `DataSource` abstraction: how a slot's data is obtained (specs §2.2, §4.3).

Panel ① is slot-first: the user is shown the roster of series slots (series_vocab.SlotSpec)
and, per slot, chooses where that slot's data comes from. A `DataSource` is one such origin —
Home Assistant, the preset historical spot-price dataset, and (later) CSV. The set offered for
a given slot is decided by `available_for`; the registry (registry.py) turns that into the
per-slot list the source-picker side panel reads.

Two families of source exist, distinguished by `SourceKind`, because the frame is produced in
two very different places:

  * "browser_fetch" — the frame is built by the browser→WS ingest path (ha_fetch.js →
    WS /data/ingest/ws → app.domain.ingest). The backend never loads it; the source object is a
    descriptor the UI shows, and its `load` raises. Home Assistant is this kind: the HA token
    stays in the browser and must never reach this app.
  * "backend_load" — the backend loads the frame itself, with no browser round-trip. The preset
    Energy-Charts spot-price source is this kind: it reads committed on-disk data and bridges
    the recent tail from a public API the backend may call directly.

Main items:
    SourceKind          "browser_fetch" | "backend_load" — where the frame is produced.
    SourceDescriptor    the drawer-facing metadata (key, label, kind, blurb).
    DataSource          the Protocol: descriptor, available_for(slot), load(slot, window).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from app.domain.frames import SeriesFrame
from app.domain.series_vocab import SlotSpec

# Where a source's frame is produced. "browser_fetch" sources are shown in the drawer but the
# backend never loads them (their frames arrive over the ingest WS); "backend_load" sources are
# loaded by the backend itself. This gates whether `load` does work or raises (see DataSource).
SourceKind = Literal["browser_fetch", "backend_load"]


@dataclass(frozen=True)
class SourceDescriptor:
    """Drawer-facing metadata for one data source (the source-picker side panel, specs §2.2).

    `key` is the stable id used to look the source up in the registry and to persist a slot's
    chosen source (e.g. "home_assistant", "energy_charts"); it never changes once shipped.
    `label` and `blurb` are the human-readable name and one-line description shown in the drawer.
    `kind` tells the UI whether picking this source starts a browser fetch or a backend load.
    """

    key: str
    label: str
    kind: SourceKind
    blurb: str


@runtime_checkable
class DataSource(Protocol):
    """One origin a slot's data can be pulled from (specs §2.2 slot-first source picker).

    Implementations are plain objects instantiated once in the registry. `available_for` decides
    which slots offer this source; `load` produces the SeriesFrame for a backend_load source, and
    raises for a browser_fetch source whose frame instead arrives over the ingest WS.
    """

    @property
    def descriptor(self) -> SourceDescriptor:
        """The drawer-facing metadata for this source."""

    def available_for(self, slot: SlotSpec) -> bool:
        """True if this source can fill `slot` (specs §4.1 slot roster)."""

    def load(self, slot: SlotSpec, window: tuple[datetime, datetime]) -> SeriesFrame:
        """Load `slot` over `window` (tz-aware UTC start, end).

        backend_load sources build and return the SeriesFrame. browser_fetch sources raise
        NotImplementedError: their frames are produced by the browser→WS ingest path, not here.
        """
