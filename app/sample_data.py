"""Static sample view-model for the frontend scaffold.

This module hard-codes the numbers shown in the UX wireframes (docs/specs/02-ux-wireframes.md).
It exists so the templates can render the *shape* of the real product before any feature
logic — ingestion, simulation, pricing — is wired up. Nothing here is computed; every value
is a placeholder lifted from the wireframe so the page reads like the intended app.

The single entry point is `sample_view()`, which returns the dict the index template
consumes. When the real service layer lands (docs/specs/08-architecture.md §5.1), this module is
replaced by the result object of docs/specs/07-internal-representation.md §4.5 — the template
field names deliberately mirror that eventual structure.

`sample_view()` includes `data_summary` (specs §2.3a) unconditionally so a demo render shows the
band. The real page hides it in the empty/pre-fetch state: app/main.py drops `data_summary` from
the context when no dataset is loaded, since the band has nothing to summarise until data exists
(§3.4). Once a dataset IS loaded, main.py replaces this sample with the COMPUTED band from
app/summary_view.py (the real §6.3/§6.11 figures over the persisted frames); the sample here is the
empty-state-free demo shape and the shared shape contract in tests/test_data_summary.py. The
template itself guards on `data_summary` being present.

Current variant: the app default — has_pv=True, simulate_cost=True (energy and cost). These two
choices are the setup band (docs/specs/02-ux-wireframes.md §2.1); they drive which series/slots
panel ① asks for, which boxes panel ② shows, and which sections panel ③ renders. They are NOT
sample data any more: main.py reads them off the persisted SimulationConfig and renders them
through templates/_setup_band.html. This module therefore supplies only `data`, `data_summary`
and `results` — panel ② renders from app/params_view.py in every code path.

Translatable chrome vs. data. Some values here are UI chrome that must translate (role
labels, series names, warning sentences, policy descriptions); others are data that must not
(entity IDs, ISO dates, numbers, band values). Two markers, for two different shapes:

  * `_N(...)` — a no-op extraction tagger for a CONSTANT string with no runtime values in it.
    The template translates it via `_(value)` at render time.
  * `_msg(...)` / `_msg_n(...)` (app/i18n.msg / .msg_n) — a `(msgid, params)` PAIR for a
    sentence that has figures in it. `templates/_msg.html` renders it: translate the constant
    msgid, then substitute. `_msg_n` is the counted form, so "1 day" and "9 days" both read
    right.

The pair shape is not optional here. The REAL view-models (app/data_view.panel_data_from and
app/results_view.results_from) emit pairs for exactly these fields, and this module's whole job
is to be shape-compatible with them — the sample is what a first-time user sees before any
dataset exists, and it renders through the same templates. A string with its figures baked in
would be a msgid `pybabel extract` cannot see, so the sample would render in English on a Dutch
page while the live page rendered in Dutch. Where a field's illustrative wording matches the
real one, this module deliberately reuses the REAL msgid rather than minting a parallel copy,
so the two cannot drift apart in the catalog.

  * `num(...)` (app/i18n.num) — a FIGURE, as the number plus the name of a convention, formatted
    at render time in the request's locale (A6). Same reasoning as the pair, applied to digits
    rather than words: Dutch writes 4.129 kWh and 0,142 €/kWh where English writes 4,129 kWh and
    0.142 €/kWh, and a number written out here is written out in one language. Every figure in
    this module — the glance band, the KPI tiles, the breakdown, the benchmark rows, the counts
    inside sentences — is a `num()`, matching what the computed paths emit.

Data values are left bare where they are genuinely locale-independent: entity IDs, statistic IDs,
ISO dates (see `data_view._fmt_date` for why dates do not follow the figures), the `period`
fallback line, and the chart's month NUMBERS, which the template names through the locale-bound
`monthname` filter.
"""

from app.i18n import msg as _msg, msg_n as _msg_n, num


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


def _req_for(name: str) -> str:
    """The slot's requirement level (specs §4.1), single-sourced from `SlotSpec.requirement`.

    Same discipline as `_info_for`: the sample roster paints the same ●/◐/○ marker the live one
    does. Hand-copying this field is what let the demo drift — it showed the T2 registers as
    `required` while the vocabulary called them `optional`, which is the level §4.1 note 4's
    *expected* collapses to (there is no "expected" level in code). Falling back to "optional"
    for an unknown name keeps the sample from claiming a slot is mandatory on a typo.
    """
    from app.domain.series_vocab import SLOT_BY_NAME

    slot = SLOT_BY_NAME.get(name)
    return slot.requirement if slot is not None else "optional"


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
    _N("Preset historical (ENTSO-E NL)"),
    _N("NL day-ahead spot prices from mid-2022, extracted from the ENTSO-E transparency "
       "platform at their native hourly then quarter-hourly resolution."),
]

def _res(label: str) -> dict:
    """A resolution label ("hourly", "15-min", …) as a nested message — data_view's `_res_msg`.

    A resolution is a WORD embedded in half a dozen sentences, not a figure, so it has to be
    translated on its own: interpolation runs AFTER the catalog lookup, so a bare string param
    would put "hourly" into an otherwise-Dutch sentence. `templates/_msg.html` renders a param
    that is itself a message recursively, which is what makes that work.

    The label is a runtime value here, so `pybabel extract` does not see it from this module —
    it does not need to. These are the same five msgids `app/data_view._RES_LABELS` carries and
    `_N`-marks, which is deliberate: one catalog entry per resolution, shared by both paths.
    Passing a label this table does not contain would render it untranslated.
    """
    return _msg(label)


def _recorded_full(label: str) -> dict:
    """A "recorded at" cell for a series' native resolution — data_view's `%(res)s (full)`."""
    return _msg("%(res)s (full)", res=_res(label))


def _recorded_fine(label: str, days: int) -> dict:
    """A "recorded at" cell for the finer copy fetched over a sub-window (specs §4.3).

    Counted: the sample's own figure is 9 days, but the singular exists on the real path and the
    two share this msgid, so the plural must come from the count rather than from the English.
    """
    return _msg_n(
        "%(res)s (last %(n)s day)",
        "%(res)s (last %(n)s days)",
        days,
        res=_res(label),
        n=num(days, "count"),
    )


def _panel_data():
    """Panel ① — data input summary + expanded body (§2.2).

    Every sentence here is a `_msg` / `_msg_n` pair with the same msgid the real view-model
    (app/data_view.panel_data_from) emits for the same field, so the sample and the live page
    render in the same language. Only the four fields whose illustrative wording has no
    counterpart in the real path (gaps, registers, price_warning, load_warning — the real path
    words them differently or does not compute them yet) carry their own msgids.
    """
    return {
        # Counted for the same reason as the real path: "series" is invariant in English but not
        # in Dutch, so the plural form has to come from the count rather than from the English.
        "summary": _msg_n(
            "Home Assistant · %(n)s series · simulated %(res)s",
            "Home Assistant · %(n)s series · simulated %(res)s",
            5,
            n=num(5, "count"),
            res=_res("hourly"),
        ),
        "days": 412,
        "source": "Home Assistant",
        "ha": {
            "base_url": "http://homeassistant.local:8123",
            "connected": True,
            "version": "HA 2026.6.2",
            "statistic_count": "1,284",
        },
        # Series mapping table. `req` is one of required / conditional / optional, rendered as
        # ● / ◐ / ○. It comes from `_req_for`, i.e. from SlotSpec, rather than being written out
        # here: hand-copied, it drifted, and the demo painted the T2 registers ● while the live
        # roster painted them ○. §4.1 note 4 marks T2 *expected* — both registers should be there,
        # but a single-tariff meter that fills only T1 still runs, so nothing gates on them.
        #
        # The slot roster is derived from the setup band (§2.2): rows flagged `pv_only` show
        # only when cfg.has_pv; rows flagged `battery_only` only when cfg.has_battery.
        # Each row carries its per-slot source provenance (specs §2.2 slot-first): `source` is
        # the descriptor key of the chosen source (or None for an unfilled slot), and `sources`
        # is the drawer's option list for that slot (built from the registry via _sources_for).
        # This sample shows a populated look: the grid/solar rows are Home Assistant, price_spot
        # is the preset Energy-Charts source, and the optional rows are still unchosen.
        # The two corroboration rows (power_grid, house_load) carry an `info` blurb so the demo
        # previews the picker's ⓘ affordance; `_info_for` single-sources the text from SlotSpec.
        "mapping": [
            {"name": "grid_import_t1", "role": _N("Grid import T1"), "req": _req_for("grid_import_t1"), "entity": "sensor.electricity_meter_import_t1", "stat_id": "sensor.electricity_meter_import_t1", "source": "home_assistant", "sources": _sources_for("grid_import_t1")},
            {"name": "grid_import_t2", "role": _N("Grid import T2"), "req": _req_for("grid_import_t2"), "entity": "sensor.electricity_meter_import_t2", "stat_id": "sensor.electricity_meter_import_t2", "source": "home_assistant", "sources": _sources_for("grid_import_t2")},
            {"name": "grid_export_t1", "role": _N("Grid export T1"), "req": _req_for("grid_export_t1"), "entity": "sensor.electricity_meter_export_t1", "stat_id": "sensor.electricity_meter_export_t1", "source": "home_assistant", "sources": _sources_for("grid_export_t1")},
            {"name": "grid_export_t2", "role": _N("Grid export T2"), "req": _req_for("grid_export_t2"), "entity": "sensor.electricity_meter_export_t2", "stat_id": "sensor.electricity_meter_export_t2", "source": "home_assistant", "sources": _sources_for("grid_export_t2")},
            {"name": "solar_production", "role": _N("Solar production"), "req": _req_for("solar_production"), "entity": "sensor.solar_total_production", "stat_id": "sensor.solar_total_production", "pv_only": True, "source": "home_assistant", "sources": _sources_for("solar_production")},
            {"name": "battery_charge", "role": _N("Battery charge"), "req": _req_for("battery_charge"), "entity": None, "stat_id": None, "battery_only": True, "source": None, "sources": _sources_for("battery_charge")},
            {"name": "battery_discharge", "role": _N("Battery discharge"), "req": _req_for("battery_discharge"), "entity": None, "stat_id": None, "battery_only": True, "source": None, "sources": _sources_for("battery_discharge")},
            {"name": "price_spot", "role": _N("Spot price"), "req": _req_for("price_spot"), "entity": "sensor.epex_spot_price", "stat_id": None, "source": "energy_charts", "sources": _sources_for("price_spot")},
            {"name": "power_grid", "role": _N("Grid power"), "req": _req_for("power_grid"), "entity": None, "stat_id": None, "source": None, "sources": _sources_for("power_grid"), "info": _info_for("power_grid")},
            {"name": "house_load", "role": _N("House load"), "req": _req_for("house_load"), "entity": None, "stat_id": None, "source": None, "sources": _sources_for("house_load"), "info": _info_for("house_load")},
        ],
        "quality": {
            # The dates are pure data; only the day count carries a word, so only that part is a
            # msgid. Same shape and same msgid as data_view's, so one catalog entry serves both.
            "coverage": _msg_n(
                "%(dates)s   (%(n)s day)",
                "%(dates)s   (%(n)s days)",
                416,
                dates="2025-06-01 → 2026-07-21",
                n=num(416, "count"),
            ),
            "grid": _msg_n(
                "%(res)s  ·  %(n)s interval",
                "%(res)s  ·  %(n)s intervals",
                8760,
                res=_res("hourly"),
                n=num(8760, "count"),
            ),
            # Per-series granularity (§2.2 "Granularity, per series").
            # `warn` marks the one lossy reconciliation (a price averaged down).
            #
            # Each cell is one message with the resolution nested inside it rather than a label
            # with a suffix glued on: ", averaged" is not a suffix in every language, and the
            # fine-copy cell's day count needs a plural rule the English "s" cannot express.
            "series": [
                {"name": _N("Grid import T1"), "recorded": [_recorded_full("hourly"), _recorded_fine("5-min", 9)], "uses": _res("hourly")},
                {"name": _N("Grid import T2"), "recorded": [_recorded_full("hourly"), _recorded_fine("5-min", 9)], "uses": _res("hourly")},
                {"name": _N("Grid export T1"), "recorded": [_recorded_full("hourly"), _recorded_fine("5-min", 9)], "uses": _res("hourly")},
                {"name": _N("Grid export T2"), "recorded": [_recorded_full("hourly"), _recorded_fine("5-min", 9)], "uses": _res("hourly")},
                {"name": _N("Solar production"), "recorded": [_recorded_full("hourly")], "uses": _res("hourly")},
                {"name": _N("Spot price"), "recorded": [_recorded_full("15-min")],
                 "uses": _msg("%(res)s, averaged", res=_res("hourly")), "warn": True},
            ],
            # Worded from the household's point of view ("your meter records hourly") rather than
            # the run's, which is how the real path words it, and it spells the native resolution
            # out ("every 15 minutes") where the real path nests the "15-min" LABEL. Its own msgid
            # for both reasons; kept as-is so the sample's English does not change. Only the
            # meter's own resolution is held out as a param, since that is the one word the real
            # path also treats as a translatable label.
            "price_warning": _msg(
                "Your prices change every 15 minutes but your meter records %(res)s, so the "
                "run sees one averaged price per hour and cannot act on within-hour swings.",
                res=_res("hourly"),
            ),
            # The real path counts flagged INTERVALS ("3 intervals flagged as gaps"); this sample
            # predates that computation and shows a duration/share instead, so it has its own
            # msgid. Counted on the gap count, which is the number the sentence leads with.
            "gaps": _msg_n(
                "%(n)s gap totalling %(hours)s h  (%(pct)s)",
                "%(n)s gaps totalling %(hours)s h  (%(pct)s)",
                3,
                n=num(3, "count"), hours=num(4.2, "dec1"), pct=num(0.0004, "pct_dec2"),
            ),
            # Same msgid as data_view's uncounted reset line (its English carries no noun to
            # pluralise, so a translator whose language needs one rephrases the whole clause).
            "resets": _msg("%(n)s detected and corrected", n=num(2, "count")),
            # A literal "%" is inert everywhere now — app/i18n.interpolate doubles every percent
            # sign that does not begin a "%(name)s" placeholder, and _() no longer %-formats at
            # all (i18n.install_for, newstyle=False). The fullwidth "％" this string used to carry
            # was a workaround for that trap and was rendering a literal ％ to the user.
            "load_warning": _msg(
                "Reconstructed load is negative in %(n)s intervals (%(pct)s). Usually means the "
                "solar sensor does not cover the whole house, or a clock offset between sensors.",
                n=num(41, "count"), pct=num(0.0041, "pct_dec2"),
            ),
            # The real path words this "import T1 <mark> · T2 <mark>" with the per-register marks
            # as nested messages, because there it picks one of three marks per register at
            # runtime. Here both marks are fixed, so the whole line is ONE constant msgid — there
            # is no runtime value to hold out, and a single reorderable sentence translates better
            # than one assembled from parts. `_N` rather than `_msg`: with no params it is a plain
            # string, which the template's `msg()` macro also accepts.
            "registers": _N("T1 ✓ mapped    T2 ✓ mapped, active"),
        },
    }


def _data_summary():
    """The data summary band — "Your data at a glance" (docs/specs/02-ux-wireframes.md §2.3a).

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

    Every FIGURE here is a `num()` dict rather than a pre-formatted string (A6), matching what
    `summary_view.data_summary_from` now emits: the number travels and `templates/_msg.html`
    formats it in the render locale, so this band reads 4.129 kWh on a Dutch page and 4,129 kWh on
    an English one. Writing them as literal strings here would have hardcoded the English
    separators into the fresh-install page — the same defect on the sample side, which is what A7
    was about the first time. `coverage` and `days` stay as they are, for the reasons
    `summary_view`'s module docstring gives (the template splits `coverage` on " → ").
    """
    return {
        "coverage": "2025-06-01 → 2026-07-21",
        "days": 416,
        # Always present.
        "grid": {"imported": num(4129, "kwh"), "exported": num(3180, "kwh")},
        # Always present. `net_battery` flags that the reconstruction stripped an existing
        # battery (§6.3), so the template labels this (and Solar) "net of your existing battery".
        # `self_sufficiency_clamped` marks a negative self-sufficiency the display clamped to ≥ 0%
        # (import > load over the window — an existing battery net-charging; §2.3a); False here.
        "household": {
            "consumption": num(6540, "kwh"), "self_sufficiency": num(0.31, "pct"),
            "net_battery": True,
            "self_sufficiency_clamped": False,
        },
        # PV present (CONFIG.has_pv). Omitted (None) for a no-PV dataset. `partial` False here
        # (the sample PV spans the whole window); a real short-coverage PV series sets it True and
        # carries its own coverage/days so "Produced" is not read against the full window.
        "solar": {
            "produced": num(4820, "kwh"), "self_consumption": num(0.58, "pct"),
            "coverage": "2025-06-01 → 2026-07-21", "days": 416, "partial": False,
        },
        # Existing battery present: its measured charge-in / discharge-out over the window. This
        # is the battery the household ALREADY owns, not the one panel ② will simulate. Omitted
        # (None) when no battery_charge/battery_discharge series was mapped.
        "battery": {"charged": num(2510, "kwh"), "discharged": num(2240, "kwh")},
        # Spot price context over the window (battery-free: the price is an input, §1.4). Omitted
        # (None) when no price series was loaded.
        "price": {"avg": num(0.142, "eur_kwh"), "min": num(-0.021, "eur_kwh"),
                  "max": num(0.487, "eur_kwh")},
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
        # Same msgid and same counted shape as results_view's, with the resolution nested so it is
        # translated rather than substituted as an English word. `period` above stays a plain
        # unsplit string, matching the real path's deliberately-untranslated fallback field.
        "period_run": _msg_n(
            "simulated %(res)s · %(n)s interval",
            "simulated %(res)s · %(n)s intervals",
            8760,
            res=_res("hourly"),
            n=num(8760, "count"),
        ),
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
            #
            # The first two tiles' `value` and `delta` are formatted FIGURES with no words in them
            # ("+34.2 %", "+21 pp"), so they stay plain strings — as they do on the computed path,
            # which has no msgid to offer for a number. The third tile's `delta`/`extra` carry
            # words ("/ day", "throughput") and so are `_msg` pairs with the real path's msgids.
            {"title": _N("GRID IMPORT SAVED"), "value": num(1412, "kwh_bare"), "unit": "kWh",
             "delta": num(34.2, "pct_signed")},
            {"title": _N("SELF-SUFFICIENCY"),
             "value": _msg("%(before)s → %(after)s", before=num(0.31, "pct"), after=num(0.52, "pct")),
             "delta": _msg("%(pp)s pp", pp=num(21, "dec0_signed"))},
            {"title": _N("EQUIVALENT FULL CYCLES"), "value": num(241, "count"),
             "delta": _msg("%(n)s / day", n=num(0.66, "dec2")),
             "extra": _msg("%(kwh)s throughput", kwh=num(2410, "kwh"))},
        ],
        # "Where the energy comes from" breakdown.
        "energy_breakdown": [
            {"label": _N("Grid import, no battery"), "value": num(4129, "kwh")},
            {"label": _N("Grid import, with battery"), "value": num(2717, "kwh")},
            {"label": _N("Grid import avoided"), "value": num(1412, "kwh"), "rule_above": True},
            {"label": _N("Charged into the battery"), "value": num(2664, "kwh"), "gap_above": True},
            {"label": _N("Discharged from the battery"), "value": num(2410, "kwh")},
            {"label": _N("Conversion losses"), "value": num(254, "kwh")},
            {"label": _N("Standby consumption"), "value": num(263, "kwh")},
        ],
        # Benchmark bars. `frac` is the bar fill 0..1 relative to the widest baseline.
        "benchmark": {
            "rows": [
                {"label": _N("No battery"), "value": num(0, "kwh"), "frac": 0.0, "dot": False},
                {"label": _N("Your policy"), "value": num(1412, "kwh"), "frac": 0.61, "dot": True},
                {"label": _N("Perfect foresight"), "value": num(1988, "kwh"), "frac": 0.86, "dot": True},
                {"label": _N("…if export allowed"), "value": num(2311, "kwh"), "frac": 1.0, "dot": True},
            ],
            # The wireframe's gloss, which is shorter than the computed path's (results_view's
            # shape-1 variants also state what perfect foresight knows) and states the ratios with
            # a "%" sign rather than the word. Its own msgid for that reason; the figures ride as
            # params so the constant text is what reaches the catalog. The two "%" signs were
            # fullwidth "％" — a workaround for the old newstyle %-formatting that was showing a
            # literal ％ to the reader; a literal "%" is inert now (app/i18n.interpolate).
            "gloss": _msg(
                "Your policy captures %(pct)s of the grid import a perfectly-informed battery "
                "could have avoided. Allowed to export, that ceiling rises to %(ceiling)s "
                "(a %(unc_pct)s capture) — the extra is arbitrage your export setting "
                "currently forbids.",
                pct=num(0.71, "pct"),
                ceiling=num(2311, "kwh"),
                unc_pct=num(0.61, "pct"),
            ),
        },
        # The third row is KEPT even though results_from() does not emit it. §2.4's wireframe
        # lists it, and this module's job is the wireframe shape, not the current view-model's —
        # results_view.results_from's own docstring names this row as the one deliberate shape
        # difference, so the divergence is documented on both sides rather than silent. Drop it
        # here only when §2.4 drops it, or when the computed path starts emitting it.
        "secondary": [
            {"label": _N("Self-consumption ratio"),
             "value": _msg("%(before)s → %(after)s", before=num(0.58, "pct"), after=num(0.81, "pct"))},
            {"label": _N("Grid export"),
             "value": _msg("%(before)s → %(after)s", before=num(3180, "count"), after=num(1742, "kwh"))},
            {"label": _N("Intervals battery was full / empty"),
             "value": _msg("%(full)s / %(empty)s", full=num(1204, "count"), empty=num(2988, "count"))},
        ],
        # Monthly grid-import bar chart (Plotly). Values are illustrative. The computed path
        # (results_view._monthly_import) plots measured monthly import here, and the tab is
        # labelled for that; a per-month SAVINGS series is not built.
        # `months` are MONTH NUMBERS, matching what results_view._monthly_import now emits: the
        # template's locale-bound `monthname` filter renders them, so the axis reads "aug sep okt"
        # on a Dutch page instead of the English abbreviations that used to be written out here
        # (A6). 8..12 then 1..7 is the same Aug→Jul span as before.
        "chart": {
            "months": [8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7],
            "values": [64, 88, 112, 150, 176, 188, 172, 150, 120, 96, 78, 60],
        },
        # Caveats, as `_msg` pairs — the same shape results_view.results_from emits, so the
        # template's `msg(c)` renders either. The wireframe's wording differs from the computed
        # path's (this one names the §6.13 resolution-bias diagnostic, which the real path does not
        # compute yet), so these keep their own msgids; only the figures were pulled out into
        # params. Their fullwidth "％" signs are now real "%" — see the gloss note above.
        "caveats": [
            # "5-minute" stays IN the msgid rather than riding as a param: it is a word, not a
            # figure, and it is not one of data_view's resolution labels (those are "5-min"), so
            # as a param it would be substituted after translation and stay English in Dutch.
            _msg("Simulated at %(res)s resolution. A 5-minute re-run over the last %(n)s days "
                 "gives %(delta)s lower savings — hourly buckets hide within-hour import/export "
                 "overlap and flatter the battery. Treat the headline figure as an upper bound.",
                 res=_res("hourly"), n=num(9, "count"), delta=num(0.084, "pct_dec1")),
            _msg("Spot prices are quarter-hourly but the run is %(res)s, so the battery acted on "
                 "an averaged price and could not chase within-hour swings.",
                 res=_res("hourly")),
            _msg("%(pct)s of intervals had negative reconstructed load (clamped to 0).",
                 pct=num(0.0041, "pct_dec2")),
        ],
    }


def sample_view():
    """The full view-model each screen falls back to as its EMPTY STATE.

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
