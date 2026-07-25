"""Static sample view-model for the frontend scaffold.

This module hard-codes the numbers shown in the UX wireframes (specs/02-ux-wireframes.md).
It exists so the templates can render the *shape* of the real product before any feature
logic — ingestion, simulation, pricing — is wired up. Nothing here is computed; every value
is a placeholder lifted from the wireframe so the page reads like the intended app.

The single entry point is `sample_view()`, which returns the dict the index template
consumes. When the real service layer lands (specs/08-architecture.md §5.1), this module is
replaced by the result object of specs/07-internal-representation.md §4.5 — the template
field names deliberately mirror that eventual structure.

`sample_view()` includes `data_summary` (specs §2.3a) unconditionally so a demo render shows the
band. The real page hides it in the empty/pre-fetch state: app/main.py drops `data_summary` from
the context when no dataset is loaded, since the band has nothing to summarise until data exists
(§3.4). Once a dataset IS loaded, main.py replaces this sample with the COMPUTED band from
app/summary_view.py (the real §6.3/§6.11 figures over the persisted frames); the sample here is the
empty-state-free demo shape and the shared shape contract in tests/test_data_summary.py. The
template itself guards on `data_summary` being present.

Current variant: the app default — has_pv=True, simulate_cost=False (energy only). These two
choices are the setup band (specs/02-ux-wireframes.md §2.1); they drive which series/slots
panel ① asks for, which boxes panel ② shows, and which sections panel ③ renders. They are NOT
sample data any more: main.py reads them off the persisted SimulationConfig and renders them
through templates/_setup_band.html. This module therefore supplies only `data`, `data_summary`
and `results` — panel ② renders from app/params_view.py in every code path.

Translatable chrome vs. data. Some values here are UI chrome that must translate (role
labels, series names, warning sentences, policy descriptions); others are data that must not
(entity IDs, numbers, coverage strings, band values). Chrome strings are wrapped in `_N(...)`
below — a no-op marker whose only job is to make `pybabel extract` discover the English
source string as a msgid. The actual translation happens in the template, which calls
`_(value)` on the (still-English) string at render time. Data values are left bare.
"""


def _N(s: str) -> str:
    """gettext extraction marker (no-op at runtime).

    Marks a string literal so `pybabel extract` records it as a translatable msgid, without
    translating here — translation happens in the template via `_(value)`. This keeps the
    active-locale lookup at render time while still exposing these strings to extraction.
    """
    return s


def _sources_for(name: str) -> list[dict]:
    """The drawer's source list for the slot named `name` (specs §2.2 slot-first sources).

    Built from the same registry the real view-model (app/data_view.py) reads, so the empty-state
    sample offers exactly the sources a live dataset would. Returns the small {key,label,kind,
    blurb} dicts the drawer renders. Descriptor labels/blurbs are English source strings; they
    are marked for extraction in _SOURCE_STRINGS below and translated in the template via _().
    """
    from app.domain.series_vocab import SLOT_BY_NAME
    from app.sources import registry

    slot = SLOT_BY_NAME.get(name)
    if slot is None:
        return []
    return [
        {"key": d.key, "label": d.label, "kind": d.kind, "blurb": d.blurb}
        for d in registry.sources_for(slot)
    ]


def _info_for(name: str) -> str | None:
    """The slot's picker ⓘ blurb (specs §4.1), or None. Single-sourced from `SlotSpec.info` so the
    sample uses the same English string (and thus the same msgid) as the real view-model."""
    from app.domain.series_vocab import SLOT_BY_NAME

    slot = SLOT_BY_NAME.get(name)
    return slot.info if slot is not None else None


# Source descriptor labels/blurbs live in app/sources/*.py (not string literals here), so
# pybabel would not otherwise discover them as msgids. Mark them for extraction once, so the
# template's _(source.label) / _(source.blurb) calls have catalog entries to look up. Keep this
# list in step with the SourceDescriptor labels/blurbs in app/sources/.
_SOURCE_STRINGS = [
    _N("Home Assistant"),
    _N("Fetched from your Home Assistant in your browser; the token never reaches this app."),
    _N("Preset historical (Energy-Charts NL)"),
    _N("NL day-ahead spot prices from 2023 to today: committed on disk and bridged live "
       "to the end of your selected range."),
]

def _panel_data():
    """Panel ① — data input summary + expanded body (§2.2)."""
    return {
        "summary": "Home Assistant · 5 series · simulated hourly",
        "days": 412,
        "source": "Home Assistant",
        "ha": {
            "base_url": "http://homeassistant.local:8123",
            "connected": True,
            "version": "HA 2026.6.2",
            "statistic_count": "1,284",
        },
        # Series mapping table. `req` is one of required / conditional / cost_optional /
        # optional, rendered as ● / ◐ / ◒ / ○.
        #
        # The slot roster is derived from the setup band (§2.2): rows flagged `pv_only` show
        # only when cfg.has_pv; rows flagged `cost_only` show only when cfg.simulate_cost.
        # The two price-bracketing rows below are cost_only, so with this sample's
        # simulate_cost=False they are absent; they appear when cost simulation is enabled.
        # Each row carries its per-slot source provenance (specs §2.2 slot-first): `source` is
        # the descriptor key of the chosen source (or None for an unfilled slot), and `sources`
        # is the drawer's option list for that slot (built from the registry via _sources_for).
        # This sample shows a populated look: the grid/solar rows are Home Assistant, price_spot
        # is the preset Energy-Charts source, and the optional/bracket rows are still unchosen.
        # The two corroboration rows (power_grid, house_load) carry an `info` blurb so the demo
        # previews the picker's ⓘ affordance; `_info_for` single-sources the text from SlotSpec.
        "mapping": [
            {"name": "grid_import_t1", "role": _N("Grid import T1"), "req": "required", "entity": "sensor.electricity_meter_import_t1", "stat_id": "sensor.electricity_meter_import_t1", "source": "home_assistant", "sources": _sources_for("grid_import_t1")},
            {"name": "grid_import_t2", "role": _N("Grid import T2"), "req": "required", "entity": "sensor.electricity_meter_import_t2", "stat_id": "sensor.electricity_meter_import_t2", "source": "home_assistant", "sources": _sources_for("grid_import_t2")},
            {"name": "grid_export_t1", "role": _N("Grid export T1"), "req": "required", "entity": "sensor.electricity_meter_export_t1", "stat_id": "sensor.electricity_meter_export_t1", "source": "home_assistant", "sources": _sources_for("grid_export_t1")},
            {"name": "grid_export_t2", "role": _N("Grid export T2"), "req": "required", "entity": "sensor.electricity_meter_export_t2", "stat_id": "sensor.electricity_meter_export_t2", "source": "home_assistant", "sources": _sources_for("grid_export_t2")},
            {"name": "solar_production", "role": _N("Solar production"), "req": "conditional", "entity": "sensor.solar_total_production", "stat_id": "sensor.solar_total_production", "pv_only": True, "source": "home_assistant", "sources": _sources_for("solar_production")},
            {"name": "battery_charge", "role": _N("Battery charge"), "req": "optional", "entity": None, "stat_id": None, "source": None, "sources": _sources_for("battery_charge")},
            {"name": "battery_discharge", "role": _N("Battery discharge"), "req": "optional", "entity": None, "stat_id": None, "source": None, "sources": _sources_for("battery_discharge")},
            {"name": "price_spot", "role": _N("Spot price"), "req": "required", "entity": "sensor.epex_spot_price", "stat_id": None, "source": "energy_charts", "sources": _sources_for("price_spot")},
            {"name": "price_spot_min", "role": _N("Spot price (min)"), "req": "cost_optional", "entity": None, "cost_only": True, "source": None, "sources": _sources_for("price_spot_min")},
            {"name": "price_spot_max", "role": _N("Spot price (max)"), "req": "cost_optional", "entity": None, "cost_only": True, "source": None, "sources": _sources_for("price_spot_max")},
            {"name": "power_grid", "role": _N("Grid power"), "req": "optional", "entity": None, "stat_id": None, "source": None, "sources": _sources_for("power_grid"), "info": _info_for("power_grid")},
            {"name": "house_load", "role": _N("House load"), "req": "optional", "entity": None, "stat_id": None, "source": None, "sources": _sources_for("house_load"), "info": _info_for("house_load")},
        ],
        "quality": {
            "coverage": "2025-06-01 → 2026-07-21   (416 days)",
            "grid": "hourly  ·  8,760 intervals",
            # Per-series granularity (§2.2 "Granularity, per series").
            # `warn` marks the one lossy reconciliation (a price averaged down).
            "series": [
                {"name": _N("Grid import T1"), "recorded": ["hourly (full)", "5-min (last 9 days)"], "uses": "hourly"},
                {"name": _N("Grid import T2"), "recorded": ["hourly (full)", "5-min (last 9 days)"], "uses": "hourly"},
                {"name": _N("Grid export T1"), "recorded": ["hourly (full)", "5-min (last 9 days)"], "uses": "hourly"},
                {"name": _N("Grid export T2"), "recorded": ["hourly (full)", "5-min (last 9 days)"], "uses": "hourly"},
                {"name": _N("Solar production"), "recorded": ["hourly (full)"], "uses": "hourly"},
                {"name": _N("Spot price"), "recorded": ["15-min (full)"], "uses": "hourly, averaged", "warn": True},
            ],
            "price_warning": _N(
                "Your prices change every 15 minutes but your meter records hourly, so the "
                "run sees one averaged price per hour and cannot act on within-hour swings."
            ),
            "gaps": "3 gaps totalling 4.2 h  (0.04%)",
            "resets": "2 detected and corrected",
            # Note: literal percent signs in translatable strings use U+FF05 (fullwidth ％),
            # not ASCII %, so Babel's printf-format checker does not treat them as format
            # placeholders. See app/i18n.py and the README i18n note.
            "load_warning": _N(
                "Reconstructed load is negative in 41 intervals (0.41％). Usually means the "
                "solar sensor does not cover the whole house, or a clock offset between sensors."
            ),
            "registers": "T1 ✓ mapped    T2 ✓ mapped, active",
        },
    }


def _data_summary():
    """The data summary band — "Your data at a glance" (specs/02-ux-wireframes.md §2.3a).

    The battery-free figures that follow from the household's OWN recorded data before the
    SIMULATED battery is configured: the §6.11 energy row (minus efc, which counts the simulated
    battery's cycles) over the §6.3 load reconstruction, plus the raw grid/price aggregates.

    This sample shows the EXISTING-battery variant: `battery` is populated, so the band renders a
    "Your existing battery" throughput group and the Household/Solar figures are flagged
    `net_battery` — reconstructed net of the battery the household already owns (§6.3 strips it).
    The optional groups follow omit-don't-zero (§2.4): `solar` present because this sample has PV
    (CONFIG.has_pv), `battery` present because its sensors are mapped, `price` present because a
    spot series was loaded. A no-PV / no-existing-battery dataset would set the respective keys to
    None and the template would drop those groups.

    Numbers are illustrative and consistent with the panel ①/③ samples (4,129 kWh imported,
    3,180 kWh exported, 31% self-sufficiency). Consumption is the reconstructed household load
    net of the existing battery; self-consumption is 1 − export/pv.
    """
    return {
        "coverage": "2025-06-01 → 2026-07-21",
        "days": 416,
        # Always present.
        "grid": {"imported": "4,129 kWh", "exported": "3,180 kWh"},
        # Always present. `net_battery` flags that the reconstruction stripped an existing
        # battery (§6.3), so the template labels this (and Solar) "net of your existing battery".
        # `self_sufficiency_clamped` marks a negative self-sufficiency the display clamped to ≥ 0%
        # (import > load over the window — an existing battery net-charging; §2.3a); False here.
        "household": {
            "consumption": "6,540 kWh", "self_sufficiency": "31%", "net_battery": True,
            "self_sufficiency_clamped": False,
        },
        # PV present (CONFIG.has_pv). Omitted (None) for a no-PV dataset. `partial` False here
        # (the sample PV spans the whole window); a real short-coverage PV series sets it True and
        # carries its own coverage/days so "Produced" is not read against the full window.
        "solar": {
            "produced": "4,820 kWh", "self_consumption": "58%",
            "coverage": "2025-06-01 → 2026-07-21", "days": 416, "partial": False,
        },
        # Existing battery present: its measured charge-in / discharge-out over the window. This
        # is the battery the household ALREADY owns, not the one panel ② will simulate. Omitted
        # (None) when no battery_charge/battery_discharge series was mapped.
        "battery": {"charged": "2,510 kWh", "discharged": "2,240 kWh"},
        # Spot price context over the window (battery-free: the price is an input, §1.4). Omitted
        # (None) when no price series was loaded.
        "price": {"avg": "0.142 €/kWh", "min": "−0.021 €/kWh", "max": "0.487 €/kWh"},
        # Data-quality caveats (specs §2.3a): empty in this clean sample. The computed path
        # (app/summary_view.py) fills e.g. {"key": "load_unreliable", ...} or {"key": "solar_empty"}.
        "notes": [],
    }


def _panel_results():
    """Panel ③ — results, ENERGY SAVINGS section (§2.4). Cost section omitted (cost off)."""
    return {
        # The picker's coverage line, split so the template can render the day count (which needs
        # ngettext) between the dates and the run description. `period` keeps the whole line.
        "period": "2025-07-22 → 2026-07-21 · simulated hourly · 8,760 intervals",
        "period_dates": "2025-07-22 → 2026-07-21",
        "period_days": 365,
        "period_run": "simulated hourly · 8,760 intervals",
        # No `periods` list: the template hardcodes its five preset buttons (token, label, key)
        # and only reads `period_selected` to decide which is active. The computed path dropped
        # its parallel `periods` key for the same reason.
        "period_selected": "1 year",
        # Three KPI tiles. `unit` is rendered smaller and inline beside the big value.
        "kpis": [
            # The delta is the saving as a fraction of the no-battery import (4,129 kWh), so
            # 1,412/4,129 = +34.2 %. It is SIGNED with the same convention the computed path uses
            # (results_view._fmt_signed_pct): "+" for a saving, U+2212 "−" for a negative one. The
            # sign used to be "−" here, which — beside a positive 1,412 kWh saved — read as the
            # opposite of the truth on the fresh-install path, where this fixture is what a user
            # actually sees.
            {"title": _N("GRID IMPORT SAVED"), "value": "1,412", "unit": "kWh", "delta": "+34.2 %"},
            {"title": _N("SELF-SUFFICIENCY"), "value": "31% → 52%", "delta": "+21 pp"},
            {"title": _N("EQUIVALENT FULL CYCLES"), "value": "241",
             "delta": _N("0.66 / day"), "extra": _N("2,410 kWh throughput")},
        ],
        # "Where the energy comes from" breakdown.
        "energy_breakdown": [
            {"label": _N("Grid import, no battery"), "value": "4,129 kWh"},
            {"label": _N("Grid import, with battery"), "value": "2,717 kWh"},
            {"label": _N("Grid import avoided"), "value": "1,412 kWh", "rule_above": True},
            {"label": _N("Charged into the battery"), "value": "2,664 kWh", "gap_above": True},
            {"label": _N("Discharged from the battery"), "value": "2,410 kWh"},
            {"label": _N("Conversion losses"), "value": "254 kWh"},
            {"label": _N("Standby consumption"), "value": "263 kWh"},
        ],
        # Benchmark bars. `frac` is the bar fill 0..1 relative to the widest baseline.
        "benchmark": {
            "rows": [
                {"label": _N("No battery"), "value": "0 kWh", "frac": 0.0, "dot": False},
                {"label": _N("Your policy"), "value": "1,412 kWh", "frac": 0.61, "dot": True},
                {"label": _N("Perfect foresight"), "value": "1,988 kWh", "frac": 0.86, "dot": True},
                {"label": _N("…if export allowed"), "value": "2,311 kWh", "frac": 1.0, "dot": True},
            ],
            "gloss": _N(
                "Your policy captures 71％ of the grid import a perfectly-informed battery "
                "could have avoided. Allowed to export, that ceiling rises to 2,311 kWh "
                "(a 61％ capture) — the extra is arbitrage your export setting currently forbids."
            ),
        },
        # The third row is KEPT even though results_from() does not emit it. §2.4's wireframe
        # lists it, and this module's job is the wireframe shape, not the current view-model's —
        # results_view.results_from's own docstring names this row as the one deliberate shape
        # difference, so the divergence is documented on both sides rather than silent. Drop it
        # here only when §2.4 drops it, or when the computed path starts emitting it.
        "secondary": [
            {"label": _N("Self-consumption ratio"), "value": "58% → 81%"},
            {"label": _N("Grid export"), "value": "3,180 → 1,742 kWh"},
            {"label": _N("Intervals battery was full / empty"), "value": "1,204 / 2,988"},
        ],
        # Monthly grid-import bar chart (Plotly). Values are illustrative. The computed path
        # (results_view._monthly_import) plots measured monthly import here, and the tab is
        # labelled for that; a per-month SAVINGS series is not built.
        "chart": {
            "months": ["Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"],
            "values": [64, 88, 112, 150, 176, 188, 172, 150, 120, 96, 78, 60],
        },
        "caveats": [
            _N("Simulated at hourly resolution. A 5-minute re-run over the last 9 days gives "
               "8.4％ lower savings — hourly buckets hide within-hour import/export overlap and "
               "flatter the battery. Treat the headline figure as an upper bound."),
            _N("Spot prices are quarter-hourly but the run is hourly, so the battery acted on an "
               "averaged price and could not chase within-hour swings."),
            _N("0.41％ of intervals had negative reconstructed load (clamped to 0)."),
        ],
    }


def sample_view():
    """The full view-model consumed by templates/index.html.

    `cfg` and `params` are NOT provided here. Both used to be sample literals (a `CONFIG` dict
    and a `_panel_params()` fixture), but main.py's index() replaces both unconditionally from
    the PERSISTED `SimulationConfig` — panel ② and the setup band have had a real backing store
    since Phase 6, so the sample copies could never render and were only a second, drifting
    statement of the appendix-A defaults. Their translatable policy labels live in
    app/params_view.py, which is where `pybabel extract` now finds them.
    """
    return {
        "data": _panel_data(),
        "data_summary": _data_summary(),
        "results": _panel_results(),
    }
