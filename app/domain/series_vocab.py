"""The series vocabulary and slot metadata (specs/05-data-formats.md §4.1).

The closed set of internal series names, shared by the Home Assistant and CSV paths. On the HA
path these name the rows of the mapping table; a fetched statistic is bound to one of these
slots by the user. The backend uses this to know each mapped series' `kind` (energy vs price)
and whether it is required, so an ingest payload can be validated against the roster the setup
band implies (specs §2.2, §2.1).

This is the authoritative list for ingest validation, the counterpart to `app/features.py`'s
closed feature-key vocabulary. It is intentionally a plain table, not a registry with
behaviour: the point is a name a downstream consumer can rely on (same discipline as §4.1).

The one translatable field is `SlotSpec.info` — an optional picker explanation, wrapped in the
local `_N` extraction marker so `pybabel extract` finds it; everything else here is bare data.

Main items:
    SeriesKind                 "energy" | "price".
    Requirement                "required" | "conditional" | "cost_optional" | "optional".
    SlotSpec                   one §4.1 row: name, kind, requirement, gating flags, optional info blurb.
    SERIES_SLOTS               ordered tuple of SlotSpec, one per §4.1 row.
    SLOT_BY_NAME               name → SlotSpec lookup.
    is_known_series(name)      True if the name is in the vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


def _N(s: str) -> str:
    """gettext extraction marker (no-op at runtime).

    Mirrors app/sample_data.py's marker: it makes `pybabel extract -k _N` record the English
    source string as a msgid without translating here. The `info` blurbs below are the only
    translatable chrome in this otherwise data-only module; translation happens at render time
    in the template via `_(value)`.
    """
    return s


SeriesKind = Literal["energy", "price"]
Requirement = Literal["required", "conditional", "cost_optional", "optional"]


@dataclass(frozen=True)
class SlotSpec:
    """One series slot (specs §4.1 row): its internal name, kind, and requirement level.

    `pv_only` marks a slot present only when the household declared PV (cfg.has_pv); `cost_only`
    marks a slot offered only under cost simulation (cfg.simulate_cost). These gate whether the
    slot appears in the mapping roster (specs §2.2), not whether an ingest carrying it is
    accepted — a payload naming a valid slot is always parsed.

    `info` is an optional one- or two-sentence explanation of why the slot is offered, shown by
    the picker's ⓘ affordance (a DaisyUI modal). It is the English source string / translation
    msgid; the template passes it through `_()`. A slot with `info=None` renders no icon, so the
    affordance is generic: a future series gets an explanation by populating this field, with no
    template change.
    """

    name: str
    kind: SeriesKind
    requirement: Requirement
    pv_only: bool = False
    cost_only: bool = False
    info: str | None = None


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
    SlotSpec(
        "power_grid",
        "energy",
        "optional",  # signed W; §4.1 power slot
        info=_N(
            "Optional. A signed instantaneous-power series. If you have this sensor, supplying "
            "it lets the app detect a clock offset between your meter and inverter — the main "
            "thing that can quietly distort a solar household's results."
        ),
    ),
    SlotSpec(
        "house_load",
        "energy",
        "optional",
        info=_N(
            "Optional. The app reconstructs household load from your grid meter, adding back "
            "any solar and existing-battery data you supply (with neither, it is just your grid "
            "load). If you have a direct house-load sensor, supplying it uses the real thing and "
            "shows how far the reconstruction would have drifted."
        ),
    ),
)

SLOT_BY_NAME: dict[str, SlotSpec] = {s.name: s for s in SERIES_SLOTS}


def is_known_series(name: str) -> bool:
    """True if `name` is in the closed series vocabulary (accepted by ingest)."""
    return name in SLOT_BY_NAME
