"""The series vocabulary and slot metadata (specs/05-data-formats.md §4.1).

The closed set of internal series names, shared by the Home Assistant and CSV paths. On the HA
path these name the rows of the mapping table; a fetched statistic is bound to one of these
slots by the user. The backend uses this to know each mapped series' `kind` (energy vs price)
and whether it is required, so an ingest payload can be validated against the roster the setup
band implies (specs §2.2, §2.1).

This is the authoritative list for ingest validation, the counterpart to `app/features.py`'s
closed feature-key vocabulary. It is intentionally a plain table, not a registry with
behaviour: the point is a name a downstream consumer can rely on (same discipline as §4.1).

Main items:
    SeriesKind                 "energy" | "price".
    Requirement                "required" | "conditional" | "cost_optional" | "optional".
    SERIES_SLOTS               ordered tuple of SlotSpec, one per §4.1 row.
    SLOT_BY_NAME               name → SlotSpec lookup.
    is_known_series(name)      True if the name is in the vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SeriesKind = Literal["energy", "price"]
Requirement = Literal["required", "conditional", "cost_optional", "optional"]


@dataclass(frozen=True)
class SlotSpec:
    """One series slot (specs §4.1 row): its internal name, kind, and requirement level.

    `pv_only` marks a slot present only when the household declared PV (cfg.has_pv); `cost_only`
    marks a slot offered only under cost simulation (cfg.simulate_cost). These gate whether the
    slot appears in the mapping roster (specs §2.2), not whether an ingest carrying it is
    accepted — a payload naming a valid slot is always parsed.
    """

    name: str
    kind: SeriesKind
    requirement: Requirement
    pv_only: bool = False
    cost_only: bool = False


# One entry per row of the §4.1 vocabulary table, in mapping order.
SERIES_SLOTS: tuple[SlotSpec, ...] = (
    SlotSpec("grid_import_t1", "energy", "required"),
    SlotSpec("grid_import_t2", "energy", "optional"),  # "expected" — see §4.1 note 4
    SlotSpec("grid_export_t1", "energy", "required"),
    SlotSpec("grid_export_t2", "energy", "optional"),
    SlotSpec("solar_production", "energy", "conditional", pv_only=True),
    SlotSpec("battery_charge", "energy", "optional"),
    SlotSpec("battery_discharge", "energy", "optional"),
    SlotSpec("price_spot", "price", "required"),
    SlotSpec("price_spot_min", "price", "cost_optional", cost_only=True),
    SlotSpec("price_spot_max", "price", "cost_optional", cost_only=True),
    SlotSpec("power_grid", "energy", "optional"),  # signed W; §4.1 power slot
    SlotSpec("house_load", "energy", "optional"),
)

SLOT_BY_NAME: dict[str, SlotSpec] = {s.name: s for s in SERIES_SLOTS}


def is_known_series(name: str) -> bool:
    """True if `name` is in the closed series vocabulary (accepted by ingest)."""
    return name in SLOT_BY_NAME
