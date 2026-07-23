"""Static sample view-model for the frontend scaffold.

This module hard-codes the numbers shown in the UX wireframes (specs/02-ux-wireframes.md).
It exists so the templates can render the *shape* of the real product before any feature
logic — ingestion, simulation, pricing — is wired up. Nothing here is computed; every value
is a placeholder lifted from the wireframe so the page reads like the intended app.

The single entry point is `sample_view()`, which returns the dict the index template
consumes. When the real service layer lands (specs/08-architecture.md §5.1), this module is
replaced by the result object of specs/07-internal-representation.md §4.5 — the template
field names deliberately mirror that eventual structure.

Current variant: the app default — has_pv=True, simulate_cost=False (energy only). These two
choices are the setup band (specs/02-ux-wireframes.md §2.1); they drive which series/slots
panel ① asks for, which boxes panel ② shows, and which sections panel ③ renders. They live in
CONFIG below and are rendered by templates/_setup_band.html, not by either panel.

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

# --- Session-level configuration this sample represents -------------------------------
# Mirrors cfg fields from the spec. Drives which rows/boxes the templates show.
CONFIG = {
    "has_pv": True,
    "simulate_cost": False,   # spec default; hides the Pricing box and COST SAVINGS section
    "phases": 1,              # 1-phase → battery-phase selector is absent (§2.5)
    "coupling": "dc",         # DC-coupled / hybrid
}


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
        "mapping": [
            {"role": _N("Grid import T1"), "req": "required", "entity": "sensor.electricity_meter_import_t1"},
            {"role": _N("Grid import T2"), "req": "required", "entity": "sensor.electricity_meter_import_t2"},
            {"role": _N("Grid export T1"), "req": "required", "entity": "sensor.electricity_meter_export_t1"},
            {"role": _N("Grid export T2"), "req": "required", "entity": "sensor.electricity_meter_export_t2"},
            {"role": _N("Solar production"), "req": "conditional", "entity": "sensor.solar_total_production", "pv_only": True},
            {"role": _N("Battery charge"), "req": "optional", "entity": "— none —"},
            {"role": _N("Battery discharge"), "req": "optional", "entity": "— none —"},
            {"role": _N("Spot price"), "req": "required", "entity": "sensor.epex_spot_price"},
            {"role": _N("Spot price (min)"), "req": "cost_optional", "entity": "— none —", "cost_only": True},
            {"role": _N("Spot price (max)"), "req": "cost_optional", "entity": "— none —", "cost_only": True},
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


def _panel_params():
    """Panel ② — parameters summary + expanded body (§2.3, §2.5)."""
    return {
        # Summary line ends with the cost mode; energy only when simulate_cost is off (§2.1).
        "summary": "10.0 kWh · 5.0/5.0 kW · 90% · charge P3 · discharge P1 · energy only",
        "battery": {
            "capacity": "10.0", "min_soc": "10", "max_soc": "100",
            "max_charge": "5.0", "max_discharge": "5.0", "rte": "90",
            "standby": "30", "coupling": "AC-coupled", "initial_soc": "50",
        },
        "grid": {"phases": "1-phase", "fuse": "25", "max_import": "5.75", "export_limit": "same as import"},
        # Charge/discharge policy radio groups. `selected` marks the preselected option.
        # P1/P3 carry a [PV only] marker (shown because has_pv).
        "charge_policies": [
            {"key": "P1", "label": _N("Solar surplus only (net zero at the grid)"), "pv_only": True},
            {"key": "P2", "label": _N("Grid charge when spot price is in band")},
            {"key": "P3", "label": _N("Both"), "pv_only": True, "selected": True},
        ],
        "charge_band": {"a": "-0.050", "b": "0.040"},
        "discharge_policies": [
            {"key": "D1", "label": _N("Serve house load when consumption exceeds solar"), "selected": True},
            {"key": "D2", "label": _N("Maximise discharge when spot price is in band")},
            {"key": "D3", "label": _N("Both")},
        ],
        "discharge_band": {"c": "0.180", "d": "9.999"},
        "band_overlap_ok": True,
    }


def _panel_results():
    """Panel ③ — results, ENERGY SAVINGS section (§2.4). Cost section omitted (cost off)."""
    return {
        "period": "2025-07-22 → 2026-07-21 · simulated hourly · 8,760 intervals",
        "periods": [_N("1 week"), _N("1 month"), _N("3 months"), _N("6 months"), _N("1 year")],
        "period_selected": "1 year",
        # Three KPI tiles. `unit` is rendered smaller and inline beside the big value.
        "kpis": [
            {"title": _N("GRID IMPORT SAVED"), "value": "1,412", "unit": "kWh", "delta": "−34.2 %"},
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
        "secondary": [
            {"label": _N("Self-consumption ratio"), "value": "58% → 81%"},
            {"label": _N("Grid export"), "value": "3,180 → 1,742 kWh"},
            {"label": _N("Intervals battery was full / empty"), "value": "1,204 / 2,988"},
        ],
        # Monthly-savings bar chart (Plotly). Values are illustrative.
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
    """The full view-model consumed by templates/index.html."""
    return {
        "cfg": CONFIG,
        "data": _panel_data(),
        "params": _panel_params(),
        "results": _panel_results(),
    }
