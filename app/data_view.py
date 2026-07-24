"""Panel ① view-model from a persisted dataset (specs/02-ux-wireframes.md §2.2).

Bridges the persisted `LoadedDataset` (app/dataset.py) to the dict the `_panel_data.html`
template consumes. Before this increment the template rendered a static sample
(app/sample_data.py); once a real Home Assistant dataset has been fetched and persisted, this
module builds the panel from it instead — real coverage, the chosen simulation grid, per-series
native resolutions and reconciliation (§6.2), and the gap/reset counts recovered from the
per-interval quality flags (§4.4).

What it does NOT populate yet — because those computations are later increments — is left out
rather than faked: the negative-load reconstruction warning (§6.3), the tariff-register
identification (§6.4, cost-sim), and the resolution-bias diagnostic (§6.13). The template
renders these blocks conditionally, so a real dataset simply omits the ones not yet computed.

The role labels mirror the sample's, keyed by series name, so the same translation msgids apply.

Each mapping row now also carries per-slot source provenance (specs §2.2 slot-first sources):
`source` (the descriptor key of the source that produced the series, or None) and `sources` (the
sources the drawer may offer for that slot, as small {key,label,kind,blurb} dicts). Phase C's
source-picker drawer renders these; the current template ignores the extra keys, so the shape
stays a superset and nothing breaks between phases.

Main items:
    ROLE_LABEL                 series name → human role label (translation msgid).
    panel_data_from(dataset)   the panel-① dict; shape-compatible with sample_data._panel_data.
"""

from __future__ import annotations

import numpy as np

from app.dataset import LoadedDataset
from app.domain import normalize
from app.domain.frames import QualityFlags, SeriesFrame
from app.sources import registry

# Human role labels, keyed by internal series name (specs §4.1). These are the same English
# msgids the static sample uses, so the existing catalog covers them.
ROLE_LABEL: dict[str, str] = {
    "grid_import_t1": "Grid import T1",
    "grid_import_t2": "Grid import T2",
    "grid_export_t1": "Grid export T1",
    "grid_export_t2": "Grid export T2",
    "solar_production": "Solar production",
    "battery_charge": "Battery charge",
    "battery_discharge": "Battery discharge",
    "price_spot": "Spot price",
    "price_spot_min": "Spot price (min)",
    "price_spot_max": "Spot price (max)",
    "power_grid": "Grid power",
    "house_load": "House load",
}


def _fmt_res(seconds: int | None) -> str:
    """Seconds → a human resolution label ("hourly", "15-min", "5-min", "daily", or "Ns")."""
    if seconds is None:
        return "irregular"
    table = {300: "5-min", 900: "15-min", 1800: "30-min", 3600: "hourly", 86400: "daily"}
    return table.get(seconds, f"{seconds}s")


def _fmt_date(dt) -> str:
    return dt.date().isoformat()


def _count_flag(frames: list[SeriesFrame], flag: QualityFlags) -> int:
    total = 0
    for f in frames:
        if len(f.quality):
            total += int((np.asarray(f.quality) & int(flag)).astype(bool).sum())
    return total


def panel_data_from(dataset: LoadedDataset) -> dict:
    """Build the panel-① view-model from a persisted dataset (specs §2.2).

    Shape-compatible with sample_data._panel_data() so the template renders either. Fields the
    real pipeline does not yet compute are omitted; the template guards on their presence.
    """
    frames = dataset.frames
    report = normalize.grid_report(frames, dataset.window)
    grid_s = report["grid_s"]
    # Use the effective window (data coverage overlap) for coverage/day display, not the raw
    # fetch bounds — the two differ by up to an interval and the effective one is what the run
    # spans (specs §6.2).
    from datetime import datetime as _dt

    win_start = _dt.fromisoformat(report["window"]["start"])
    win_end = _dt.fromisoformat(report["window"]["end"])
    window = (win_start, win_end)

    # Mapping table: the FULL slot roster (specs §2.2 slot-first). One row per SERIES_SLOTS
    # entry whether or not a series is present, so the user can pick a source for a slot that has
    # no data yet. A present slot carries its fetched entity string and persisted source; an
    # absent slot carries entity=None and source=None. The template gates pv_only/cost_only rows.
    from app.domain.series_vocab import SERIES_SLOTS

    present = {f.name: f for f in frames}
    series_sources = getattr(dataset, "series_sources", {}) or {}
    mapping = []
    for slot in SERIES_SLOTS:
        f = present.get(slot.name)
        mapping.append(
            {
                "name": slot.name,
                "role": ROLE_LABEL.get(slot.name, slot.name),
                "req": slot.requirement,
                # Present: the "(res, N intervals)" coverage string. Absent: None (no data yet).
                "entity": (
                    f"({_fmt_res(f.resolution_s)}, {len(f.values)} intervals)"
                    if f is not None
                    else None
                ),
                "pv_only": slot.pv_only,
                "cost_only": slot.cost_only,
                # Slot-first provenance (specs §2.2): the source that produced this series (its
                # descriptor key, or None when the slot is unfilled), and the sources the drawer
                # may offer for this slot. Phase C's source-picker drawer renders these.
                "source": series_sources.get(slot.name),
                "sources": [
                    {"key": d.key, "label": d.label, "kind": d.kind, "blurb": d.blurb}
                    for d in registry.sources_for(slot)
                ],
            }
        )

    # Per-series granularity table (§2.2). "recorded" is the native resolution; "uses" is the
    # reconciliation onto the grid, with the lossy (averaged) case marked.
    grid_label = _fmt_res(grid_s)
    by_name = {f.name: f for f in frames}
    series_rows = []
    for entry in report["series"]:
        recon = entry["reconciliation"]
        if recon == "averaged":
            uses, warn = f"{grid_label}, averaged", True
        elif recon == "held":
            uses, warn = f"{grid_label}, held", False
        elif recon == "undefined":
            uses, warn = "undefined", False
        else:
            uses, warn = grid_label, False
        # "Recorded at" shows the native resolution, plus the finer copy over its sub-window when
        # one was fetched (specs §4.3, §2.2 — the two-line granularity cell).
        recorded = [f"{_fmt_res(entry['native_resolution_s'])} (full)"]
        f = by_name.get(entry["name"])
        if f is not None and f.fine_resolution_s and f.fine_coverage:
            fine_days = (f.fine_coverage[1] - f.fine_coverage[0]).days
            recorded.append(f"{_fmt_res(f.fine_resolution_s)} (last {fine_days} days)")
        series_rows.append(
            {
                "name": ROLE_LABEL.get(entry["name"], entry["name"]),
                "recorded": recorded,
                "uses": uses,
                "warn": warn,
            }
        )

    gaps = _count_flag(frames, QualityFlags.GAP_FILLED)
    resets = _count_flag(frames, QualityFlags.RESET_CORRECTED)
    days = (window[1] - window[0]).days

    quality: dict = {
        "coverage": f"{_fmt_date(window[0])} → {_fmt_date(window[1])}   ({days} days)",
        "grid": f"{grid_label}  ·  {report['intervals'] or 0:,} intervals",
        "series": series_rows,
        "gaps": (f"{gaps} interval(s) flagged as gaps" if gaps else "none detected"),
        "resets": (f"{resets} detected and corrected" if resets else "none detected"),
        "registers": _register_summary(present),
    }
    if report["price_granularity_lost"]["lost"]:
        native = report["price_granularity_lost"]["native_resolution_s"]
        quality["price_warning"] = (
            f"Your prices change every {_fmt_res(native)} but the run is {grid_label}, so the "
            "run sees one averaged price per interval and cannot act on within-interval swings."
        )

    return {
        "summary": f"Home Assistant · {len(frames)} series · simulated {grid_label}",
        "days": days,
        "source": "Home Assistant",
        # Connection block: after a fetch the browser holds the token; the server only knows a
        # dataset exists. The template's connection card is driven client-side (ha_fetch.js).
        "ha": None,
        "mapping": mapping,
        "quality": quality,
    }


def _register_summary(present: dict[str, SeriesFrame]) -> str:
    """T1/T2 mapping summary (specs §6.4 availability — the always-shown, contract-free fact)."""
    def mark(name: str) -> str:
        f = present.get(name)
        if f is None:
            return "not mapped"
        active = len(f.values) and float(np.nansum(f.values)) > 0
        return "mapped, active" if active else "mapped, flat"

    return f"import T1 {mark('grid_import_t1')} · T2 {mark('grid_import_t2')}"
