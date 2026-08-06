"""Per-slot data-source registry — the table the source-picker drawer reads (specs §2.2).

A plain lookup table over the instantiated sources, with no behaviour beyond selection (same
discipline as series_vocab.py). It answers two questions: for a given slot, which sources may
fill it (`sources_for`, what the drawer lists), and for a stored source key, which source object
handles it (`get_source`, used when a slot's chosen source is loaded).

Sources are instantiated once here. HA is listed first for every slot it offers (it is the
primary origin); other sources follow in registration order — the two preset spot-price sources
for `price_spot`, and the uploaded-CSV source for every energy slot.

Main items:
    ALL_SOURCES            the instantiated sources, in registration order (HA first).
    sources_for(slot)      the SourceDescriptors offered for `slot`, HA first.
    get_source(key)        the DataSource for a descriptor key; ValueError if unknown.
"""

from __future__ import annotations

from app.domain.series_vocab import SlotSpec
from app.sources.base import DataSource, SourceDescriptor
from app.sources.csv_source import CsvSource
from app.sources.energy_charts import EnergyChartsSource
from app.sources.entsoe import EntsoeSource
from app.sources.home_assistant import HomeAssistantSource

# The instantiated sources, in registration order. HA is first so it leads every slot's list (it
# is the primary origin, available for every slot); the two preset spot-price sources follow.
# Energy-Charts precedes ENTSO-E because it bridges live to `now` while ENTSO-E stops at the last
# extracted dump, making it the better default for a window reaching the present; ENTSO-E offers
# earlier coverage (mid-2022) and its own native resolutions.
# CSV is last for every energy slot it offers. HA is the primary origin and the one a household
# with Home Assistant should reach for first; an upload is the fallback for a household that has
# an export but no HA, and for the slots HA cannot supply. Ordering is presentation only — nothing
# selects a source by position — but the drawer reads top to bottom, so the order is the
# recommendation.
ALL_SOURCES: list[DataSource] = [
    HomeAssistantSource(),
    EnergyChartsSource(),
    EntsoeSource(),
    CsvSource(),
]

# Descriptor-key → source lookup, built once from ALL_SOURCES. Keys are the stable ids persisted
# with a slot's chosen source (specs §2.2); a duplicate key would be a registration bug.
_BY_KEY: dict[str, DataSource] = {}
for _s in ALL_SOURCES:
    _key = _s.descriptor.key
    if _key in _BY_KEY:
        raise ValueError(f"duplicate data-source key {_key!r} in ALL_SOURCES")
    _BY_KEY[_key] = _s


def sources_for(slot: SlotSpec) -> list[SourceDescriptor]:
    """The descriptors of every source whose `available_for(slot)` is True, in registration order.

    This is what the source-picker side panel lists for `slot`. HA leads (registration order),
    followed by any other source that offers the slot (e.g. the preset spot-price source for
    price_spot).
    """
    return [s.descriptor for s in ALL_SOURCES if s.available_for(slot)]


def get_source(key: str) -> DataSource:
    """The DataSource for descriptor `key`; ValueError if no source declares that key.

    Used when a slot's persisted source choice is loaded (specs §2.2). The error names the key so
    a stale or mistyped choice fails loudly rather than silently.
    """
    try:
        return _BY_KEY[key]
    except KeyError:
        raise ValueError(f"unknown data-source key {key!r}") from None
