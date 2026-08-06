"""Data sources — where each series slot's data is pulled from (specs §2.2, §4.3).

Panel ① is slot-first: for every series slot the user picks a source. This package holds the
`DataSource` abstraction, the concrete sources (Home Assistant, the preset Energy-Charts NL
spot-price dataset), and the per-slot registry the source-picker drawer reads. The low-level
Energy-Charts API client and the on-disk price store live here too and are re-exported for
callers (scripts, the runtime source).

Main items:
    SourceKind, SourceDescriptor, DataSource   the abstraction (base.py).
    HomeAssistantSource                        browser_fetch source; frames arrive over the WS.
    EnergyChartsSource, bridge_date_range      backend_load spot-price source + its pure helper.
    CsvSource, CsvBinding                      backend_load uploaded-wide-CSV source (energy slots).
    ALL_SOURCES, sources_for, get_source       the per-slot registry (registry.py).
    PricePoint, price_store                    re-exported on-disk/API building blocks.
"""

from __future__ import annotations

from app.sources import price_store
from app.sources.base import DataSource, SourceDescriptor, SourceKind
from app.sources.csv_source import CsvBinding, CsvBindingError, CsvSource
from app.sources.energy_charts import EnergyChartsSource, bridge_date_range
from app.sources.energy_charts_api import PricePoint
from app.sources.home_assistant import HomeAssistantSource
from app.sources.registry import ALL_SOURCES, get_source, sources_for

__all__ = [
    "SourceKind",
    "SourceDescriptor",
    "DataSource",
    "HomeAssistantSource",
    "EnergyChartsSource",
    "bridge_date_range",
    "CsvSource",
    "CsvBinding",
    "CsvBindingError",
    "ALL_SOURCES",
    "sources_for",
    "get_source",
    "PricePoint",
    "price_store",
]
